from fake_bmc import dell, make_bmc

SETTINGS = {"Dell Inc.": {"AMD": {"PowerEdge R6615": {"LogicalProc": "Disabled"}}}}


def two(tool):
    a = tool.add("10.0.0.1", make_bmc(dell()))
    b = tool.add("10.0.0.2", make_bmc(dell()))
    tool.settings(SETTINGS)
    tool.hosts([("10.0.0.1", "admin", "secret"), ("10.0.0.2", "admin", "secret")])
    return a, b


def resets_bios(bmc):
    return [uri for uri, body in bmc.posts if uri.endswith("Bios.ResetBios")]


def test_nothing_is_reset_without_an_answer(tool):
    a, b = two(tool)
    assert tool.run("--reset-bios", "--reboot") == 1
    assert a.posts == b.posts == []
    assert "Reset the BIOS of 2 servers to factory defaults and reboot them" in tool.log


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
