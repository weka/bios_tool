# BMC setup.py - setup the BMC for the host; check for brand and ensure redfish and ipmi over lan are enabled
import time

from wekapyutils.wekassh import RemoteServer

# from paramiko.util import log_to_file
import logging

log = logging.getLogger(__name__)
#log_to_file("paramiko.log", logging.DEBUG)

def hpe_is_date(string):
    if (string.startswith("Mon") or
            string.startswith("Tue") or
            string.startswith("Wed") or
            string.startswith("Thu") or
            string.startswith("Fri") or
            string.startswith("Sat") or
            string.startswith("Sun")):
        return True
    return False

def hpe_string_to_dict(string):
    # convert the string to a dictionary
    # example string:
    #   'set /map1/config1 oemHPE_ipmi_dcmi_overlan_enable=yes\r\r\nstatus=2\r\nstatus_tag=COMMAND PROCESSING FAILED\r\nerror_tag=COMMAND ERROR-UNSPECIFIED\r\nTue Jul 23 09:58:45 2024\r\n\r\nProperty value already set.\r\n\r\n\r\n'
    temp = string.splitlines()
    temp_dict = dict()
    for line in temp:
        if "=" in line:
            key, value = line.split("=")
            temp_dict[key] = value
        else:
            if len(line) == 0:
                continue
            if hpe_is_date(line):
                temp_dict["date"] = line
            else:
                temp_dict["message"] = line
    return temp_dict


def lenovo_parse_return(string):
    # parse the output of bmc commands
    # example output:
    #   'system> To create a new user, you must provide all fields\r\r\nsystem>'
    line = string.splitlines()[0]
    trimmed = line[8:].strip()
    return trimmed


def bmc_setup(host, user, password):
    # check for brand and ensure redfish and ipmi over lan are enabled
    # enable redfish
    # enable ipmi over lan
    # return True if all is well, False if not


    ssh_sess = RemoteServer(host)

    ssh_sess.user = user
    ssh_sess.password = password
    ssh_sess.kwargs = {"allow_agent": False, "look_for_keys": False}
    #ssh_sess.connect(allow_agent=False, look_for_keys=False)
    ssh_sess.connect()
    shell = ssh_sess.invoke_shell()
    time.sleep(0.5)
    output = shell.recv(500).strip().decode("utf-8")

    # try Lenovo:
    if output.endswith("system>"):
        log.info(f"Lenovo server detected at {host}")
        # To effectively enable this service, you must ensure that 'ipmi' is selected in the '-ai' option of the 'users' command.
        ssh_sess.run("portcontrol -ipmi on") # lenovo
        # try to find our user id number - it doesn't take names
        user_id = None
        ssh_sess.run(f"users")
        all_users = ssh_sess.output.stdout.splitlines()
        for line in all_users:
            if user in line:
                user_id = line.split()[0].strip()
                #print(f"Lenovo host {host}: {user_id}")
                break

        if user_id is None:
            log.error(f"Lenovo server {host}: Unable to determine user_id")
            return False
        ret = ssh_sess.run(f"users -{user_id} -ai web|redfish|ssh|ipmi")
        message = lenovo_parse_return(ret.stdout)
        if message != "ok":
            log.error(f"Lenovo server {host}: Error enabling IPMI over LAN: {message}")
    elif output.endswith("racadm>>"):  # Dell
        log.info(f"Dell server detected at {host}")
        # ret.stdout starts with ERROR: if there's a problem. status is always 0
        ret = ssh_sess.run("racadm set iDRAC.Redfish.Enable Enabled")
        if ret.stdout.startswith("ERROR:"):
            log.error(f"Error enabling RedFish on {host}: {ret.stdout}")
            return False
        ret = ssh_sess.run("racadm set iDRAC.IPMIlan.Enable Enabled")
        if ret.stdout.startswith("ERROR:"):
            log.error(f"Error enabling IPMIlan on {host}: {ret.stdout}")
            return False
        return True
    elif output.endswith("</>hpiLO->"): # HPe
        log.info(f"HPe server detected at {host}")
        # HPe:
        # set /map1/config1 oemHPE_ipmi_dcmi_overlan_enable=yes
        # redfish appears to always be set to enabled
        # might be able to do this via RedFish...
        ret = ssh_sess.run("set /map1/config1 oemHPE_ipmi_dcmi_overlan_enable=yes")
        parsed_ret = hpe_string_to_dict(ret.stdout)
        if len(parsed_ret) > 0 and parsed_ret["status"] != "0":
            log.error(f"Error enabling IPMI over LAN on {host}: {parsed_ret['message']}")
            return False
    else:
        log.error(f"Unknown BMC type detected at {host}")
        return False
    ssh_sess.run("exit")
    return True



if __name__ == '__main__':
    bmc_setup('172.29.3.1', 'Administrator', 'Administrator') # hpe
    bmc_setup('172.29.3.164', 'ADMIN', '_PASSWORD_1!') # lenovo
    #bmc_setup('172.29.3.66', 'USERID', 'Passw0rd!!')
    #bmc_setup('172.29.3.67', 'USERID', 'Passw0rd!!')
    #bmc_setup('172.29.3.68', 'USERID', 'Passw0rd!!')
    #bmc_setup('172.29.3.69', 'USERID', 'Passw0rd!!')
    #bmc_setup('172.29.3.70', 'USERID', 'Passw0rd!!')

    bmc_setup('172.29.1.74', 'root', 'Administrator') # dell
    #dell_bmc_setup('172.29.3.120', 'root', 'WekaService')
    # dell_bmc_setup('172.29.3.121', 'root', 'Administrator')
    # dell_bmc_setup('172.29.3.122', 'root', 'Administrator')
    # dell_bmc_setup('172.29.3.123', 'root', 'Administrator')
    # dell_bmc_setup('172.29.3.124', 'root', 'Administrator')
    # dell_bmc_setup('172.29.3.125', 'root', 'Administrator')
    # dell_bmc_setup('172.29.3.126', 'root', 'Administrator')
    # dell_bmc_setup('172.29.3.127', 'root', 'Administrator')

    print("done")