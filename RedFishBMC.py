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
        self.redfish.login(auth="session")

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

        self.bios_settings_uri = self.bios_data.dict['@Redfish.Settings']['SettingsObject']['@odata.id']

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
            except Exception:
                log.error("A response error occurred, unable to access iLO Extended " "Message Info...")
        elif resp.status != 200:
            log.error("An http response of \'%s\' was returned.\n" % resp.status)
        else:
            # print("\nSuccess!\n")
            log.info(f"Successfully set settings on host {self.name}; System reboot required")
            return True

        return False

    def check_settings(self, settings):
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

    def print_settings(self):
        print(f"{self.name} Current BIOS settings:")
        print(json.dumps(self.bios_data.obj.Attributes, indent=4, sort_keys=True))

    def reboot(self):
        action = self.systems_members_response.obj.Actions['#ComputerSystem.Reset']['target']
        # print(json.dumps(self.systems_members_response.obj.Actions['#ComputerSystem.Reset']))
        body = dict()
        body['ResetType'] = 'ForceRestart'
        resp = self.redfish.post(action, body=body)
        if resp.status != 200:
            log.error(f"An http response of '{resp.status}' was returned attempting to reboot {self.name}.\n")
            return False
        else:
            return True
