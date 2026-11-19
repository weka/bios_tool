from fake_bmc import dell

SETTINGS = {"Dell Inc.": {"AMD": {"PowerEdge R6615": {
    "LogicalProc": "Disabled", "NumaNodesPerSocket": "1", "SecureBoot": "Disabled", "ProcVirtualization": "Disabled"}}}}


def one(tool, **attributes):
    [bmc] = tool.servers(SETTINGS, dell(**attributes))
    return bmc


def test_only_settings_that_differ_are_written_and_values_compare_as_text(tool):
    bmc = one(tool, NumaNodesPerSocket=1)      # the BMC's 1 is the file's "1"
    assert tool.run("--fix") == 0
    assert bmc.patches[0][1]["Attributes"] == {"LogicalProc": "Disabled", "ProcVirtualization": "Disabled"}


def test_settings_already_staged_are_not_written_again(tool):
    bmc = one(tool, NumaNodesPerSocket="1")
    bmc.pending().update({"LogicalProc": "Disabled", "ProcVirtualization": "Disabled"})
    assert tool.run("--fix") == 0
    assert bmc.patches == []
    assert "2 changes on 10.0.0.1 are staged and wait for a reboot" in tool.log


def test_a_change_the_bmc_accepts_but_does_not_stage_is_an_error(tool):
    bmc = one(tool, NumaNodesPerSocket="1")
    bmc.not_staged = {"ProcVirtualization"}
    assert tool.run("--fix") == 1
    assert "accepted the BIOS changes but did not stage ProcVirtualization=Disabled" in tool.log


def test_a_refusal_is_logged_with_the_bmc_message(tool):
    bmc = one(tool, NumaNodesPerSocket="1")
    bmc.patch_status = 400
    assert tool.run("--fix") == 1
    assert "refused the BIOS changes (HTTP 400)" in tool.log
