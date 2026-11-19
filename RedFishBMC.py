import json
#from pprint import pprint

import redfish

from logging import getLogger

#from setuptools.command.build_ext import if_dl

#from paramiko.util import log_to_file

log = getLogger(__name__)


def is_hex(param):
    import string
    return all(c in string.hexdigits for c in param)

def trim_supermicro_key(key):
    # Supermicro uses a _XXXX (hex) suffix for the key - trim it off
    return key[:-5] if (key[-5] == "_" and is_hex(key[-4])) else key


READ_TIMEOUT = 60
WRITE_TIMEOUT = 300
SETTINGS_OBJECTS = ("Settings", "SD", "Pending")    # Dell and HPE, Supermicro, Lenovo


def ok(resp):
    return resp.status in (200, 201, 202, 204)


def same(a, b):
    """Whether two BIOS values are equal, as BMCs and YAML spell them: "1" and 1, False and false."""
    def norm(value):
        return str(value).lower() if isinstance(value, bool) else str(value)
    return norm(a) == norm(b)


CPU_VENDOR_IDS = {"AuthenticAMD": "AMD", "GenuineIntel": "Intel"}
CPU_NAME_HINTS = [("AMD", "AMD"), ("EPYC", "AMD"), ("INTEL", "Intel"), ("XEON", "Intel"),
                  ("AMPERE", "ARM"), ("NEOVERSE", "ARM"), ("GRACE", "ARM"), ("ARM", "ARM")]


def cpu_arch(processor):
    """The bios_settings.yml architecture (AMD, Intel or ARM) of a Redfish Processor, or None if it is not a CPU or
    cannot be told. The Redfish fields come first; BMCs that leave them out are recognised by the CPU's name."""
    if processor.get("ProcessorType", "CPU") != "CPU" or processor.get("Status", {}).get("State") == "Absent":
        return None
    arch = str(processor.get("ProcessorArchitecture") or "").upper()
    instruction_set = str(processor.get("InstructionSet") or "").upper()
    if arch == "ARM" or instruction_set.startswith("ARM"):
        return "ARM"
    vendor_id = (processor.get("ProcessorId") or {}).get("VendorId")
    if vendor_id in CPU_VENDOR_IDS:
        return CPU_VENDOR_IDS[vendor_id]
    name = f"{processor.get('Manufacturer') or ''} {processor.get('Model') or ''}".upper()
    for hint, cpu in CPU_NAME_HINTS:
        if hint in name:
            return cpu
    return None


def trim_supermicro_dict(settings_dict):
    new_settings_dict = dict()
    for key, value in settings_dict.items():
        new_settings_dict[trim_supermicro_key(key)] = value
    return new_settings_dict


class RedFishBMC(object):
    def __init__(self, hostname, username=None, password=None, ca_file=None):
        # create the redfish object
        self.cdrom_eject_uri = None
        self.cdrom_mount_uri = None
        self.cdrom_dev = None
        self.cdrom_uri = None
        self.virtual_media_list = None
        self.virtual_media_data = None
        self.virtual_media_uri = None
        self.redfish = redfish.redfish_client(base_url="https://" + hostname, username=username, password=password,
                                              default_prefix='/redfish/v1', timeout=10, max_retry=2,
                                              cafile=ca_file)

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

        # every later read gets READ_TIMEOUT, every write WRITE_TIMEOUT, so a BMC that stops answering cannot hang the run
        self.redfish._timeout = READ_TIMEOUT
        try:
            self._discover()
        except Exception:
            self.close()
            raise

    def close(self):
        try:
            self.redfish.logout()
        except Exception as exc:
            log.warning(f"Could not log out of {self.name}: {exc}")

    def _only_member(self, collection_uri, what):
        members = self.redfish.get(collection_uri).dict.get('Members', [])
        if len(members) != 1:
            raise Exception(f"{self.name} has {len(members)} {what}s; bios_tool works with a BMC that has exactly one")
        uri = members[0]['@odata.id']
        return uri, self.redfish.get(uri)

    def _discover(self):
        root = self.redfish.root
        self.vendor = next(iter((root.get("Oem") or {}).keys()), None) or root.get("Vendor")

        self.systems_members_uri, self.systems_members_response = self._only_member(root['Systems']['@odata.id'],
                                                                                     "system")
        system = self.systems_members_response.dict
        self.manufacturer = system.get('Manufacturer')
        self.model = system.get('Model')
        self.bios_version = system.get('BiosVersion')

        reset = system.get('Actions', {}).get('#ComputerSystem.Reset', {})
        self.reset_target = reset.get('target')
        self.system_reset_types = reset.get('ResetType@Redfish.AllowableValues')
        if self.system_reset_types is None and '@Redfish.ActionInfo' in reset:
            parameters = self.redfish.get(reset['@Redfish.ActionInfo']).dict.get('Parameters', [])
            self.system_reset_types = next((p.get('AllowableValues') for p in parameters
                                            if p.get('Name', 'ResetType') == 'ResetType'), None)
        self.system_reset_types = self.system_reset_types or []

        self.arch = None
        processors = system.get('Processors', {}).get('@odata.id')
        for member in self.redfish.get(processors).dict.get('Members', []) if processors else []:
            self.arch = cpu_arch(self.redfish.get(member['@odata.id']).dict)
            if self.arch is not None:
                break

        if 'Bios' not in system:
            raise Exception(f"{self.name} does not offer its BIOS settings over Redfish")
        self.bios_uri = system['Bios']['@odata.id']
        self.bios_data = self.redfish.get(self.bios_uri)
        if self.bios_data.status != 200 or 'error' in self.bios_data.dict:
            info = self.bios_data.dict.get('error', {}).get('@Message.ExtendedInfo', '')
            raise Exception(f"Error fetching BIOS settings for {self.name} (HTTP {self.bios_data.status}): {info}")
        self.reset_bios_uri = self.bios_data.dict.get('Actions', {}).get('#Bios.ResetBios', {}).get('target')
        settings = self.bios_data.dict.get('@Redfish.Settings') or {}
        self.supported_apply_times = settings.get('SupportedApplyTimes')
        self.bios_settings_uri = settings.get('SettingsObject', {}).get('@odata.id') or self._find_settings_object()

        self.managers_members_uri = None
        self.managers_members_response = None
        self.bmc_firmware_version = None
        if 'Managers' in root:
            members = self.redfish.get(root['Managers']['@odata.id']).dict.get('Members', [])
            if members:
                self.managers_members_uri = members[0]['@odata.id']
                self.managers_members_response = self.redfish.get(self.managers_members_uri)
                self.bmc_firmware_version = self.managers_members_response.dict.get('FirmwareVersion')

    def _find_settings_object(self):
        """Where BIOS changes are staged, for a BMC whose BIOS resource does not say: the vendors' usual places."""
        for name in SETTINGS_OBJECTS:
            uri = f"{self.bios_uri}/{name}"
            if self.redfish.get(uri).status == 200:
                log.info(f"{self.name} does not say where to stage BIOS changes; using {uri}")
                return uri
        log.warning(f"{self.name} does not say where to stage BIOS changes, and none of the usual places exist")
        return None

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
        """Stages settings_dict for the next reboot, and confirms the BMC staged every one of them."""
        if self.bios_settings_uri is None:
            log.error(f"{self.name} does not say where to stage BIOS changes, so they cannot be made")
            return False
        on_reset = self.supported_apply_times is not None and "OnReset" in self.supported_apply_times

        resp = self._patch_settings(settings_dict, on_reset)
        if resp.status == 400 and on_reset:
            # some iDRAC firmware refuses the annotation it advertises
            log.info(f"{self.name} refused the apply time; trying again without it")
            on_reset = False
            resp = self._patch_settings(settings_dict, on_reset)
        refused = []
        if resp.status >= 500 and len(settings_dict) > 1:
            # Supermicro fails the whole PATCH for one value it does not take, so find which
            log.info(f"{self.name} refused the BIOS changes (HTTP {resp.status}); trying them one at a time")
            for key, value in settings_dict.items():
                if not ok(self._patch_settings({key: value}, on_reset)):
                    refused.append(f"{key}={value}")
        elif not ok(resp):
            messages = [info.get('Message', '') for info in
                        resp.dict.get('error', {}).get('@Message.ExtendedInfo', [])]
            log.error(f"{self.name} refused the BIOS changes (HTTP {resp.status}): {' '.join(messages)}")
            return False
        if refused:
            log.error(f"{self.name} refused {', '.join(refused)}")
        if len(refused) == len(settings_dict):
            return False
        if not on_reset and self.is_dell() and not self._create_dell_bios_job():
            return False

        staged = self.staged_settings()
        if not staged:
            log.warning(f"{self.name} accepted the BIOS changes but does not show what it staged, so they could not "
                        f"be confirmed")
            return not refused
        not_staged = [f"{key}={value}" for key, value in settings_dict.items()
                      if f"{key}={value}" not in refused and not same(staged.get(key), value)]
        if not_staged:
            log.error(f"{self.name} accepted the BIOS changes but did not stage {', '.join(not_staged)}")
            return False
        log.info(f"{self.name} staged {len(settings_dict) - len(refused)} BIOS changes; they apply at its next reboot")
        return not refused

    def _patch_settings(self, attributes, on_reset):
        """PATCHes attributes to the settings object; with the object's ETag if the BMC demands one (Supermicro)."""
        body = {'Attributes': attributes}
        if on_reset:
            body["@Redfish.SettingsApplyTime"] = {"ApplyTime": "OnReset"}
        resp = self.redfish.patch(self.bios_settings_uri, body=body, timeout=WRITE_TIMEOUT)
        if resp.status in (412, 428):
            etag = self._settings_etag()
            if etag:
                resp = self.redfish.patch(self.bios_settings_uri, body=body, headers={"If-Match": etag},
                                          timeout=WRITE_TIMEOUT)
        return resp

    def _settings_etag(self):
        resp = self.redfish.get(self.bios_settings_uri)
        header = resp.getheader("ETag") if hasattr(resp, "getheader") else None
        return resp.dict.get("@odata.etag") or header

    def is_dell(self):
        return self.vendor == "Dell" or str(self.manufacturer).startswith("Dell")

    def _create_dell_bios_job(self):
        """Without an apply time, iDRAC applies staged BIOS changes only through a configuration job."""
        if self.managers_members_uri is None:
            log.error(f"{self.name} has no manager to create the BIOS job on, so the changes will not be applied")
            return False
        body = {"TargetSettingsURI": self.bios_settings_uri}
        for jobs in (f"{self.managers_members_uri}/Jobs", f"{self.managers_members_uri}/Oem/Dell/Jobs"):
            resp = self.redfish.post(jobs, body=body, timeout=WRITE_TIMEOUT)
            if ok(resp):
                log.info(f"{self.name} has a BIOS configuration job to apply the changes at its next reboot")
                return True
            if resp.status != 404:
                break
        log.error(f"{self.name} did not create the BIOS configuration job (HTTP {resp.status}), so the changes will "
                  f"not be applied at its next reboot")
        return False

    def check_settings(self, settings):
        """The settings that need changing, and those already staged and waiting for a reboot."""
        current = self.bios_data.dict['Attributes']
        staged = self.staged_settings()
        to_change, waiting = dict(), dict()
        for key, value in settings.items():
            if key not in current:
                log.error(f"desired key ({key}) is not part of {self.name}'s bios!")
            elif same(current[key], value):
                continue
            elif key in staged and same(staged[key], value):
                log.info(f"{self.name}: BIOS setting {key} is {current[key]}, and {value} is waiting for a reboot")
                waiting[key] = value
            else:
                log.info(f"{self.name}: BIOS setting {key} is {current[key]}, but should be {value}")
                to_change[key] = value
        return to_change, waiting

    def staged_settings(self):
        """The BIOS settings staged on the BMC for the next reboot, or {} if it shows none."""
        if self.bios_settings_uri is None:
            return {}
        try:
            resp = self.redfish.get(self.bios_settings_uri)
        except Exception as exc:
            log.warning(f"Could not read the BIOS changes staged on {self.name}: {exc}")
            return {}
        return resp.dict.get('Attributes', {}) if resp.status == 200 else {}

    def pending_changes(self):
        """The BIOS settings staged on the BMC that differ from the current ones, applied at the next reboot."""
        current = self.bios_data.dict['Attributes']
        return {key: value for key, value in self.staged_settings().items() if not same(current.get(key), value)}

    def reset_settings_to_default(self):
        if self.reset_bios_uri is None:
            log.error(f"{self.name} does not offer a BIOS reset to defaults")
            return False
        try:
            resp = self.redfish.post(self.reset_bios_uri, body={}, timeout=WRITE_TIMEOUT)
        except Exception as exc:
            log.error(f"{self.name} could not be asked to reset its BIOS: {exc}")
            return False
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
        action = self.reset_target
        if action is None:
            log.error(f"{self.name} does not offer a way to reboot it")
            return False
        try:
            power_state = self.redfish.get(self.systems_members_uri).dict.get('PowerState')
            if power_state != "On":
                reset_type = 'On'
            elif 'GracefulRestart' in self.system_reset_types:
                reset_type = 'GracefulRestart'
            elif 'ForceRestart' in self.system_reset_types:
                reset_type = 'ForceRestart'
            else:
                reset_type = 'On'
            resp = self.redfish.post(action, body={'ResetType': reset_type}, timeout=WRITE_TIMEOUT)
        except Exception as exc:
            log.error(f"{self.name} could not be asked to reboot: {exc}")
            return False
        if resp.status not in [200, 201, 202, 203, 204]:
            log.error(f"{self.name} refused to reboot ({reset_type}): HTTP {resp.status}")
            return False
        log.info(f"{self.name} accepted a {reset_type}")
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
