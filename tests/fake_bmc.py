"""A fake Redfish BMC, so bios_tool can be tested without hardware.

Each FakeBMC holds the Redfish documents of one server, keyed by URI, and records every PATCH and POST it receives.
The profiles below are synthetic: they follow the shape each vendor's BMC returns, not any real machine's values.
"""
import copy
import redfish
from redfish.rest.v1 import RisObject, StaticRestResponse

ROOT = "/redfish/v1"


def response(status, body=None):
    return StaticRestResponse(Status=status, Content=body if body is not None else {}, Headers={})


class FakeBMC:
    def __init__(self, docs, username="admin", password="secret"):
        self.docs = docs
        self.username = username
        self.password = password
        self.patches = []       # (uri, body)
        self.posts = []         # (uri, body)
        self.logged_in = False
        self.logged_out = False
        self.patch_status = 200
        self.post_status = 200
        self.not_staged = set()     # settings the BMC accepts in a PATCH but silently drops
        self.patch_hook = None      # (uri, body, headers) -> an HTTP status that overrides patch_status, or None
        self.headers = []           # the headers of each PATCH

    def system(self):
        return self.docs[self.docs[self.docs[ROOT]["Systems"]["@odata.id"]]["Members"][0]["@odata.id"]]

    def bios(self):
        return self.docs[self.system()["Bios"]["@odata.id"]]

    def pending(self):
        return self.docs[self.bios()["@Redfish.Settings"]["SettingsObject"]["@odata.id"]]["Attributes"]

    def posts_to(self, action):
        return [body for uri, body in self.posts if uri.endswith(action)]

    def resets(self):
        return [body.get("ResetType") for body in self.posts_to("ComputerSystem.Reset")]

    def get(self, uri):
        uri = uri.rstrip("/") or ROOT
        if uri not in self.docs:
            return response(404, {"error": {"code": "Base.1.0.ResourceMissingAtURI",
                                                "@Message.ExtendedInfo": [{"Message": f"{uri} not found"}]}})
        return response(200, copy.deepcopy(self.docs[uri]))

    def patch(self, uri, body, headers=None):
        if self.patch_status is None:
            raise ConnectionError("the BMC stopped answering")
        self.patches.append((uri, copy.deepcopy(body)))
        self.headers.append(headers or {})
        status = self.patch_status
        if self.patch_hook is not None:
            status = self.patch_hook(uri, body, headers or {}) or status
        if status >= 300:
            return response(status)
        if uri in self.docs:
            kept = {key: value for key, value in body.get("Attributes", {}).items() if key not in self.not_staged}
            self.docs[uri].setdefault("Attributes", {}).update(kept)
        return response(status)

    def post(self, uri, body):
        self.posts.append((uri, copy.deepcopy(body)))
        return response(self.post_status)


class FakeClient:
    """Stands in for redfish.rest.v1.HttpClient, as returned by redfish.redfish_client."""

    def __init__(self, bmc, username, password):
        self.bmc = bmc
        self.username = username
        self.password = password
        self._timeout = 10

    @property
    def root(self):
        return RisObject.parse(copy.deepcopy(self.bmc.docs[ROOT]))

    def login(self, auth="session"):
        if (self.username, self.password) != (self.bmc.username, self.bmc.password):
            raise redfish.rest.v1.InvalidCredentialsError(401)
        self.bmc.logged_in = True

    def logout(self):
        self.bmc.logged_out = True

    def get(self, uri, *args, **kwargs):
        return self.bmc.get(uri)

    def patch(self, uri, body=None, headers=None, **kwargs):
        return self.bmc.patch(uri, body or {}, headers)

    def post(self, uri, body=None, *args, **kwargs):
        return self.bmc.post(uri, body or {})


def _server(system_id, manufacturer, model, cpu, attributes, settings_object, apply_times=None,
            reset_types=None, oem="Dell", firmware="1.00"):
    system = f"{ROOT}/Systems/{system_id}"
    manager = f"{ROOT}/Managers/1"
    reset = {"target": f"{system}/Actions/ComputerSystem.Reset"}
    docs = {
        ROOT: {"Oem": {oem: {}}, "Systems": {"@odata.id": f"{ROOT}/Systems"},
               "Managers": {"@odata.id": f"{ROOT}/Managers"}},
        f"{ROOT}/Systems": {"Members": [{"@odata.id": system}]},
        system: {"Manufacturer": manufacturer, "Model": model, "BiosVersion": "1.0.0", "PowerState": "On",
                 "Actions": {"#ComputerSystem.Reset": reset},
                 "Processors": {"@odata.id": f"{system}/Processors"},
                 "Bios": {"@odata.id": f"{system}/Bios"}},
        f"{system}/Processors": {"Members": [{"@odata.id": f"{system}/Processors/CPU1"}]},
        f"{system}/Processors/CPU1": cpu,
        f"{system}/Bios": {"Attributes": dict(attributes),
                           "Actions": {"#Bios.ResetBios": {"target": f"{system}/Bios/Actions/Bios.ResetBios"}},
                           "@Redfish.Settings": {"SettingsObject": {"@odata.id": f"{system}/Bios/{settings_object}"}}},
        f"{system}/Bios/{settings_object}": {"Attributes": {}},
        f"{ROOT}/Managers": {"Members": [{"@odata.id": manager}]},
        manager: {"FirmwareVersion": firmware, "Actions": {}},
    }
    if apply_times is not None:
        docs[f"{system}/Bios"]["@Redfish.Settings"]["SupportedApplyTimes"] = apply_times
    if reset_types is None:
        info = f"{system}/ResetActionInfo"
        reset["@Redfish.ActionInfo"] = info
        docs[info] = {"Parameters": [{"Name": "ResetType",
                                      "AllowableValues": ["On", "ForceOff", "GracefulRestart", "ForceRestart"]}]}
    else:
        reset["ResetType@Redfish.AllowableValues"] = reset_types
    return docs


AMD_CPU = {"Model": "AMD EPYC 9454P 48-Core Processor", "ProcessorArchitecture": "x86",
           "InstructionSet": "x86-64", "ProcessorId": {"VendorId": "AuthenticAMD"}}
INTEL_CPU = {"Model": "Intel(R) Xeon(R) Gold 6530", "ProcessorArchitecture": "x86",
             "InstructionSet": "x86-64", "ProcessorId": {"VendorId": "GenuineIntel"}}
ARM_CPU = {"Model": "Ampere(R) Altra(R) Max Processor", "ProcessorArchitecture": "ARM",
           "InstructionSet": "ARM-A64", "ProcessorId": {"VendorId": "Ampere(R)"}}


def dell(model="PowerEdge R6615", cpu=AMD_CPU, **attributes):
    attrs = {"LogicalProc": "Enabled", "ProcVirtualization": "Enabled", "BootMode": "Uefi",
             "SecureBoot": "Disabled", "SysProfile": "PerfOptimized"}
    attrs.update(attributes)
    return _server("System.Embedded.1", "Dell Inc.", model, cpu, attrs, "Settings",
                   apply_times=["OnReset", "Immediate"],
                   reset_types=["On", "ForceOff", "GracefulRestart", "ForceRestart"], oem="Dell")


def supermicro(model="AS -1115CS-TNR", cpu=AMD_CPU, **attributes):
    attrs = {"SMTControl_0037": "Enabled", "IOMMU_0038": "Auto", "ConsoleRedirection_00A5": "Disabled"}
    attrs.update(attributes)
    return _server("1", "Supermicro", model, cpu, attrs, "SD", oem="Supermicro")
