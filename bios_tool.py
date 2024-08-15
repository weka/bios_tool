import argparse
import logging
import sys
import traceback

import redfish
import yaml

from wekapyutils.wekalogging import configure_logging, register_module
from RedFishBMC import RedFishBMC, trim_supermicro_dict
from BMCsetup import bmc_setup
from tabulate import tabulate

# from paramiko.util import log_to_file

# get root logger
log = logging.getLogger()

def csv_load(f):
    """
    Load a CSV file into a list of dictionaries
    :param f: file object
    :return: list of dictionaries
    """
    import csv
    reader = csv.DictReader(f)
    #reader_list = list(reader)
    #for row in reader:
    #    print(row)
    return {"hosts":list(reader)}


def _load_config(inputfile):
    try:
        f = open(inputfile)
    except Exception as exc:
        raise
    with f:
        try:
            if inputfile.endswith(".csv"):
                return csv_load(f)
            return yaml.load(f, Loader=yaml.FullLoader)
        except AttributeError:
            return yaml.load(f)
        except Exception as exc:
            log.error(f"Error reading config file: {exc}")
            raise

def _generate_config(bmc_ips, bmc_username, bmc_password):
    conf = dict()
    conf['hosts'] = list()
    for ip in bmc_ips:
        conf['hosts'].append({'name': ip, 'user': bmc_username[0], 'password': bmc_password[0]})
    return conf


def bios_diff(hostlist):
    hosta = hostlist[0]
    hostb = hostlist[1]

    if hosta.arch != hostb.arch:
        print()
        print(f"ERROR: Hosts are of different architectures! {hosta.arch} vs {hostb.arch}")
        sys.exit(1)
    if hosta.vendor != hostb.vendor:
        print()
        print(f"ERROR: Hosts are of different vendors! {hosta.vendor} vs {hostb.vendor}")
        sys.exit(1)
    if hosta.bios_version != hostb.bios_version:
        print()
        print(f"WARNING: Hosts have different BIOS versions! {hosta.bios_version} vs {hostb.bios_version}")
        # note:  Supermicro has a different BIOS keys in every bios version (all end in _XXXX, where XXXX is hex)
        # the XXXX is different in different versions.  This means that the BIOS settings are not comparable
        # between different versions of the BIOS.
        # Perhaps we should trim the keys to remove the _XXXX part so we can compare different BIOS versions?
        # This could be implemented by copying the hosta_bios and hostb_bios dictionaries and removing the _XXXX
        # from the keys.  Then we could compare the two dictionaries.

    if hosta.vendor == "Supermicro":
        hosta_bios = trim_supermicro_dict(hostlist[0].bios_data.dict['Attributes'])
        hostb_bios = trim_supermicro_dict(hostlist[1].bios_data.dict['Attributes'])
    else:
        hosta_bios = hostlist[0].bios_data.dict['Attributes']
        hostb_bios = hostlist[1].bios_data.dict['Attributes']

    diff = list()
    settings_not_present = list()
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
        print(tabulate(diff, headers=["Setting", hosta.name, hostb.name]))
        are_different = True

    if len(settings_not_present) > 0:
        print()
        print("Settings that are in one server and not the other:")
        print(tabulate(settings_not_present, headers=["Setting", hosta.name, hostb.name]))
        are_different = True

    return are_different


def main():
    # parse arguments
    progname = sys.argv[0]
    parser = argparse.ArgumentParser(description="View/Change BIOS Settings on servers")

    # parser.add_argument("host", type=str, nargs="?", help="a host to talk to", default="localhost")
    parser.add_argument("-c", "--hostconfigfile", type=str, nargs="?", help="filename of host config file",
                        default="host_config.csv")
    parser.add_argument("-b", "--bios", type=str, nargs="?", help="bios configuration filename",
                        default="bios_settings.yml")
    parser.add_argument("--bmc_config", dest="bmc_config", default=False, action="store_true",
                        help="Configure the BMCs to allow RedFish access")
    parser.add_argument("--fix", dest="fix", default=False, action="store_true",
                        help="Correct any bios settings that do not match the definition")
    parser.add_argument("--reboot", dest="reboot", default=False, action="store_true",
                        help="Reboot server if changes have been made")
    parser.add_argument("--dump", dest="dump", default=False, action="store_true",
                        help="Print out BIOS settings only")
    parser.add_argument("--reset_bios", dest="reset_bios", default=False, action="store_true",
                        help="Reset BIOS to default settings.  To also reboot, add the --reboot option")
    parser.add_argument("--diff", dest="diff", nargs=2, default=False, help="Compare 2 hosts BIOS settings")
    # parser.add_argument("--version", dest="version", default=False, action="store_true",
    #                    help="Display version number")
    parser.add_argument("--bmc_ips", dest="bmc_ips", type=str, nargs="*",
                        help="a list of hosts to configure, or none to use cluster beacons", default=None)
    parser.add_argument("--bmc_username", dest="bmc_username", type=str, nargs=1,
                        help="a username to use on all hosts in --bmc_ips", default=None)
    parser.add_argument("--bmc_password", dest="bmc_password", type=str, nargs=1,
                        help="a password to use on all hosts in --bmc_ips", default=None)
    parser.add_argument("-v", "--verbose", dest='verbosity', action='store_true', help="enable verbose mode")
    parser.add_argument("--version", dest='version', action='store_true', help="report program version and exit")

    args = parser.parse_args()

    if args.version:
        print(f"{progname} version 2024.08.15")
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
            log.error("You must provide a username and password when using --bmc_ips")
            sys.exit(1)
        log.info(f"Using BMC IPs - ignoring {args.hostconfigfile}")
        conf = _generate_config(args.bmc_ips, args.bmc_username, args.bmc_password)
    else:
        try:
            conf = _load_config(args.hostconfigfile)
        except Exception as exc:
            log.error(f"Unable to open host configuration file: {exc}")
            sys.exit(1)

    if args.bmc_config:
        log.info("Configuring BMCs")
        for host in conf['hosts']:
            log.info(f"Configuring {host['name']}")
            bmc_setup(host['name'], host['user'], host['password'])
        log.info("BMCs have been configured")
        sys.exit(0)

    try:
        desired_bios_settings = _load_config(args.bios)
    except Exception as exc:
        log.error(f"Unable to parse bios settings configuration file: {exc}")
        sys.exit(1)

    if args.diff:
        hostlist = list()
        for c_host in args.diff:
            try:
                hostlist.append([x for x in conf['hosts'] if x['name'] == c_host][0])
            except:
                log.error(f"host {c_host} not in {args.hostconfigfile}")
                sys.exit(1)
    else:
        hostlist = conf['hosts']

    # connect to all the hosts
    redfish_list = list()
    for host in hostlist:
        log.info(f"Fetching BIOS settings of host {host['name']}")
        try:
            redfish_list.append(RedFishBMC(host['name'], username=host['user'], password=host['password']))
        except redfish.rest.v1.InvalidCredentialsError:
            #log.error(f"Error opening connections to {host['name']} - invalid credentials")
            # error message is already logged
            continue
        except Exception as exc:
            log.error(f"Error opening connections to {host['name']}: {exc}")
            print(traceback.format_exc())
        # redfish_list.append(RedFishBMC(host['name'], username=host['user'], password=host['password']))

    if args.diff:
        if len(redfish_list) != 2:
            log.error(f"hostlist has too few members to continue")
        elif not bios_diff(redfish_list):
            log.info("The servers have identical BIOS settings")
    elif args.reset_bios:
        for bmc in redfish_list:
            bmc.reset_settings_to_default()
            log.info(f"{bmc.name} has been reset to factory defaults")
            if args.reboot:
                bmc.reboot()
                log.info(f"{bmc.name} has been rebooted")
    else:
        # check BIOS settings
        hosts_needing_changes = list()
        fixed_hosts = list()
        systems_rebooted = list()
        for bmc in redfish_list:
            if args.dump:
                bmc.print_settings()
                continue
            else:
                count = bmc.check_settings(desired_bios_settings[bmc.vendor][bmc.arch])
            log.info(f"")
            if count > 0:
                log.warning(f"{count} changes are needed on {bmc.name}")
                hosts_needing_changes.append(bmc)
                if args.fix:
                    if bmc.change_settings(desired_bios_settings[bmc.vendor][bmc.arch]):
                        fixed_hosts.append(bmc)
                    else:
                        log.error(f"Unable to fix {bmc.name}")
            else:
                log.warning(f"No changes are needed on {bmc.name}")
            log.info("")
            # if they said reboot, reboot
            if args.reboot:
                if args.fix and bmc in fixed_hosts: # --fix --reboot implies rebooting only the hosts that were fixed
                    log.info(f"Rebooting {bmc.name}")
                    bmc.reboot()
                    systems_rebooted.append(bmc)
                elif not args.fix:  # they asked to reboot all hosts
                    log.info(f"Rebooting {bmc.name}")
                    bmc.reboot()
                    systems_rebooted.append(bmc)

        if not args.fix:
            log.info(f"There are {len(hosts_needing_changes)} hosts needing changes")
        else:
            if not args.reboot:
                log.info(f"{len(fixed_hosts)} have been modified.  Please reboot them to activate changes.")
            else:
                log.info(f"{len(systems_rebooted)} have been successfully modified and rebooted.")

    for host in redfish_list:
        host.redfish.logout()


if __name__ == '__main__':
    main()
