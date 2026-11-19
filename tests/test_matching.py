import pytest

from bios_tool import match_setting
from fake_bmc import AMD_CPU, supermicro

SMC = ["SMTControl_0040", "Hyper_Threading_ALL_", "SR_IOVSupport", "ConsoleRedirection_00A5",
       "ConsoleRedirection_00A7", "Processors_SVMMode", "Processors_P_state2"]


@pytest.mark.parametrize("name, key, candidates", [
    ("SR_IOVSupport", "SR_IOVSupport", []),
    ("SMTControl_0037", "SMTControl_0040", []),          # a Supermicro BIOS update renumbered it
    ("SMTControl", "SMTControl_0040", []),
    ("Hyper-Threading[ALL]", "Hyper_Threading_ALL_", []),  # SUM's spelling of the Redfish name
    ("SR-IOVSupport", "SR_IOVSupport", []),
    # never a guess: two ports, or a different knob with a similar name
    ("ConsoleRedirection", None, ["ConsoleRedirection_00A5", "ConsoleRedirection_00A7"]),
    ("Processors_SMTMode", None, []),
    ("Processors_P_state1", None, []),
])
def test_match_setting(name, key, candidates):
    assert match_setting(name, SMC) == (key, candidates)


def test_unmatched_settings_are_reported_not_written_and_fail_the_run(tool):
    [bmc] = tool.servers({"Supermicro": {"AMD": {"AS -1115CS-TNR": {
        "SMTControl": "Disabled", "SMTControlMode": "Off", "ConsoleRedirectionX": "Enabled"}}}},
        supermicro(cpu=AMD_CPU, SMTControl_0037="Enabled"))

    assert tool.run("--fix") == 1

    assert bmc.patches[0][1]["Attributes"] == {"SMTControl_0037": "Disabled"}
    assert "SMTControlMode is not in this server's BIOS" in tool.log
    assert "(the closest are SMTControl_0037" in tool.log
    assert "2 settings from bios_settings.yml are not in their server's BIOS" in tool.log
