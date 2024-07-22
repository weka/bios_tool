# BMC setup.py - setup the BMC for the host; check for brand and ensure redfish and ipmi over lan are enabled
import time

from wekapyutils.wekassh import RemoteServer
#from wekassh2 import RemoteServer

from paramiko.util import log_to_file
import logging
#from fabric.api import *
#from fabric.contrib.console import confirm

log_to_file("paramiko.log", logging.DEBUG)

def bmc_setup(host, user, password):
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
    #connect_kwargs = {'username': user, 'password': password, "connect_kwargs": {"look_for_keys": False}}
    #connect_kwargs = {'username': user, 'password': password}

    #connect_kwargs = {'password': password}
    ssh_sess = RemoteServer(host)
    #ssh_sess = RemoteServer(host, connect_kwargs=connect_kwargs)
    #ssh_sess.connection.connect_kwargs['disabled_algorithms'] = {'kex': ['rsa-sha2-512', 'rsa-sha2-256'],
    #                                                             'kex': ['rsa-sha2-512', 'rsa-sha2-256']}
    #ssh_sess.connection.connect_kwargs['username'] = user
    #ssh_sess.connection.connect_kwargs['password'] = password
    #if 'key_filename' in ssh_sess.connection.connect_kwargs:
    #    ssh_sess.connection.connect_kwargs.pop('key_filename')
    ssh_sess.user = user
    ssh_sess.password = password
    ssh_sess.kwargs = {"allow_agent": False, "look_for_keys": False}
    ssh_sess.connect(allow_agent=False, look_for_keys=False)
    shell = ssh_sess.invoke_shell()
    time.sleep(1)
    output = shell.recv(1000).strip().decode("utf-8")
    #ssh_sess.run("getssninfo")
    #if ssh_sess.output.status == 0:
    #    print("Dell")
    #    ssh_sess.run("racadm set iDRAC.Redfish.Enable Enabled")
    #    ssh_sess.run("racadm set iDRAC.IPMIlan.Enable Enabled")
    #    return True

    # try Lenovo:
    if output.endswith("system>"):
        print("Lenovo")
        # To effectively enable this service, you must ensure that 'ipmi' is selected in the '-ai' option of the 'users' command.
        ssh_sess.run("portcontrol -ipmi on") # lenovo
        ssh_sess.run("users -curr")
        try:
            user = ssh_sess.output.stdout.split("\r\r\n")[-2].split()[0]
        except:
            print(f"ERROR: Lenovo server {host}: Unable to determine user")
            return False
        #print(f"Lenovo host {host}: user: {user}")
        ssh_sess.run(f"users")
        all_users = ssh_sess.output.stdout.split("\r\n")
        #print(f"Lenovo host {host}: user_id: {all_users}")
        user_id = None
        for line in all_users:
            if user in line:
                user_id = line.split()[0].strip()
                #print(f"Lenovo host {host}: {user_id}")
                break
        if user_id is None:
            print(f"ERROR: Lenovo server {host}: Unable to determine user_id")
            return False
        ssh_sess.run(f"users -{user_id} -ai web|redfish|ssh|ipmi")
    elif output.endswith("racadm>>"):
        print("Dell")
        ssh_sess.run("racadm set iDRAC.Redfish.Enable Enabled")
        ssh_sess.run("racadm set iDRAC.IPMIlan.Enable Enabled")
        return True
    elif output.endswith("</>hpiLO->"):
        print("HPe")
        # HPe:
        # set /map1/config1 oemHPE_ipmi_dcmi_overlan_enable=yes
        # redfish appears to always be set to enabled
        # might be able to do this via RedFish...
        ssh_sess.run("set /map1/config1 oemHPE_ipmi_dcmi_overlan_enable=yes")
    else:
        print("Unknown BMC type")
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