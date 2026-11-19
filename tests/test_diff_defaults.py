import yaml

from fake_bmc import INTEL_CPU, dell

DEFAULTS = {"Dell Inc.": {"AMD": {"PowerEdge R6615": {"LogicalProc": "Enabled", "BootMode": "Uefi"}}}}


def test_every_server_is_compared_and_one_without_defaults_fails_the_run(tool, capsys):
    tool.servers(None, dell(model="PowerEdge R670", cpu=INTEL_CPU), dell(LogicalProc="Disabled"))
    (tool.dir / "defaults-db.yml").write_text(yaml.safe_dump(DEFAULTS))

    assert tool.run("--diff-defaults") == 1

    assert "10.0.0.1 is skipped: there are no default settings for Dell Inc./Intel/PowerEdge R670" in tool.log
    assert "LogicalProc: Disabled" in capsys.readouterr().out


def test_no_database_is_an_error_not_a_promise_to_create_one(tool):
    tool.servers(None, dell())
    assert tool.run("--diff-defaults") == 1
    assert "record one with --save-defaults" in tool.log
