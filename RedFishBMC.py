import json

import redfish

from logging import getLogger

log = getLogger(__name__)


READ_TIMEOUT = 60
WRITE_TIMEOUT = 300
SETTINGS_OBJECTS = ("Settings", "SD", "Pending")    # Dell and HPE, Supermicro, Lenovo


def ok(resp):
    return resp.status in (200, 201, 202, 203, 204)


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


class RedFishBMC(object):
    def __init__(self, hostname, username=None, password=None, ca_file=None):
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
        self._staged = None         # the settings staged for the next reboot, as last read
        self._needs_etag = False    # set once the BMC refuses a PATCH without If-Match (Supermicro)
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

    def _members(self, collection_uri):
        return [member['@odata.id'] for member in self.redfish.get(collection_uri).dict.get('Members', [])]

    def _only_member(self, collection_uri, what):
        members = self._members(collection_uri)
        if len(members) != 1:
            raise Exception(f"{self.name} has {len(members)} {what}s; bios_tool works with a BMC that has exactly one")
        return members[0]

    def _discover(self):
        root = self.redfish.root
        self.vendor = next(iter((root.get("Oem") or {}).keys()), None) or root.get("Vendor")

        self.systems_members_uri = self._only_member(root['Systems']['@odata.id'], "system")
        system = self.redfish.get(self.systems_members_uri).dict
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
        for member in self._members(processors) if processors else []:
            self.arch = cpu_arch(self.redfish.get(member).dict)
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

        managers = self._members(root['Managers']['@odata.id']) if 'Managers' in root else []
        self.managers_members_uri = managers[0] if managers else None
        self.bmc_firmware_version = None
        if self.managers_members_uri:
            self.bmc_firmware_version = self.redfish.get(self.managers_members_uri).dict.get('FirmwareVersion')

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


    def change_settings(self, settings_dict):
        """Stages settings_dict for the next reboot, and confirms the BMC staged every one of them."""
        if self.bios_settings_uri is None:
            log.error(f"{self.name} does not say where to stage BIOS changes, so they cannot be made")
            return False
        on_reset = "OnReset" in (self.supported_apply_times or [])

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
            refused = [key for key, value in settings_dict.items()
                       if not ok(self._patch_settings({key: value}, on_reset))]
        elif not ok(resp):
            messages = [info.get('Message', '') for info in
                        resp.dict.get('error', {}).get('@Message.ExtendedInfo', [])]
            log.error(f"{self.name} refused the BIOS changes (HTTP {resp.status}): {' '.join(messages)}")
            return False
        if refused:
            log.error(f"{self.name} refused {', '.join(f'{key}={settings_dict[key]}' for key in refused)}")
        if len(refused) == len(settings_dict):
            return False
        if not on_reset and self.is_dell() and not self._create_dell_bios_job():
            return False

        staged = self.staged_settings(refresh=True)
        if not staged:
            log.warning(f"{self.name} accepted the BIOS changes but does not show what it staged, so they could not "
                        f"be confirmed")
            return not refused
        not_staged = [f"{key}={value}" for key, value in settings_dict.items()
                      if key not in refused and not same(staged.get(key), value)]
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
        resp = self._patch(body)
        if resp.status in (412, 428) and not self._needs_etag:
            self._needs_etag = True
            resp = self._patch(body)
        return resp

    def _patch(self, body):
        headers = None
        if self._needs_etag:
            resp = self._settings_object()
            etag = resp and (resp.dict.get("@odata.etag") or resp.getheader("ETag"))
            headers = {"If-Match": etag} if etag else None
        return self.redfish.patch(self.bios_settings_uri, body=body, headers=headers, timeout=WRITE_TIMEOUT)

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
        differ = {key: value for key, value in settings.items() if not same(current[key], value)}
        staged = self.staged_settings() if differ else {}
        to_change, waiting = dict(), dict()
        for key, value in differ.items():
            if key in staged and same(staged[key], value):
                log.info(f"{self.name}: BIOS setting {key} is {current[key]}, and {value} is waiting for a reboot")
                waiting[key] = value
            else:
                log.info(f"{self.name}: BIOS setting {key} is {current[key]}, but should be {value}")
                to_change[key] = value
        return to_change, waiting

    def _settings_object(self):
        """The response for the settings object, or None if it cannot be read."""
        if self.bios_settings_uri is None:
            return None
        try:
            resp = self.redfish.get(self.bios_settings_uri)
        except Exception as exc:
            log.warning(f"Could not read the BIOS changes staged on {self.name}: {exc}")
            return None
        return resp if resp.status == 200 else None

    def staged_settings(self, refresh=False):
        """The BIOS settings staged on the BMC for the next reboot, or {} if it shows none."""
        if refresh or self._staged is None:
            resp = self._settings_object()
            self._staged = resp.dict.get('Attributes', {}) if resp else {}
        return self._staged

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
        if not ok(resp):
            log.error(f"{self.name} refused to reset its BIOS to defaults (HTTP {resp.status}) at {self.reset_bios_uri}")
            return False
        return True

    def print_settings(self):
        print(f"{self.name} Current BIOS settings:")
        print(json.dumps(self.bios_data.obj.Attributes, indent=4, sort_keys=True))

    def reboot(self):
        if self.reset_target is None:
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
            resp = self.redfish.post(self.reset_target, body={'ResetType': reset_type}, timeout=WRITE_TIMEOUT)
        except Exception as exc:
            log.error(f"{self.name} could not be asked to reboot: {exc}")
            return False
        if not ok(resp):
            log.error(f"{self.name} refused to reboot ({reset_type}): HTTP {resp.status}")
            return False
        log.info(f"{self.name} accepted a {reset_type}")
        return True
