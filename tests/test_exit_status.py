import pytest

import RedFishBMC
from fake_bmc import INTEL_CPU, dell, make_bmc

SETTINGS = {"Dell Inc.": {"AMD": {"PowerEdge R6615": {"LogicalProc": "Disabled"}}}}


def hosts(tool, *names):
    tool.settings(SETTINGS)
    tool.hosts([(name, "admin", "secret") for name in names])


def test_an_unreachable_server_is_named_and_fails_the_run(tool):
    tool.add("10.0.0.1", make_bmc(dell(LogicalProc="Disabled")))
    hosts(tool, "10.0.0.1", "10.0.0.9")
    assert tool.run() == 1
    assert "1 of 2 servers could not be reached, so nothing was done to them: 10.0.0.9" in tool.log


def test_wrong_credentials_fail_the_run(tool):
    tool.add("10.0.0.1", make_bmc(dell(), password="other"))
    hosts(tool, "10.0.0.1")
    assert tool.run() == 1
    assert "Invalid credentials for 10.0.0.1" in tool.log


def test_a_rejected_change_fails_the_run(tool):
    bmc = tool.add("10.0.0.1", make_bmc(dell()))
    bmc.patch_status = 500
    hosts(tool, "10.0.0.1")
    assert tool.run("--fix") == 1
    assert "Unable to fix 10.0.0.1" in tool.log


def test_a_clean_check_succeeds(tool):
    tool.add("10.0.0.1", make_bmc(dell(LogicalProc="Disabled")))
    hosts(tool, "10.0.0.1")
    assert tool.run() == 0


def test_diff_of_servers_that_cannot_be_compared_fails(tool):
    tool.add("10.0.0.1", make_bmc(dell()))
    tool.add("10.0.0.2", make_bmc(dell(model="PowerEdge R670", cpu=INTEL_CPU)))
    hosts(tool, "10.0.0.1", "10.0.0.2")
    assert tool.run("--diff", "10.0.0.1", "10.0.0.2") == 1


def test_sessions_are_closed_even_when_something_goes_wrong(tool, monkeypatch):
    bmc = tool.add("10.0.0.1", make_bmc(dell()))
    hosts(tool, "10.0.0.1")

    def broken(self, settings):
        raise RuntimeError("boom")

    monkeypatch.setattr(RedFishBMC.RedFishBMC, "check_settings", broken)
    with pytest.raises(RuntimeError):
        tool.run()
    assert bmc.logged_out
