"""Tests for the findings of the automated reviews of PR #31."""
import logging

import pytest

from fake_bmc import FakeBMC, dell

SETTINGS = {"Dell Inc.": {"AMD": {"PowerEdge R6615": {"LogicalProc": "Disabled"}}}}
SECRET = "s3cr3t-Value!"
DELL_BIOS = "/redfish/v1/Systems/System.Embedded.1/Bios"


# CodeQL: "clear-text logging of sensitive information" at the --bmc-ips error. The line logs the name of the
# variable that holds the password, never a password.
@pytest.mark.parametrize("args, env", [
    (["--bmc-ips", "10.0.0.1", "--bmc-password", SECRET], None),        # no --bmc-username
    (["--bmc-ips", "10.0.0.1"], SECRET),                                 # password from the environment
    (["--bmc-ips", "10.0.0.1", "--bmc-username", "admin", "--bmc-password", SECRET], None),
    (["--bmc-ips", "10.0.0.1", "--bmc-username", "admin"], SECRET),
])
def test_no_password_is_ever_logged(tool, monkeypatch, args, env):
    tool.servers(SETTINGS, FakeBMC(dell(), password=SECRET))
    monkeypatch.delenv("BIOS_TOOL_BMC_PASSWORD", raising=False)
    if env:
        monkeypatch.setenv("BIOS_TOOL_BMC_PASSWORD", env)
    tool.caplog.set_level(logging.DEBUG)
    tool.run(*args)
    assert SECRET not in tool.log


def test_the_bmc_ips_error_names_the_variable_not_its_value(tool, monkeypatch):
    monkeypatch.setenv("BIOS_TOOL_BMC_PASSWORD", SECRET)
    assert tool.run("--bmc-ips", "10.0.0.1") == 1
    assert "$BIOS_TOOL_BMC_PASSWORD" in tool.log and SECRET not in tool.log


# Bugbot: "--save-defaults ignores failure exit status".
def test_save_defaults_fails_when_the_database_cannot_be_read(tool):
    tool.servers(None, dell())
    (tool.dir / "defaults-db.yml").write_text("Dell Inc.: [\n")
    assert tool.run("--save-defaults") == 1


# Bugbot: "staged Dell settings skip job retry".
def test_a_dell_job_that_failed_is_created_on_the_next_fix(tool):
    docs = dell()
    del docs[DELL_BIOS]["@Redfish.Settings"]["SupportedApplyTimes"]
    [bmc] = tool.servers(SETTINGS, docs)
    bmc.post_status = 500                       # the first run's job POST fails
    assert tool.run("--fix") == 1
    assert bmc.pending() == {"LogicalProc": "Disabled"}     # staged, with no job to apply it

    bmc.post_status = 200
    bmc.posts.clear()
    assert tool.run("--fix") == 0
    assert bmc.posts_to("/Jobs") == [{"TargetSettingsURI": f"{DELL_BIOS}/Settings"}]


def test_a_dell_job_already_waiting_is_not_created_twice(tool):
    [bmc] = tool.servers(SETTINGS, dell())
    bmc.pending()["LogicalProc"] = "Disabled"
    bmc.docs["/redfish/v1/Managers/1/Jobs"] = {"Members": [{"@odata.id": "/redfish/v1/Managers/1/Jobs/JID_1"}]}
    bmc.docs["/redfish/v1/Managers/1/Jobs/JID_1"] = {"JobType": "BIOSConfiguration", "JobState": "Scheduled"}
    assert tool.run("--fix") == 0
    assert bmc.posts == []


def test_staged_settings_on_other_vendors_need_no_job(tool):
    from fake_bmc import supermicro
    [bmc] = tool.servers({"Supermicro": {"AMD": {"AS -1115CS-TNR": {"SMTControl": "Disabled"}}}}, supermicro())
    bmc.pending()["SMTControl_0037"] = "Disabled"
    assert tool.run("--fix") == 0
    assert bmc.posts == []
