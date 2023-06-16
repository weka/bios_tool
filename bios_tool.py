import argparse
import logging
import sys
import yaml

from wekapyutils.wekalogging import configure_logging, register_module
from RedFishBMC import RedFishBMC
from tabulate import tabulate

# get root logger
log = logging.getLogger()


def _load_config(inputfile):
    try:
        f = open(inputfile)
    except Exception as exc:
        raise
    with f:
        try:
            return yaml.load(f, Loader=yaml.FullLoader)
        except AttributeError:
            return yaml.load(f)
        except Exception as exc:
            log.error(f"Error reading config file: {exc}")
            raise


def bios_diff(hostlist):
    hosta = hostlist[0]
    hostb = hostlist[1]

    hosta_bios = hosta.bios_data.dict['Attributes']
    hostb_bios = hostb.bios_data.dict['Attributes']

    if hosta.arch != hostb.arch:
        print()
        print("WARNING: Hosts are of different architectures!")

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
                        default="host_config.yml")
    parser.add_argument("-b", "--bios", type=str, nargs="?", help="bios configuration filename",
                        default="bios_settings.yml")
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

    # these next args are passed to the script and parsed in etc/preamble - this is more for syntax checking
    parser.add_argument("-v", "--verbose", dest='verbosity', action='store_true', help="enable verbose mode")

    args = parser.parse_args()

    # local modules - override a module's logging level
    register_module("RedFishBMC", logging.INFO)
    register_module("redfish.rest.v1", logging.ERROR)

    # set up logging in a standard way...
    configure_logging(log, args.verbosity)

    try:
        conf = _load_config(args.hostconfigfile)
    except Exception as exc:
        log.error(f"Unable to open host configuration file: {exc}")
        sys.exit(1)

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
        except Exception as exc:
            log.error(f"Error opening connections to {host['name']}: {exc}")
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
        hosts_needing_changes = 0
        fixed_hosts = 0
        systems_rebooted = 0
        for bmc in redfish_list:
            if args.dump:
                bmc.print_settings()
                continue
            else:
                count = bmc.check_settings(desired_bios_settings[bmc.vendor][bmc.arch])
            log.info(f"")
            if count > 0:
                log.warning(f"{count} changes are needed on {bmc.name}")
                hosts_needing_changes += 1
                if args.fix:
                    #if bmc.vendor == "Dell":    # Dell requires this, but it breaks SMC
                    #    body["@Redfish.SettingsApplyTime"] = {"ApplyTime": "OnReset"}
                    if bmc.change_settings(desired_bios_settings[bmc.vendor][bmc.arch]):
                        fixed_hosts += 1
                        if args.reboot:
                            if bmc.reboot():
                                systems_rebooted += 1
            else:
                log.warning(f"No changes are needed on {bmc.name}")

        if not args.fix:
            log.info(f"There are {hosts_needing_changes} hosts needing changes")
        else:
            if not args.reboot:
                log.info(f"{fixed_hosts} have been modified.  Please reboot them to activate changes.")
            else:
                log.info(f"{systems_rebooted} have been successfully modified and rebooted.")

    for host in redfish_list:
        host.redfish.logout()


if __name__ == '__main__':
    main()
