import pytest

from fake_bmc import AMD_CPU, dell, make_bmc, supermicro

SETTINGS = {"Dell Inc.": {"AMD": {"PowerEdge R6615": {"LogicalProc": "Disabled"}}}}


def two_hosts(tool, unknown_docs):
    known = tool.add("10.0.0.1", make_bmc(dell()))
    unknown = tool.add("10.0.0.2", make_bmc(unknown_docs))
    tool.settings(SETTINGS)
    tool.hosts([("10.0.0.1", "admin", "secret"), ("10.0.0.2", "admin", "secret")])
    return known, unknown


@pytest.mark.parametrize("docs, missing", [
    (supermicro(), "no 'Supermicro' manufacturer"),
    (dell(cpu={"Model": "Intel(R) Xeon(R) Gold 6530"}), "no 'Intel' architecture under 'Dell Inc.'"),
    (dell(model="PowerEdge R7615"), "no 'PowerEdge R7615' model, and no '*', under 'Dell Inc./AMD'"),
])
@pytest.mark.parametrize("options", [["--fix"], ["--reboot"], ["--fix", "--reboot"]])
def test_an_unknown_server_stops_any_change_before_the_first_write(tool, docs, missing, options):
    known, unknown = two_hosts(tool, docs)

    assert tool.run(*options) == 1

    assert missing in tool.log
    assert "No server was changed" in tool.log
    assert known.patches == known.posts == unknown.patches == unknown.posts == []
    assert known.logged_out and unknown.logged_out


def test_a_check_reports_the_known_servers_and_fails(tool):
    known, unknown = two_hosts(tool, supermicro(cpu=AMD_CPU))

    assert tool.run() == 1

    assert "1 changes are needed on 10.0.0.1" in tool.log
    assert "No changes are needed on 10.0.0.2" not in tool.log
    assert "1 servers are not in bios_settings.yml and were not checked" in tool.log
