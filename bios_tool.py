import argparse
import logging
import sys
import redfish
import yaml
from redfish.rest.v1 import RetriesExhaustedError

from wekapyutils.wekalogging import configure_logging, register_module
from RedFishBMC import RedFishBMC
from BMCsetup import bmc_setup, get_ipmi_ip
from tabulate import tabulate

# get root logger
log = logging.getLogger()

class Server(object):
    def __init__(self, hostname, username, password):
        self.hostname = hostname
        self.username = username
        self.password = password
        self.bmc = None
        self.bios_settings = None
        self.manufacturer = None
        self.arch = None
        self.model = None


    def connect(self):
        try:
            # need to add a timeout here...
            self.bmc = RedFishBMC(self.hostname, username=self.username, password=self.password)
            self.bios_settings = self.bmc.get_bios_settings()
            self.manufacturer = self.bmc.manufacturer
            self.arch = self.bmc.arch
            self.model = self.bmc.model
            log.info(f"Connected to {self.hostname}")
            return self
        except redfish.rest.v1.InvalidCredentialsError:
            log.error(f"Invalid credentials for {self.hostname}")
        except RetriesExhaustedError:
            log.error(f"Error connecting to {self.hostname}: Retries exhausted.  Is the server running?")
        except Exception as exc:
            log.error(f"Error opening connections to {self.hostname}: {exc}")

        return None


    def close(self):
        if self.bmc:
            self.bmc.redfish.logout()


def csv_load(f):
    """
    Load a CSV file into a list of dictionaries
    :param f: file object
    :return: list of dictionaries
    """
    import csv
    reader = None
    exc = None
    try:
        reader = csv.DictReader(f)
    except Exception as exc:
        #log.error(f"Error reading CSV file: {exc}")
        return None, exc
    return {"hosts":list(reader)}, exc

def yaml_load(f):
    data = None
    exc = None
    try:
        data = yaml.unsafe_load(f)
    except Exception as exc:
        pass
        #log.error(f"Error reading YAML file: {exc}")
        #raise
    return data, exc

# load a config file - either CSV or YAML
def load_config(inputfile):
    data = None
    try:
        f = open(inputfile)
    except Exception as exc:
        raise
    data, exc = yaml_load(f)
    if type(data) is not dict:   # yaml_load returns a dict; if not a dict, it's an error reading file
        f.seek(0)   # rewind the file
        data, exc = csv_load(f)     # try CSV
    if type(data) is not dict:
        log.error(f"Error reading config file: {exc}")
        return None
    return data

def generate_config(bmc_ips, bmc_username, bmc_password):
    conf = dict()
    conf['hosts'] = list()
    for ip in bmc_ips:
        conf['hosts'].append({'name': ip, 'user': bmc_username[0], 'password': bmc_password[0]})
    return conf

def save_bmc_db(redfish_list, defaults_database, force=False):
    bmc_db = None
    changes_made = False
    try:
        bmc_db = load_config(defaults_database)
    except FileNotFoundError: # it's ok if it doesn't exist - we'll create it
        log.info(f"Bios database {defaults_database} does not exist, creating")
        pass
    except Exception as exc:
        log.error(f"Database file {defaults_database} file: {exc}")
        return False

    if bmc_db is None:
        bmc_db = dict()

    # build the in-memory db
    for server in redfish_list:
        manufacturer = server.manufacturer
        model = server.model
        architecture = server.arch
        if manufacturer not in bmc_db:
            bmc_db[manufacturer] = dict()
        if architecture not in bmc_db[manufacturer]:
            bmc_db[manufacturer][architecture] = dict()

        # always overwrite any old settings?
        if model in bmc_db[manufacturer][architecture]:
            if force:
                log.warning(f"{manufacturer}/{architecture}/{model} found in database, forcing overwrite")
                bmc_db[manufacturer][architecture][model] = server.bios_settings
                changes_made = True
            else:
                log.info(f"{manufacturer}/{architecture}/{model} found in database; to force overwrite use --force")
        else:
            bmc_db[manufacturer][architecture][model] = server.bios_settings
            changes_made = True

    if changes_made:
        with open(defaults_database, 'w') as f:
            f.write('# Bios Defaults Database\n')
            f.write('# This should contain the default/factory reset values\n')
            yaml.dump(bmc_db, f, default_flow_style=False)

# Generate the bios defs for a server model so we can later set the values on new servers
def diff_defaults(defaults_database, redfish_list):
    bmc_db = None
    custom_settings = dict()
    try:
        bmc_db = load_config(defaults_database)
    except FileNotFoundError: # it's ok if it doesn't exist - we'll create it
        log.info(f"Bios database {defaults_database} does not exist, creating")
    except Exception as exc:
        log.error(f"Database file {defaults_database} file: {exc}")
        return False

    if bmc_db is None:
        bmc_db = dict()

    for server in redfish_list:
        manufacturer = server.bmc.manufacturer
        model = server.bmc.model
        arch = server.bmc.arch
        bios_settings = server.bmc.bios_data.dict['Attributes']  # bios settings on the target server

        if manufacturer not in bmc_db:
            log.error(f"There are no default settings for {manufacturer}")
            return False
        if arch not in bmc_db[manufacturer]:
            log.error(f"There are no default settings for {manufacturer}/{arch}")
            return False
        if model not in bmc_db[manufacturer][arch]:
            log.error(f"There are no default settings for {manufacturer}/{arch}/{model}")
            return False

        defaults = bmc_db[manufacturer][arch][model]

        # make a list of setting that differ on this server compared to factory defaults
        log.info(f"Looking at defaults for {server.hostname}: {manufacturer}/{arch}/{model}:")
        bios_differences = dict()
        missing_settings = 0
        for setting in defaults:
            if setting not in bios_settings:   # does this default setting exist in the server?
                log.warning(f"{server.hostname} is missing setting for {manufacturer}/{arch}/{model}/{setting} - ???")
                missing_settings += 1
            else:
                if bios_settings[setting] != defaults[setting]:
                    log.info(f'Setting: {setting} differs from default: {bios_settings[setting]}')
                    bios_differences[setting] = bios_settings[setting]

        if len(bios_differences) == 0 and missing_settings == 0:
            log.info(f"Server {server.bmc.name} has all default settings")
            continue
        elif len(bios_differences) == 0:
            log.error(f"Server {server.bmc.name}'s default definition is incorrect or incomplete, and shows no bios_differences")
            continue

        if manufacturer not in custom_settings:
            custom_settings[manufacturer] = dict()
        if arch not in custom_settings[manufacturer]:
            custom_settings[manufacturer][arch] = dict()
        custom_settings[manufacturer][arch][model] = bios_differences

    if len(custom_settings) == 0:
        log.info("None of the servers have non-default settings")
    else:
        print()
        print(f"Bios Differences (Edit these before adding to the bios_settings file):")
        print(yaml.dump(custom_settings))
    return True


def bios_diff(hostlist):
    hosta = hostlist[0]
    hostb = hostlist[1]

    if hosta.arch != hostb.arch:
        print()
        print(f"ERROR: Hosts are of different architectures! {hosta.arch} vs {hostb.arch}")
        sys.exit(1)
    if hosta.manufacturer != hostb.manufacturer:
        print()
        print(f"ERROR: Hosts are of different manufacturer! {hosta.manufacturer} vs {hostb.manufacturer}")
        sys.exit(1)
    if hosta.bmc.bios_version != hostb.bmc.bios_version:
        print()
        print(f"WARNING: Hosts have different BIOS versions! {hosta.bmc.bios_version} vs {hostb.bmc.bios_version}")
        # note:  Supermicro has a different BIOS keys in every bios version (all end in _XXXX, where XXXX is hex)
        # the XXXX is different in different versions.  This means that the BIOS settings are not comparable
        # between different versions of the BIOS.
        # Perhaps we should trim the keys to remove the _XXXX part so we can compare different BIOS versions?
        # This could be implemented by copying the hosta_bios and hostb_bios dictionaries and removing the _XXXX
        # from the keys.  Then we could compare the two dictionaries.

    hosta_bios = hostlist[0].bios_settings
    hostb_bios = hostlist[1].bios_settings

    diff = list()                  #  Entries are [setting, value_a, value_b]
    settings_not_present = list()  #  Entries are [setting, value_a, value_b]
    for setting, value in hosta_bios.items():
        if setting not in hostb_bios:
            settings_not_present.append([setting, value, "setting not present"])
        elif hostb_bios[setting] != value:
            diff.append([setting, value, hostb_bios[setting]])

    # check for settings in b that are not in a
    for setting, value in hostb_bios.items():
        if setting not in hosta_bios:
            settings_not_present.append([setting, "setting not present", value])

    are_different = False
    if len(diff) > 0:
        print()
        print("Settings that are different between the servers:")
        print(tabulate(diff, headers=["Setting", hosta.hostname, hostb.hostname]))
        are_different = True

    if len(settings_not_present) > 0:
        print()
        print("Settings that are in one server and not the other:")
        print(tabulate(settings_not_present, headers=["Setting", hosta.hostname, hostb.hostname]))
        are_different = True

    return are_different

# detail the differences between 2 dicts (keys in one and not in the other, and different values for the same key
def diff_dicts(dict1, dict2):
    diff = list()
    keys_not_present_in1 = list()
    keys_not_present_in2 = list()
    for key, value in dict1.items():
        if key not in dict2:
            keys_not_present_in2.append([key, value, "key not present"])
        elif dict2[key] != value:
            diff.append([key, value, dict2[key]])

    # check for key in b that are not in a
    for key, value in dict2.items():
        if key not in dict1:
            keys_not_present_in1.append([key, "key not present", value])

    return (diff, keys_not_present_in1, keys_not_present_in2)


from concurrent.futures import ThreadPoolExecutor


def parallel_open_sessions(hostlist):
    opened_list = list()
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(Server.connect, host) for host in hostlist]
        for future in futures:
            result = future.result()
            if result is not None:
                opened_list.append(result)


    return opened_list



def close_sessions(hostlist):
    for host in hostlist:
        host.close()

def ends_with_hex(s):
    """Check if string ends with _ and 4 hex digits"""
    if len(s) < 5:  # Need at least 5 chars: _XXXX
        return False
    if s[-5] != '_':  # Must have underscore
        return False
    try:
        # Try to convert last 4 chars to hex
        int(s[-4:], 16)
        return True
    except ValueError:
        return False

def trim_trailing_hex(s):
    """Trim trailing hex digits from string, return the string without trailing hex digits"""
    if not ends_with_hex(s):
        return s
    else:
        return s[:-5]

# for the given server (bmc), try to find the settings in all_bios_settings, verify that the keys match, then return it
# match the keys using fuzzy logic, and return the actual keys (prevents failures).
# If there is no match for the server model, try finding one that matches closely?
from rapidfuzz import process, fuzz
def find_bios_settings(server, all_bios_settings, force=False):
    wild = False
    if server.manufacturer in all_bios_settings:
        mfg = all_bios_settings[server.manufacturer]
    else:
        log.error(f"Server {server.hostname}: Unknown manufacturer: {server.manufacturer}.  Aborting.")
        return None
    if server.arch in mfg:
        arch = mfg[server.arch]
    else:
        log.error(f"Server {server.hostname}: Unknown processor architecture: {server.architecture}.  Aborting.")
        return None
    if server.model in arch:
        base_settings = arch[server.model] # exact match
    elif '*' in arch:
        base_settings = arch['*']  # wildcard entry - give it a try
        wild = True

    derived_keys = dict()
    preprocessor = trim_trailing_hex if server.manufacturer == "Supermicro" else None

    log.debug(f"{server.manufacturer} using {preprocessor}")
    # server_full_bios are what is set on the server now - all bios settings
    server_full_bios = server.bios_settings.keys()
    # base settings are a subset of settings from the bios_settings.yml file - what we want the settings to be
    for setting in base_settings.keys():
        # check to see if the settings we want to make are actual settings in the BIOS of this server
        keyword = process.extract(setting, server_full_bios, processor=preprocessor, scorer=fuzz.ratio, limit=1)
        if len(keyword) == 0:
            log.error(f"Server {server.hostname}: Unknown setting: {setting}. Aborting.")
            return None

        keyword, similarity, _ = keyword[0]
        # is it an exact match?
        if similarity != 100.0:
            #log.warning(
            #   f"BIOS Keys for {server.hostname}/{server.manufacturer}/{server.model} do not match the definition")
            if not wild:
                log.warning(f"BIOS Keys are different than previously recorded - {setting}")
            else:
                log.warning(f"Trying to match BIOS Keys from wildcard definition")
            if similarity > 75:
                log.info(f"Possible match found: {server.hostname}/{server.manufacturer}/{server.model}/{setting} is {keyword}, similarity {similarity}")
                if force:
                    log.info(f"Forcing setting: {setting}.")
                    derived_keys[setting] = (keyword, similarity)
            else:
                log.warning( f"Match NOT found? {server.hostname}/{server.manufacturer}/{server.model}/{setting} is {keyword}, similarity {similarity}. Skipping setting")
        else:
            derived_keys[setting] = (keyword, similarity)

    # at this point, we should analyze the results - normally they should all be 100.0% similarity,
    # unless this server is running a different BIOS version, but they should be very similar...
    # unless a wildcard was used - then all bets are off
    this_servers_settings = dict()
    for setting, target_tuple in derived_keys.items():
        this_servers_settings[target_tuple[0]] = base_settings[setting]   # sets the value

    #if wild:
    #    print(f"We used a wildcard for {server.hostname}: '{server.model}'.")

    if len(base_settings.keys()) != len(derived_keys.keys()):
        log.warning(f"{server.hostname}'s settings do not match defined settings for {server.manufacturer}/{server.model}.")
        log.warning(f"This server's settings should be manually reviewed")

    return this_servers_settings



def main():
    # parse arguments
    progname = sys.argv[0]
    parser = argparse.ArgumentParser(description="View/Change BIOS Settings on servers")

    parser.add_argument("-c", "--hostconfigfile", type=str, nargs="?", default="host_config.csv",
                        help = "filename of host config file. Default is host_config.csv")
    parser.add_argument("-b", "--bios", type=str, nargs="?", default="bios_settings.yml",
                        help="bios configuration filename. Default is bios_settings.yml")
    parser.add_argument("--bmc-config", dest="bmc_config", default=False, action="store_true",
                        help="Configure the BMCs to allow RedFish access")
    parser.add_argument("--fix", dest="fix", default=False, action="store_true",
                        help="Correct any bios settings that do not match the definition")
    parser.add_argument("--reboot", dest="reboot", default=False, action="store_true",
                        help="Reboot server if changes have been made")
    parser.add_argument("--dump", dest="dump", default=False, action="store_true",
                        help="Print out current BIOS settings only")
    parser.add_argument("--save-defaults", dest="save", default=False, action="store_true",
                        help="Save default BIOS settings to defaults-database - should be factory reset values")
    parser.add_argument("--defaults-database", dest="defaults_database", default="defaults-db.yml",
                        help="Filename of the factory defaults-database.  Default is defaults-db.yml")
    parser.add_argument("-f", "--force", dest="force", default=False, action="store_true",
                        help="Force overwriting existing BIOS settings and such")
    parser.add_argument("--reset-bios", dest="reset_bios", default=False, action="store_true",
                        help="Reset BIOS to default settings.  To also reboot, add the --reboot option")
    parser.add_argument("--diff", dest="diff", nargs=2, default=False, help="Compare 2 hosts BIOS settings")
    parser.add_argument("--diff-defaults", dest="diff_defaults", default=False, action="store_true",
                        help="Compare hosts BIOS settings to factory defaults")
    parser.add_argument("--version", dest="version", default=False, action="store_true",
                        help="Display version number")
    parser.add_argument("--bmc-ips", dest="bmc_ips", type=str, nargs="*",
                        help="a list of hosts to configure instead of using the host_config.csv", default=None)
    parser.add_argument("--bmc-username", dest="bmc_username", type=str, nargs=1,
                        help="a username to use on all hosts in --bmc_ips", default=None)
    parser.add_argument("--bmc-password", dest="bmc_password", type=str, nargs=1,
                        help="a password to use on all hosts in --bmc_ips", default=None)
    parser.add_argument("-v", "--verbose", dest='verbosity', action='store_true', help="enable verbose mode")

    args = parser.parse_args()

    if args.version:
        print(f"{progname} version 2025.11.11")
        sys.exit(0)

    # local modules - override a module's logging level
    register_module("RedFishBMC", logging.INFO)
    register_module("BMCsetup", logging.INFO)
    register_module("redfish.rest.v1", logging.ERROR)
    register_module("paramiko", logging.ERROR)

    # set up logging in a standard way...
    configure_logging(log, args.verbosity)
    #log_to_file("paramiko.log", logging.DEBUG)

    # if they provided a list of BMC IPs, they must also provide a username and password
    if args.bmc_ips is not None:
        if args.bmc_username is None or args.bmc_password is None:
            log.error("You must provide a username and password when using --bmc-ips")
            sys.exit(1)
        log.info(f"Using BMC IPs - ignoring {args.hostconfigfile}")
        conf = generate_config(args.bmc_ips, args.bmc_username, args.bmc_password)
    else:
        # else try to load the configfile
        try:
            conf = load_config(args.hostconfigfile)
        except Exception as exc:
            log.error(f"Unable to open host configuration file: {exc}")
            sys.exit(1)

    # create objects from the config in the input file or command-line
    servers_list = list()
    for host in conf['hosts']:   # host is a dict, {name, user, password}
        servers_list.append(Server(host['name'], host['user'], host['password']))

    # did the user ask us to make sure the BMC is set with ipmi over lan and redfish, etc?
    if args.bmc_config:
        log.info("Configuring BMCs")
        for host in servers_list:
            log.info(f"Configuring {host['name']}")
            bmc_setup(host.hostname, host.username, host.password)
        log.info("BMCs have been configured")
        sys.exit(0)

    # try to load the BIOS settings (the entire database) (the entire database, all server types/models)
    try:
        all_bios_settings = load_config(args.bios)
    except Exception as exc:
        log.error(f"Unable to parse bios settings configuration file: {exc}")
        sys.exit(1)

    # if they asked for a diff of two servers, make sure they're in the config file...
    if args.diff:
        hostlist = list()
        for c_host in args.diff:
            try:
                hostlist.append([x for x in servers_list if x.hostname == c_host][0])
            except:
                log.error(f"host {c_host} not in {args.hostconfigfile}")
                sys.exit(1)
    else:
        # all hosts
        hostlist = servers_list

    if args.reboot:
        this_hosts_ip = get_ipmi_ip()

        # if we're running on one of the servers we're looking at, most this server to the end of the list
        # so that it would be rebooted last.
        if this_hosts_ip is not None:
            log.info(f"This host's IPMI IP is: {this_hosts_ip}")

            my_entry = None
            for host in hostlist:
                if host.hostname == this_hosts_ip:
                    my_entry = host
                    break
            if my_entry is not None:
                hostlist.remove(my_entry)
                hostlist.append(my_entry)

    # open connections to all the hosts - redfish_list is a list of RedFishBMC objects
    log.info("Opening sessions to hosts:")
    redfish_list = parallel_open_sessions(hostlist)

    if args.diff:
        if len(redfish_list) != 2:
            log.error(f"you must specify exactly 2 hosts to diff them")
        elif not bios_diff(redfish_list):
            log.info("The servers have identical BIOS settings")
    elif args.diff_defaults:
        diff_defaults(args.defaults_database, redfish_list)
        pass
    elif args.reset_bios:
        for server in redfish_list:
            # rest the bios...
            server.bmc.reset_settings_to_default()
            log.info(f"{server.bmc.name} has been reset to factory defaults")
            if args.reboot:
                server.bmc.reboot()
                log.info(f"{server.bmc.name} has been rebooted")
    elif args.save:
        save_bmc_db(redfish_list, args.defaults_database, force=args.force)
    else:
        # check BIOS settings
        hosts_needing_changes = list()
        fixed_hosts = list()
        systems_rebooted = list()
        # Loop through the servers
        for server in redfish_list:
            if args.dump:
                server.bmc.print_settings()
                continue
            else:
                settings = find_bios_settings(server, all_bios_settings)
                # Vince left off here
                #count = bmc.check_settings(desired_bios_settings[bmc.manufacturer][bmc.arch][bmc.model])
                count = server.bmc.check_settings(settings)
            #log.info(f"")
            if count > 0:
                log.info(f"{count} changes are needed on {server.hostname}")
                hosts_needing_changes.append(server)
                if args.fix:
                    if server.bmc.change_settings(settings):
                        fixed_hosts.append(server)
                    else:
                        log.error(f"Unable to fix {server.hostname}")
            else:
                log.warning(f"No changes are needed on {server.hostname}")
            log.info("")
            # if they said reboot, reboot
            if args.reboot:
                if args.fix and server in fixed_hosts: # --fix --reboot implies rebooting only the hosts that were fixed
                    log.info(f"Rebooting {server.hostname}")
                    server.bmc.reboot()
                    systems_rebooted.append(server)
                elif not args.fix:  # they asked to reboot all hosts
                    log.info(f"Rebooting {server.hostname}")
                    server.bmc.reboot()
                    systems_rebooted.append(server)

        if not args.fix:
            log.info(f"There are {len(hosts_needing_changes)} hosts needing changes")
        else:
            if not args.reboot:
                log.info(f"{len(fixed_hosts)} have been modified.  Please reboot them to activate changes.")
            else:
                log.info(f"{len(systems_rebooted)} have been successfully modified and rebooted.")

    close_sessions(redfish_list)


if __name__ == '__main__':
    main()
