import yaml

from bios_tool import shareable
from fake_bmc import dell, make_bmc


def test_shareable_drops_what_identifies_a_machine():
    settings = {"SystemServiceTag": "ABC1234", "SerialNumber": "X", "SHA256SetupPassword": "F00D", "LogicalProc":
                "Enabled", "PxeDev1Mac": "aa:bb:cc:dd:ee:ff", "NvidiaNetworkAdapter_A088C2CA98A0__Slot3_Speed": "Auto",
                "SMTControl_0037": "Enabled", "StrongPassword": "Disabled",
                "NvmeofHostNqn": "nqn.1988-11.com.dell:PowerEdge.R6615.ABC1234"}
    assert shareable(settings) == {"LogicalProc": "Enabled", "SMTControl_0037": "Enabled", "StrongPassword": "Disabled"}


def test_save_defaults_keeps_no_identifiers(tool):
    tool.add("10.0.0.1", make_bmc(dell(SystemServiceTag="ABC1234", AssetTag="rack 4")))
    tool.hosts([("10.0.0.1", "admin", "secret")])
    assert tool.run("--save-defaults") == 0
    saved = yaml.safe_load((tool.dir / "defaults-db.yml").read_text())["Dell Inc."]["AMD"]["PowerEdge R6615"]
    assert "SystemServiceTag" not in saved and "AssetTag" not in saved and saved["LogicalProc"] == "Enabled"


def test_bmc_ips_take_the_password_from_the_environment(tool, monkeypatch):
    tool.add("10.0.0.1", make_bmc(dell(LogicalProc="Disabled")))
    tool.settings({"Dell Inc.": {"AMD": {"PowerEdge R6615": {"LogicalProc": "Disabled"}}}})
    monkeypatch.setenv("BIOS_TOOL_BMC_PASSWORD", "secret")
    assert tool.run("--bmc-ips", "10.0.0.1", "--bmc-username", "admin") == 0


def test_bmc_ips_without_a_password_is_an_error(tool, monkeypatch):
    monkeypatch.delenv("BIOS_TOOL_BMC_PASSWORD", raising=False)
    assert tool.run("--bmc-ips", "10.0.0.1", "--bmc-username", "admin") == 1
