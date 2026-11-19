from fake_bmc import dell

SETTINGS = {"Dell Inc.": {"AMD": {"PowerEdge R6615": {"LogicalProc": "Disabled", "BootMode": "Uefi"}}}}


def test_check_reports_a_drifted_setting_and_changes_nothing(tool):
    [bmc] = tool.servers(SETTINGS, dell())

    tool.run()

    assert "BIOS setting LogicalProc is Enabled, but should be Disabled" in tool.log
    assert "1 changes are needed on 10.0.0.1" in tool.log
    assert bmc.patches == [] and bmc.posts == []
    assert bmc.logged_out


def test_fix_writes_the_settings_object(tool):
    [bmc] = tool.servers(SETTINGS, dell())

    tool.run("--fix")

    uri, body = bmc.patches[0]
    assert uri.endswith("/Bios/Settings")
    assert body["Attributes"]["LogicalProc"] == "Disabled"
    assert body["@Redfish.SettingsApplyTime"] == {"ApplyTime": "OnReset"}
