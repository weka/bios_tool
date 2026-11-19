import pytest

import bios_tool
from fake_bmc import FakeBMC, INTEL_CPU, dell

SETTINGS = {"Dell Inc.": {"AMD": {"PowerEdge R6615": {"LogicalProc": "Disabled"}}}}


def test_an_unreachable_server_is_named_and_fails_the_run(tool):
    tool.servers(SETTINGS, dell(LogicalProc="Disabled"))
    tool.hosts([("10.0.0.1", "admin", "secret"), ("10.0.0.9", "admin", "secret")])
    assert tool.run() == 1
    assert "1 of 2 servers could not be reached, so nothing was done to them: 10.0.0.9" in tool.log


def test_wrong_credentials_fail_the_run(tool):
    tool.servers(SETTINGS, FakeBMC(dell(), password="other"))
    assert tool.run() == 1
    assert "Invalid credentials for 10.0.0.1" in tool.log


def test_a_rejected_change_fails_the_run(tool):
    [bmc] = tool.servers(SETTINGS, dell())
    bmc.patch_status = 500
    assert tool.run("--fix") == 1
    assert "10.0.0.1 refused the BIOS changes (HTTP 500)" in tool.log


def test_a_clean_check_succeeds(tool):
    tool.servers(SETTINGS, dell(LogicalProc="Disabled"))
    assert tool.run() == 0


def test_diff_of_servers_that_cannot_be_compared_fails(tool):
    tool.servers(SETTINGS, dell(), dell(model="PowerEdge R670", cpu=INTEL_CPU))
    assert tool.run("--diff", "10.0.0.1", "10.0.0.2") == 1


def test_sessions_are_closed_even_when_something_goes_wrong(tool, monkeypatch):
    [bmc] = tool.servers(SETTINGS, dell())

    def broken(server, all_bios_settings):
        raise RuntimeError("boom")

    monkeypatch.setattr(bios_tool, "find_bios_settings", broken)
    with pytest.raises(RuntimeError):
        tool.run()
    assert bmc.logged_out
