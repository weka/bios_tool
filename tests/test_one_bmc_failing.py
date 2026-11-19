from fake_bmc import dell

SETTINGS = {"Dell Inc.": {"AMD": {"PowerEdge R6615": {"LogicalProc": "Disabled"}}}}


def test_a_bmc_failing_mid_run_does_not_stop_the_others(tool):
    broken, fine = tool.servers(SETTINGS, dell(), dell())
    broken.patch_status = None      # the connection drops on the PATCH

    assert tool.run("--fix", "--reboot", "--yes") == 1

    assert "10.0.0.1 failed: the BMC stopped answering" in tool.log
    assert fine.patches and fine.resets() == ["GracefulRestart"]
    assert broken.resets() == []
    assert broken.logged_out and fine.logged_out


def test_a_powered_off_server_is_powered_on_and_the_state_is_read_fresh(tool):
    [bmc] = tool.servers(SETTINGS, dell())
    bmc.system()["PowerState"] = "Off"
    assert tool.run("--fix", "--reboot", "--yes") == 0
    assert bmc.resets() == ["On"]
    assert "reset status" not in tool.log
