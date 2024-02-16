# BMC setup.py - setup the BMC for the host; check for brand and ensure redfish and ipmi over lan are enabled

from wekapyutils.wekassh import RemoteServer

from paramiko.util import log_to_file
import logging
log_to_file("paramiko.log", logging.DEBUG)

def dell_bmc_setup(host, user, password):
    # check for brand and ensure redfish and ipmi over lan are enabled
    # check for brand
    # check for redfish
    # check for ipmi over lan
    # enable redfish
    # enable ipmi over lan
    # reboot
    # check for redfish
    # check for ipmi over lan
    # return True if all is well, False if not
    ssh_sess = RemoteServer(host)
    ssh_sess.kwargs['disabled_algorithms'] = { 'kex': ['rsa-sha2-512', 'rsa-sha2-256']}
    ssh_sess.user = user
    ssh_sess.password = password
    ssh_sess.connect()
    ssh_sess.run("getssninfo")
    if ssh_sess.output.status == 0:
        print("Dell")
        ssh_sess.run("racadm set iDRAC.Redfish.Enable Enabled")
        ssh_sess.run("racadm set iDRAC.IPMIlan.Enable Enabled")
        #ssh_sess.run("racadm set bios.BiosBootSettings.BootMode Uefi")
    else:
        print("not Dell")
        # Hpe:     set /map1/config1 oemHPE_ipmi_dcmi_overlan_enable=yes ???
        return False
    ssh_sess.run("exit")
    return True

    pass


if __name__ == '__main__':
    dell_bmc_setup('172.29.3.1', 'Administrator', 'Administrator')
    #bmc_setup('172.29.3.40', 'root', 'Administrator')
    dell_bmc_setup('172.29.3.120', 'root', 'Administrator')
    dell_bmc_setup('172.29.3.121', 'root', 'Administrator')
    dell_bmc_setup('172.29.3.122', 'root', 'Administrator')
    dell_bmc_setup('172.29.3.123', 'root', 'Administrator')
    dell_bmc_setup('172.29.3.124', 'root', 'Administrator')
    dell_bmc_setup('172.29.3.125', 'root', 'Administrator')
    dell_bmc_setup('172.29.3.126', 'root', 'Administrator')
    dell_bmc_setup('172.29.3.127', 'root', 'Administrator')

    print("done")