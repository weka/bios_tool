import json
import redfish

from logging import getLogger

log = getLogger(__name__)


class RedFishBMC(object):
    def __init__(self, hostname, username=None, password=None):
        # create the redfish object
        self.redfish = redfish.redfish_client(base_url="https://" + hostname, username=username, password=password,
                                              default_prefix='/redfish/v1')

        # login
        self.name = hostname
        try:
            self.redfish.login(auth="session")
        except redfish.rest.v1.InvalidCredentialsError:
            log.error(f"Error logging into {hostname} - invalid credentials")
            raise
        except Exception as exc:
            log.error(f"Error logging into {hostname}: {exc}")
            raise

        # get the Vendor ID
        self.vendor = next(iter(self.redfish.root.get("Oem", {}).keys()), None)

        # get Systems
        self.systems_uri = self.redfish.root['Systems']['@odata.id']
        self.systems_response = self.redfish.get(self.systems_uri)  # ie: /redfish/v1/Systems
        self.systems_members_uri = next(iter(self.systems_response.dict['Members']))['@odata.id']
        self.systems_members_response = self.redfish.get(self.systems_members_uri)  # ie: /redfish/v1/Systems/1

        # get Processors
        self.proc_uri = self.systems_members_response.dict['Processors']['@odata.id']
        self.proc_data = self.redfish.get(self.proc_uri)
        self.proc_members_uri = next(iter(self.proc_data.dict['Members']))['@odata.id']
        self.proc_members_response = self.redfish.get(self.proc_members_uri)  # ie: /redfish/v1/Processors/1
        # note the architecture
        self.arch = "AMD" if self.proc_members_response.dict.get("Model", None)[0] == 'A' else "Intel"

        # fetch the BIOS settings
        self.bios_uri = self.systems_members_response.dict['Bios']['@odata.id']
        self.bios_data = self.redfish.get(self.bios_uri)  # ie: /redfish/v1/Systems/1/Bios

        self.bios_actions_dict = self.bios_data.dict['Actions']
        self.reset_bios_uri = self.bios_actions_dict['#Bios.ResetBios']['target']
        self.bios_settings_uri = self.bios_data.dict['@Redfish.Settings']['SettingsObject']['@odata.id']

        #self.settings = self.redfish.get(self.bios_settings_uri)
        #oem = self.settings.dict['Oem']
        #vendor_stanza = oem[self.vendor]
        #jobs = self.redfish.get(vendor_stanza['Jobs']['@odata.id'])
        #members = jobs.dict['Members']
        #actions = self.settings.dict['Actions']
        #log.info("settings received")
        # Job: Configure: BIOS.Setup.1-1

    def get_cdrom_info(self):
        # get the Virtual CDROM
        self.managers_uri = self.redfish.root['Managers']['@odata.id']
        self.managers_data = self.redfish.get(self.managers_uri)
        self.managers_members_uri = next(iter(self.managers_data.dict['Members']))['@odata.id']
        self.managers_members_response = self.redfish.get(self.managers_members_uri)  # ie: /redfish/v1/Managers/1
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

        # body = {'Attributes': {bios_property: property_value}}
        body = dict()
        body['Attributes'] = settings_dict

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
        if settings is None:
            log.info(f"{self.name} There are no settings for this platform in the bios settings configuration file")
            return 0
        vendor = self.vendor
        arch = self.arch
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
            log.error(f"An http response of '{resp.status}' was returned attempting to reboot {self.name}.\n")
            return False
        else:
            return True
        pass

    def print_settings(self):
        print(f"{self.name} Current BIOS settings:")
        print(json.dumps(self.bios_data.obj.Attributes, indent=4, sort_keys=True))

    def reboot(self):
        action = self.systems_members_response.obj.Actions['#ComputerSystem.Reset']['target']
        # print(json.dumps(self.systems_members_response.obj.Actions['#ComputerSystem.Reset']))
        body = dict()
        #body['ResetType'] = 'ForceRestart'
        body['ResetType'] = 'GracefulRestart'
        resp = self.redfish.post(action, body=body)
        if resp.status not in [200,201,202,203,204]:
            log.error(f"An http response of '{resp.status}' was returned attempting to reboot {self.name}.\n")
            return False
        else:
            return True
