import argparse
import difflib
import getpass
import os
import re
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
    def __init__(self, hostname, username, password, ca_file=None):
        self.ca_file = ca_file
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
            self.bmc = RedFishBMC(self.hostname, username=self.username, password=self.password, ca_file=self.ca_file)
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
            self.bmc.close()


class ConfigError(Exception):
    pass


class UniqueKeyLoader(yaml.SafeLoader):
    """A safe YAML loader that refuses a key given twice in one mapping, where PyYAML keeps the last silently."""

    def construct_mapping(self, node, deep=False):
        seen = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in seen:
                raise yaml.constructor.ConstructorError(None, None, f"found the key {key!r} twice", key_node.start_mark)
            seen.add(key)
        return super().construct_mapping(node, deep)


def load_yaml(path):
    """The mapping in the YAML file at path. A missing file raises FileNotFoundError; anything else wrong with it
    raises ConfigError."""
    with open(path, encoding="utf-8-sig") as f:
        try:
            data = yaml.load(f, Loader=UniqueKeyLoader)
        except yaml.YAMLError as exc:
            raise ConfigError(f"{path} is not valid YAML: {exc}")
    if not isinstance(data, dict):
        raise ConfigError(f"{path} should hold a YAML mapping")
    return data


def load_bios_settings(path):
    """The BIOS settings file: manufacturer, then CPU architecture, then model (or '*'), then setting: value."""
    data = load_yaml(path)
    for manufacturer, archs in data.items():
        if not isinstance(archs, dict):
            raise ConfigError(f"{path}: {manufacturer} should hold CPU architectures (AMD, Intel, ARM)")
        for arch, models in archs.items():
            if not isinstance(models, dict):
                raise ConfigError(f"{path}: {manufacturer}/{arch} should hold models, or '*'")
            for model, settings in models.items():
                if not isinstance(settings, dict):
                    raise ConfigError(f"{path}: {manufacturer}/{arch}/{model} should be a model holding settings")
                for setting, value in settings.items():
                    if isinstance(value, (dict, list)) or value is None:
                        raise ConfigError(f"{path}: {manufacturer}/{arch}/{model}/{setting} should have one value")
    return data


def load_hosts(path):
    """The BMCs listed in path, as dicts of name, user and password. The file is YAML (a 'hosts' list) or CSV with a
    name,user,password header, whatever its name says."""
    with open(path, encoding="utf-8-sig") as f:
        text = f.read()
    try:
        data = yaml.load(text, Loader=UniqueKeyLoader)
        yaml_error = None
    except yaml.YAMLError as exc:
        data, yaml_error = None, exc
    if isinstance(data, dict):
        hosts = data.get("hosts")
        if not isinstance(hosts, list):
            raise ConfigError(f"{path} should hold a 'hosts' list")
    else:
        import csv
        import io
        reader = csv.DictReader(io.StringIO(text), skipinitialspace=True)
        if not {"name", "user", "password"} <= {field.strip() for field in reader.fieldnames or []}:
            hint = f" (as YAML: {yaml_error})" if yaml_error else ""
            raise ConfigError(f"{path} is neither YAML with a 'hosts' list nor CSV starting with a "
                              f"name,user,password line{hint}")
        hosts = [{key.strip(): (value or "").strip() for key, value in row.items() if key} for row in reader]
    for number, host in enumerate(hosts, 1):
        if not isinstance(host, dict) or not all(host.get(key) for key in ("name", "user", "password")):
            raise ConfigError(f"{path}: host {number} needs a name, a user and a password")
    return hosts


def generate_config(bmc_ips, bmc_username, bmc_password):
    return [{'name': ip, 'user': bmc_username, 'password': bmc_password} for ip in bmc_ips]


PASSWORD_ENV = "BIOS_TOOL_BMC_PASSWORD"


def bmc_password(given):
    """The password for --bmc-ips: --bmc-password, else $BIOS_TOOL_BMC_PASSWORD, else asked for at a terminal."""
    if given is not None:
        return given[0]
    if os.environ.get(PASSWORD_ENV):
        return os.environ[PASSWORD_ENV]
    if sys.stdin.isatty():
        return getpass.getpass("BMC password: ")
    return None


# BIOS settings that identify one machine, or hold its passwords: never copied into the defaults database or the
# settings bios_tool suggests. Settings whose value is a MAC address, or whose name holds one (Lenovo names per-adapter
# settings after the adapter's MAC), are left out too.
IDENTIFYING_SETTINGS = {"SystemServiceTag", "SerialNumber", "AssetTag", "ServerAssetTag", "SetupPassword",
                        "SysPassword", "SHA256SetupPassword", "SHA256SetupPasswordSalt", "SHA256SystemPassword",
                        "SHA256SystemPasswordSalt", "NvmeofHostId", "NvmeofHostNqn", "NvmeofHostDellNqn",
                        "NvmeofHostCustomNqn"}
MAC_ADDRESS = re.compile(r"([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}")
MAC_IN_NAME = re.compile(r"(^|_)[0-9A-Fa-f]{12}(_|$)")


def shareable(settings):
    """settings without those that identify the machine they came from."""
    return {key: value for key, value in settings.items()
            if key not in IDENTIFYING_SETTINGS and not MAC_ADDRESS.search(str(value)) and not MAC_IN_NAME.search(key)}

def save_bmc_db(redfish_list, defaults_database, force=False):
    bmc_db = None
    changes_made = False
    try:
        bmc_db = load_yaml(defaults_database)
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
                bmc_db[manufacturer][architecture][model] = shareable(server.bios_settings)
                changes_made = True
            else:
                log.info(f"{manufacturer}/{architecture}/{model} found in database; to force overwrite use --force")
        else:
            bmc_db[manufacturer][architecture][model] = shareable(server.bios_settings)
            changes_made = True

    if changes_made:
        with open(defaults_database, 'w') as f:
            f.write('# Bios Defaults Database\n')
            f.write('# This should contain the default/factory reset values\n')
            yaml.dump(bmc_db, f, default_flow_style=False)

    return changes_made

# Generate the bios defs for a server model so we can later set the values on new servers
def diff_defaults(defaults_database, redfish_list):
    bmc_db = None
    custom_settings = dict()
    try:
        bmc_db = load_yaml(defaults_database)
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
        bios_settings = shareable(server.bmc.bios_data.dict['Attributes'])  # bios settings on the target server

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
    """True if the two servers' BIOS settings differ, False if not, None if they cannot be compared."""
    hosta = hostlist[0]
    hostb = hostlist[1]

    if hosta.arch != hostb.arch:
        print()
        print(f"ERROR: Hosts are of different architectures! {hosta.arch} vs {hostb.arch}")
        return None
    if hosta.manufacturer != hostb.manufacturer:
        print()
        print(f"ERROR: Hosts are of different manufacturer! {hosta.manufacturer} vs {hostb.manufacturer}")
        return None
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

def squash(name):
    return "".join(c for c in name.lower() if c.isalnum())


def match_setting(name, bios_keys):
    """The setting in bios_keys that name means, and None; or None and the settings it could equally mean. Only a
    certain match counts: the exact name; the same name without Supermicro's _XXXX suffix; or the same letters and
    digits, ignoring case and punctuation (Supermicro's SUM spells Hyper-Threading[ALL] what Redfish calls
    Hyper_Threading_ALL_). Each step is taken only if it finds exactly one setting."""
    if name in bios_keys:
        return name, []
    for same in (trim_trailing_hex, lambda key: squash(trim_trailing_hex(key))):
        candidates = [key for key in bios_keys if same(key) == same(name)]
        if len(candidates) == 1:
            return candidates[0], []
        if candidates:
            return None, candidates
    return None, []


def find_bios_settings(server, all_bios_settings):
    """The settings this server should have, under the names its BIOS uses, and the settings from the file that
    could not be matched to one; or None if the file has no entry for this kind of server."""
    platform = f"{server.manufacturer}/{server.arch}/{server.model}"
    if server.manufacturer not in all_bios_settings:
        log.error(f"{server.hostname} is a {platform}: there is no '{server.manufacturer}' manufacturer in the BIOS "
                  f"settings file. Add it, with this server's architecture and model.")
        return None
    mfg = all_bios_settings[server.manufacturer]
    if server.arch not in mfg:
        log.error(f"{server.hostname} is a {platform}: there is no '{server.arch}' architecture under "
                  f"'{server.manufacturer}' in the BIOS settings file. Add it, with this server's model.")
        return None
    arch = mfg[server.arch]
    if server.model not in arch and '*' not in arch:
        log.error(f"{server.hostname} is a {platform}: there is no '{server.model}' model, and no '*', under "
                  f"'{server.manufacturer}/{server.arch}' in the BIOS settings file. Add this server's model.")
        return None
    # the '*' entry holds what every model of this manufacturer and architecture needs; the model's entry overrides it
    wild = server.model not in arch
    base_settings = dict(arch.get('*') or {})
    base_settings.update(arch.get(server.model) or {})

    bios_keys = list(server.bios_settings.keys())
    this_servers_settings = dict()
    unmatched = list()
    for setting, value in base_settings.items():
        key, candidates = match_setting(setting, bios_keys)
        if key is None:
            if candidates:
                reason = f"it could be any of {', '.join(candidates)}"
            else:
                close = difflib.get_close_matches(setting, bios_keys, n=3, cutoff=0.6)
                reason = f"the closest are {', '.join(close)}" if close else "no setting is close"
            log.error(f"{server.hostname}: {setting} is not in this server's BIOS, so it is neither checked nor "
                      f"changed ({reason})")
            unmatched.append(setting)
            continue
        if key != setting:
            log.debug(f"{server.hostname}: {setting} is called {key} on this server")
        this_servers_settings[key] = value
    return this_servers_settings, unmatched



def reset_bios(args, redfish_list):
    """Resets the BIOS of every server to factory defaults, and reboots them with --reboot, after asking."""
    then = " and reboot them" if args.reboot else ""
    answer = confirm(f"Reset the BIOS of {len(redfish_list)} servers to factory defaults{then}: "
                     f"{', '.join(server.hostname for server in redfish_list)}?", args.yes)
    failed = answer is None
    for server in redfish_list if answer else []:
        if not server.bmc.reset_settings_to_default():
            failed = True
            continue
        log.info(f"{server.hostname}'s BIOS will be reset to factory defaults at its next reboot")
        if args.reboot:
            if server.bmc.reboot():
                log.info(f"{server.hostname} has been rebooted")
            else:
                log.error(f"Unable to reboot {server.hostname}")
                failed = True
    return 1 if failed else 0


def check_and_fix(args, redfish_list, all_bios_settings):
    """Checks every server's BIOS against the settings file, and with --fix and --reboot changes and reboots them."""
    # check BIOS settings
    hosts_needing_changes = list()
    failed = False
    fixed_hosts = list()
    systems_rebooted = list()
    # every host's settings are found before any host is changed, so an unknown server stops the run cleanly
    wanted = dict()
    unknown = list()
    unmatched = 0
    if not args.dump:
        for server in redfish_list:
            found = find_bios_settings(server, all_bios_settings)
            if found is None:
                unknown.append(server)
            else:
                wanted[server], missing = found
                unmatched += len(missing)
    if unknown and (args.fix or args.reboot):
        log.error(f"No server was changed: {len(unknown)} of them are not in {args.bios}.")
        return 1
    # Loop through the servers
    for server in redfish_list:
        if args.dump:
            server.bmc.print_settings()
            continue
        elif server in unknown:
            continue
        settings = wanted[server]
        log.info(f"Looking at {server.hostname}: {server.bmc.manufacturer}/{server.bmc.arch}/{server.bmc.model}:")
        # one BMC failing is reported, and the others are still checked and fixed
        try:
            changes, waiting = server.bmc.check_settings(settings)
            if changes:
                log.info(f"{len(changes)} changes are needed on {server.hostname}")
                hosts_needing_changes.append(server)
                if args.fix:
                    if server.bmc.change_settings(changes):
                        fixed_hosts.append(server)
                    else:
                        log.error(f"Unable to fix {server.hostname}")
                        failed = True
            elif waiting:
                log.info(f"{len(waiting)} changes on {server.hostname} are staged and wait for a reboot")
            else:
                log.info(f"No changes are needed on {server.hostname}")
        except Exception as exc:
            log.error(f"{server.hostname} failed: {exc}")
            failed = True
        log.info("")

    if args.reboot and not args.dump:
        # only servers with BIOS changes waiting: those fixed now, and those fixed earlier without --reboot
        to_reboot = [server for server in redfish_list if server not in unknown and
                     (server in fixed_hosts or server.bmc.pending_changes())]
        if not to_reboot:
            log.info("No server has BIOS changes waiting for a reboot")
        else:
            answer = confirm(f"Reboot {len(to_reboot)} servers to apply their BIOS changes: "
                             f"{', '.join(server.hostname for server in to_reboot)}?", args.yes)
            failed = failed or answer is None
            for server in to_reboot if answer else []:
                log.info(f"Rebooting {server.hostname}")
                if server.bmc.reboot():
                    systems_rebooted.append(server)
                else:
                    log.error(f"Unable to reboot {server.hostname}")
                    failed = True

    if not args.fix:
        log.info(f"There are {len(hosts_needing_changes)} hosts needing changes")
    else:
        if not args.reboot:
            log.info(f"{len(fixed_hosts)} have been modified.  Please reboot them to activate changes.")
        else:
            log.info(f"{len(systems_rebooted)} have been successfully modified and rebooted.")
    if unmatched:
        log.error(f"{unmatched} settings from {args.bios} are not in their server's BIOS and were not checked.")
    if unknown:
        log.error(f"{len(unknown)} servers are not in {args.bios} and were not checked.")
    return 1 if failed or unmatched or unknown else 0


def confirm(question, assume_yes):
    """True or False for the answer to a yes/no question, or None if it could not be asked."""
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        log.error(f"{question} Not asked, as there is no terminal to answer on: run with --yes to answer yes.")
        return None
    return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")


def main():
    # parse arguments
    progname = sys.argv[0]
    parser = argparse.ArgumentParser(description="View/Change BIOS Settings on servers")

    parser.add_argument("-c", "--hostconfigfile", type=str, default="host_config.csv",
                        help = "filename of host config file. Default is host_config.csv")
    parser.add_argument("-b", "--bios", type=str, default="bios_settings.yml",
                        help="bios configuration filename. Default is bios_settings.yml")
    parser.add_argument("--bmc-config", dest="bmc_config", default=False, action="store_true",
                        help="Configure the BMCs to allow RedFish access")
    parser.add_argument("--fix", dest="fix", default=False, action="store_true",
                        help="Correct any bios settings that do not match the definition")
    parser.add_argument("--reboot", dest="reboot", default=False, action="store_true",
                        help="Reboot the servers with BIOS changes waiting to be applied (those --fix changed now or "
                             "earlier), after asking")
    parser.add_argument("-y", "--yes", dest="yes", default=False, action="store_true",
                        help="Answer yes to the question before rebooting or resetting, so it can run without a terminal")
    parser.add_argument("--dump", dest="dump", default=False, action="store_true",
                        help="Print out current BIOS settings only")
    parser.add_argument("--save-defaults", dest="save", default=False, action="store_true",
                        help="Save default BIOS settings to defaults-database - should be factory reset values")
    parser.add_argument("--defaults-database", dest="defaults_database", default="defaults-db.yml",
                        help="Filename of the factory defaults-database.  Default is defaults-db.yml")
    parser.add_argument("-f", "--force", dest="force", default=False, action="store_true",
                        help="With --save-defaults, overwrite a model already in the defaults database")
    parser.add_argument("--reset-bios", dest="reset_bios", default=False, action="store_true",
                        help="Reset the BIOS to factory defaults, after asking. To also reboot, add the --reboot option")
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
                        help="a password to use on all hosts in --bmc-ips; visible to other users in ps and in "
                             "shell history, so prefer $BIOS_TOOL_BMC_PASSWORD or the prompt", default=None)
    parser.add_argument("--ca-file", dest="ca_file", default=None,
                        help="check each BMC's TLS certificate against the CA certificates in this file; by default "
                             "certificates are not checked, as most BMCs' are self-signed")
    parser.add_argument("-v", "--verbose", dest='verbosity', action='store_true', help="enable verbose mode")

    args = parser.parse_args()

    if args.version:
        print(f"{progname} version 2026.01.06")
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
        password = bmc_password(args.bmc_password)
        if args.bmc_username is None or not password:
            log.error(f"--bmc-ips needs --bmc-username, and a password: ${PASSWORD_ENV}, or typed when asked")
            sys.exit(1)
        log.info(f"Using BMC IPs - ignoring {args.hostconfigfile}")
        hosts = generate_config(args.bmc_ips, args.bmc_username[0], password)
    else:
        try:
            hosts = load_hosts(args.hostconfigfile)
        except (OSError, ConfigError) as exc:
            log.error(f"Unable to read the host configuration file: {exc}")
            sys.exit(1)

    # create objects from the config in the input file or command-line
    servers_list = list()
    for host in hosts:   # host is a dict, {name, user, password}
        servers_list.append(Server(host['name'], host['user'], host['password'], ca_file=args.ca_file))
    if args.ca_file is None:
        log.info("BMC certificates are not checked; give --ca-file to check them")

    # did the user ask us to make sure the BMC is set with ipmi over lan and redfish, etc?
    if args.bmc_config:
        log.info("Configuring BMCs")
        failed = list()
        for host in servers_list:
            log.info(f"Configuring {host.hostname}")
            try:
                configured = bmc_setup(host.hostname, host.username, host.password)
            except Exception as exc:
                log.error(f"Unable to configure {host.hostname}: {exc}")
                configured = False
            if not configured:
                failed.append(host.hostname)
        if failed:
            log.error(f"{len(failed)} of {len(servers_list)} BMCs could not be configured: {', '.join(failed)}")
            sys.exit(1)
        log.info("BMCs have been configured")
        sys.exit(0)

    # the BIOS settings are read before any BMC is contacted, so a broken file changes nothing
    all_bios_settings = None
    if not (args.dump or args.diff or args.diff_defaults or args.reset_bios or args.save):
        try:
            all_bios_settings = load_bios_settings(args.bios)
        except (OSError, ConfigError) as exc:
            log.error(f"Unable to read the BIOS settings file: {exc}")
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

    unreachable = [host.hostname for host in hostlist if host not in redfish_list]

    try:
        if args.diff:
            if len(redfish_list) != 2:
                log.error(f"you must specify exactly 2 hosts to diff them")
                status = 1
            else:
                different = bios_diff(redfish_list)
                if different is False:
                    log.info("The servers have identical BIOS settings")
                status = 1 if different is None else 0
        elif args.diff_defaults:
            status = 0 if diff_defaults(args.defaults_database, redfish_list) else 1
        elif args.reset_bios:
            status = reset_bios(args, redfish_list)
        elif args.save:
            save_bmc_db(redfish_list, args.defaults_database, force=args.force)
            status = 0
        else:
            status = check_and_fix(args, redfish_list, all_bios_settings)
    finally:
        close_sessions(redfish_list)

    if unreachable:
        log.error(f"{len(unreachable)} of {len(hostlist)} servers could not be reached, so nothing was done to them: "
                  f"{', '.join(unreachable)}")
        status = 1
    sys.exit(status)


if __name__ == '__main__':
    main()
