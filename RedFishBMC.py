import json
#from pprint import pprint

import redfish

from logging import getLogger

from setuptools.command.build_ext import if_dl

#from paramiko.util import log_to_file

log = getLogger(__name__)


def is_hex(param):
    import string
    return all(c in string.hexdigits for c in param)

def trim_supermicro_key(key):
    # Supermicro uses a _XXXX (hex) suffix for the key - trim it off
    return key[:-5] if (key[-5] == "_" and is_hex(key[-4])) else key


def trim_supermicro_dict(settings_dict):
    new_settings_dict = dict()
    for key, value in settings_dict.items():
        new_settings_dict[trim_supermicro_key(key)] = value
    return new_settings_dict


class RedFishBMC(object):
    def __init__(self, hostname, username=None, password=None):
        # create the redfish object
        self.cdrom_eject_uri = None
        self.cdrom_mount_uri = None
        self.cdrom_dev = None
        self.cdrom_uri = None
        self.virtual_media_list = None
        self.virtual_media_data = None
        self.virtual_media_uri = None
        self.redfish = redfish.redfish_client(base_url="https://" + hostname, username=username, password=password,
                                              default_prefix='/redfish/v1', timeout=10, max_retry=2)

        # login
        self.name = hostname
        self.username = username
        self.password = password
        try:
            self.redfish.login(auth="session")
        except redfish.rest.v1.InvalidCredentialsError:
            log.error(f"Error logging into {hostname} - invalid credentials")
            raise
        except Exception as exc:
            log.error(f"Error logging into {hostname}: {exc}")
            raise

        # increase timeout for all future operations
        self.redfish._timeout = None

        # get the Vendor ID
        self.vendor = next(iter(self.redfish.root.get("Oem", {}).keys()), None)
        if self.vendor is None:
            self.vendor = self.redfish.root.get("Vendor", None)

        # get Systems
        self.systems_uri = self.redfish.root['Systems']['@odata.id']
        self.systems_response = self.redfish.get(self.systems_uri)  # ie: /redfish/v1/Systems
        self.systems_members_uri = next(iter(self.systems_response.dict['Members']))['@odata.id']
        self.systems_members_response = self.redfish.get(self.systems_members_uri)  # ie: /redfish/v1/Systems/1

        # get bios identification info
        self.manufacturer = self.systems_members_response.dict.get('Manufacturer', None)
        self.model = self.systems_members_response.dict.get('Model', None)
        self.bios_version = self.systems_members_response.dict.get('BiosVersion', None)

        self.systems_members_response_actions = self.systems_members_response.dict['Actions']
        try:
            self.system_reset_types = self.systems_members_response_actions['#ComputerSystem.Reset']['ResetType@Redfish.AllowableValues']
        except KeyError:
            #self.system_reset_types = None   # SMC doesn't have this key...
            self.system_reset_action_info = self.redfish.get(
                        self.systems_members_response_actions['#ComputerSystem.Reset']['@Redfish.ActionInfo'])
            self.system_reset_types = self.system_reset_action_info.dict['Parameters'][0]['AllowableValues']

        # get Processors
        self.proc_uri = self.systems_members_response.dict['Processors']['@odata.id']
        self.proc_data = self.redfish.get(self.proc_uri)
        self.proc_members_uri = next(iter(self.proc_data.dict['Members']))['@odata.id']
        self.proc_members_response = self.redfish.get(self.proc_members_uri)  # ie: /redfish/v1/Processors/1
        # note the architecture
        self.arch = "AMD" if self.proc_members_response.dict.get("Model", None)[0] == 'A' else "Intel"

        # fetch the actual BIOS settings
        self.bios_uri = self.systems_members_response.dict['Bios']['@odata.id']
        self.bios_data = self.redfish.get(self.bios_uri)  # ie: /redfish/v1/Systems/1/Bios

        if 'error' in self.bios_data.dict:
            #log.error(f"Error fetching BIOS settings for {self.name}: {self.bios_data.dict['error']['@Message.ExtendedInfo']}")
            raise Exception(f"Error fetching BIOS settings for {self.name}: {self.bios_data.dict['error']['@Message.ExtendedInfo']}")
        self.bios_actions_dict = self.bios_data.dict['Actions']
        self.reset_bios_uri = self.bios_actions_dict['#Bios.ResetBios']['target']
        
        if '@Redfish.Settings' not in self.bios_data.dict:
            log.error(f"Error retrieving settings from {hostname} even though credentials are fine - check any pending/scheduled changes to the BMC and reboot" )

        self.bios_settings_uri = self.bios_data.dict['@Redfish.Settings']['SettingsObject']['@odata.id']
        #self.redfish_settings = self.bios_data.dict['@Redfish.Settings']
        if 'SupportedApplyTimes' in self.bios_data.dict['@Redfish.Settings']:
            self.supported_apply_times = self.bios_data.dict['@Redfish.Settings']['SupportedApplyTimes']
        else:
            self.supported_apply_times = None
        

        self.managers_uri = self.redfish.root['Managers']['@odata.id']
        self.managers_data = self.redfish.get(self.managers_uri)
        self.managers_members_uri = next(iter(self.managers_data.dict['Members']))['@odata.id']
        self.managers_members_response = self.redfish.get(self.managers_members_uri)  # ie: /redfish/v1/Managers/1
        self.managers_members_actions = self.managers_members_response.dict['Actions']
        self.bmc_firmware_version = self.managers_members_response.dict['FirmwareVersion']
        #print()

    def get_bios_settings(self):
        return self.bios_data.dict['Attributes']


    def get_cdrom_info(self):
        # get the Virtual CD-ROM
        self.virtual_media_uri = self.managers_members_response.dict['VirtualMedia']['@odata.id']
        self.virtual_media_data = self.redfish.get(self.virtual_media_uri)  # ie: /redfish/v1/Managers/1/VirtualMedia
        self.virtual_media_list = list()
        for device in self.virtual_media_data.dict['Members']:
            vdev = self.redfish.get(device['@odata.id'])
            # self.virtual_media_list.append(self.redfish.get(device['@odata.id']))
            for mediatype in vdev.obj.MediaTypes:
                if mediatype == 'CD' or mediatype == "DVD":
                    # found it!
                    self.cdrom_uri = device['@odata.id']
                    self.cdrom_dev = vdev
                    self.cdrom_mount_uri = vdev.dict['Actions']['#VirtualMedia.InsertMedia']['target']
                    self.cdrom_eject_uri = vdev.dict['Actions']['#VirtualMedia.EjectMedia']['target']
                    break

    def mount_cd(self, target):
        pass

    def eject_cd(self):
        pass

    def change_settings(self, settings_dict):
        #if self.vendor == "Supermicro":
        #    settings_dict = self.adjust_supermicro_settings(settings_dict)
        #    if settings_dict is None:
        #        return False

        # body = {'Attributes': {bios_property: property_value}}
        body = dict()
        body['Attributes'] = settings_dict

        # We should fetch the SupportedApplyTimes attribute from the settings object to see if we need to set it...
        if self.supported_apply_times is not None and "OnReset" in self.supported_apply_times:
            body["@Redfish.SettingsApplyTime"] = {"ApplyTime": "OnReset"}

        # make sure a patch, which can take a lot of time, doesn't time out like a new connection
        #self.redfish._timeout = None
        resp = self.redfish.patch(self.bios_settings_uri, body=body)

        # If iLO responds with something outside of 200 or 201 then lets check the iLO extended info
        # error message to see what went wrong
        if resp.status == 400:
            try:
                print(json.dumps(resp.dict['error']['@Message.ExtendedInfo'], indent=4, sort_keys=True))
            except Exception as exc:
                log.error(f"A response exception occurred, unable to access Extended information {exc}")
        elif resp.status not in [200,201,202]:
            log.error("An http response of \'%s\' was returned.\n" % resp.status)
        else:
            # print("\nSuccess!\n")
            log.info(f"Successfully set settings on host {self.name}; System reboot required")
            return True

        return False

    def check_settings(self, settings):
        log.info(f"Checking BIOS settings on {self.name}")
        if settings is None:
            log.info(f"{self.name} There are no settings for this platform in the bios settings configuration file")
            return 0

        #if self.vendor == "Supermicro":
        #    settings = self.adjust_supermicro_settings(settings)
        #    if settings is None:
        #        return 0

        count = 0
        for key, value in settings.items():
            if key not in self.bios_data.obj.Attributes:
                log.error(f"desired key ({key}) is not part of {self.name}'s bios!")
            else:
                if self.bios_data.obj.Attributes[key] != value:
                    log.info(f"{self.name}: BIOS setting {key} is {self.bios_data.obj.Attributes[key]}, " +
                             f"but should be {value}")
                    count += 1

        return count

    def reset_settings_to_default(self):
        resp = self.redfish.post(self.reset_bios_uri, body=None)
        if resp.status not in [200,201,202,203,204]:
            error_dict = resp.dict['error'] if 'error' in resp.dict else None
            log.error(f"An http response of '{resp.status}' was returned attempting to reset bios to default on {self.name}.")
            log.error(f"The URI attempted was {self.reset_bios_uri}\n")
            return False
        else:
            return True

    def print_settings(self):
        print(f"{self.name} Current BIOS settings:")
        print(json.dumps(self.bios_data.obj.Attributes, indent=4, sort_keys=True))

    def reboot(self):
        action = self.systems_members_response.obj.Actions['#ComputerSystem.Reset']['target']
        # print(json.dumps(self.systems_members_response.obj.Actions['#ComputerSystem.Reset']))
        body = dict()
        if self.systems_members_response.obj.PowerState != "On":
            body['ResetType'] = 'On'
        else:
            if 'GracefulRestart' in self.system_reset_types:
                body['ResetType'] = 'GracefulRestart'
            elif 'ForceRestart' in self.system_reset_types:
                body['ResetType'] = 'ForceRestart'
            else:
                body['ResetType'] = 'On'

        resp = self.redfish.post(action, body=body)
        print(f'reset status: {resp.status}')
        if resp.status not in [200,201,202,203,204]:
            log.error(f"An http response of '{resp.status}' was returned attempting to reboot {self.name}.\n")
            return False
        else:
            return True

    def adjust_supermicro_settings(self, settings_dict):
        new_settings_dict = dict()

        for key, value in settings_dict.items():
            new_key = self.supermicro_find_key(trim_supermicro_key(key))
            if new_key is None:
                log.error(f"Unable to find key {key} in the Supermicro BIOS settings")
                continue
            new_settings_dict[new_key] = value

        if len(new_settings_dict) == 0:
            log.error(f"Unable to find any keys in the Supermicro BIOS settings")
            return None
        return new_settings_dict

    def supermicro_find_key(self, key):
        # Supermicro (sometimes) uses a different key for the same setting (they add a _ and 4-digit hex number: xxx_010F
        # This function will convert the key to the correct one for Supermicro
        #keys = list(self.bios_data.obj.Attributes.keys())
        for server_key in self.bios_data.obj.Attributes.keys():
            if "_" in server_key and len(server_key) > 5 and server_key[-5] == "_" and is_hex(server_key[-4]) and server_key[:-5] == key:
                return server_key
            else:
                if server_key == key:
                    return server_key
        return None
