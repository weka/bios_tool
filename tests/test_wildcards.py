from fake_bmc import dell, make_bmc

SETTINGS = {"Dell Inc.": {"AMD": {
    "*": {"LogicalProc": "Disabled", "ProcVirtualization": "Disabled"},
    "PowerEdge R6615": {"ProcVirtualization": "Enabled", "SysProfile": "Custom"},
}}}


def check(tool, model):
    bmc = tool.add("10.0.0.1", make_bmc(dell(model=model, ProcVirtualization="Unset", SysProfile="Unset")))
    tool.settings(SETTINGS)
    tool.hosts([("10.0.0.1", "admin", "secret")])
    tool.run("--fix")
    return bmc.patches[0][1]["Attributes"]


def test_a_model_gets_the_wildcard_settings_with_its_own_laid_over_them(tool):
    assert check(tool, "PowerEdge R6615") == {
        "LogicalProc": "Disabled", "ProcVirtualization": "Enabled", "SysProfile": "Custom"}


def test_an_unlisted_model_gets_the_wildcard_settings(tool):
    assert check(tool, "PowerEdge R7615") == {"LogicalProc": "Disabled", "ProcVirtualization": "Disabled"}
