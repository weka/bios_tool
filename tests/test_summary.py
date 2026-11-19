from fake_bmc import dell, make_bmc, supermicro

SETTINGS = {"Dell Inc.": {"AMD": {"PowerEdge R6615": {"LogicalProc": "Disabled", "NoSuchSetting": "On"}}}}


def test_the_summary_says_what_happened_to_each_server(tool, capsys):
    tool.add("10.0.0.1", make_bmc(dell()))
    clean = tool.add("10.0.0.2", make_bmc(dell(LogicalProc="Disabled")))
    tool.settings(SETTINGS)
    tool.hosts([("10.0.0.1", "admin", "secret"), ("10.0.0.2", "admin", "secret")])

    assert tool.run("--fix", "--reboot", "--yes") == 1

    out = capsys.readouterr().out
    assert "10.0.0.1  Dell Inc./AMD/PowerEdge R6615  1 settings not in its BIOS; 1 settings changed; rebooted" in out
    assert "10.0.0.2  Dell Inc./AMD/PowerEdge R6615  1 settings not in its BIOS; as wanted" in out
    assert clean.resets() == []


def test_the_summary_names_unknown_servers_when_nothing_is_changed(tool, capsys):
    tool.add("10.0.0.1", make_bmc(dell()))
    tool.add("10.0.0.2", make_bmc(supermicro()))
    tool.settings(SETTINGS)
    tool.hosts([("10.0.0.1", "admin", "secret"), ("10.0.0.2", "admin", "secret")])

    assert tool.run("--fix") == 1

    assert "Supermicro/AMD/AS -1115CS-TNR  not in bios_settings.yml" in capsys.readouterr().out
