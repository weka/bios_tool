from fake_bmc import dell

SETTINGS = {"Dell Inc.": {"AMD": {"PowerEdge R6615": {"LogicalProc": "Disabled"}}}}


def two(tool):
    return tool.servers(SETTINGS, dell(), dell())


def resets_bios(bmc):
    return bmc.posts_to("Bios.ResetBios")


def test_without_a_terminal_or_yes_no_bmc_is_contacted(tool):
    a, b = two(tool)
    assert tool.run("--reset-bios", "--reboot") == 1
    assert not a.logged_in and not b.logged_in
    assert "run with --yes" in tool.log


def test_reset_and_reboot(tool):
    a, b = two(tool)
    assert tool.run("--reset-bios", "--reboot", "--yes") == 0
    assert len(resets_bios(a)) == len(resets_bios(b)) == 1
    assert a.resets() == b.resets() == ["GracefulRestart"]


def test_a_failed_reset_is_an_error_and_that_server_is_not_rebooted(tool):
    a, b = two(tool)
    a.post_status = 500
    assert tool.run("--reset-bios", "--reboot", "--yes") == 1
    assert a.resets() == [] and b.resets() == ["GracefulRestart"]
    assert "10.0.0.1's BIOS will be reset" not in tool.log
