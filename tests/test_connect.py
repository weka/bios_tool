import RedFishBMC
from fake_bmc import FakeClient, dell, make_bmc, supermicro

SMC = "/redfish/v1/Systems/1"
SETTINGS = {"Supermicro": {"AMD": {"AS -1115CS-TNR": {"SMTControl": "Disabled"}},
                           "ARM": {"*": {"SMTControl": "Disabled"}}}}


def one(tool, docs):
    bmc = tool.add("10.0.0.1", make_bmc(docs))
    tool.settings(SETTINGS)
    tool.hosts([("10.0.0.1", "admin", "secret")])
    return bmc


def test_a_bmc_that_does_not_name_its_settings_object_uses_the_vendor_one(tool):
    docs = supermicro()
    del docs[f"{SMC}/Bios"]["@Redfish.Settings"]
    bmc = one(tool, docs)
    assert tool.run("--fix") == 0
    assert bmc.patches[0][0] == f"{SMC}/Bios/SD"


def test_no_settings_object_at_all_is_an_error_not_a_crash(tool):
    docs = supermicro()
    del docs[f"{SMC}/Bios"]["@Redfish.Settings"]
    del docs[f"{SMC}/Bios/SD"]
    bmc = one(tool, docs)
    assert tool.run("--fix") == 1
    assert "does not say where to stage BIOS changes, so they cannot be made" in tool.log
    assert bmc.patches == []


def test_missing_optional_properties_do_not_stop_a_check(tool):
    docs = supermicro()
    del docs[f"{SMC}/Bios"]["Actions"]
    del docs["/redfish/v1/Managers/1"]["FirmwareVersion"]
    del docs[SMC]["Actions"]
    one(tool, docs)
    assert tool.run() == 0
    assert tool.run("--reset-bios", "--yes") == 1
    assert "does not offer a BIOS reset to defaults" in tool.log


def test_a_bmc_with_two_systems_is_refused_and_logged_out(tool):
    docs = supermicro()
    docs["/redfish/v1/Systems"]["Members"].append({"@odata.id": "/redfish/v1/Systems/2"})
    bmc = one(tool, docs)
    assert tool.run() == 1
    assert "has 2 systems; bios_tool works with a BMC that has exactly one" in tool.log
    assert bmc.logged_in and bmc.logged_out


def test_a_bios_error_after_login_logs_out(tool):
    docs = supermicro()
    del docs[f"{SMC}/Bios"]
    bmc = one(tool, docs)
    assert tool.run() == 1
    assert bmc.logged_out


def test_reads_have_a_finite_timeout(monkeypatch):
    bmc = make_bmc(dell())
    client = FakeClient(bmc, "admin", "secret")
    monkeypatch.setattr(RedFishBMC.redfish, "redfish_client", lambda **kwargs: client)
    RedFishBMC.RedFishBMC("10.0.0.1", username="admin", password="secret")
    assert client._timeout == RedFishBMC.READ_TIMEOUT
