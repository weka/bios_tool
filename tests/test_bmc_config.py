import pytest

import BMCsetup
import bios_tool


@pytest.mark.parametrize("output, user, user_id", [
    ("1. USERID Read/Write\n2. ADMIN2 Read/Write\n3. ADMIN Read/Write\n", "ADMIN", "3"),
    ("1 USERID Read/Write\n2 ADMIN2 Read/Write\n", "ADMIN", None),
    ("system> users\n1. USERID Read/Write\n", "USERID", "1"),
    # user names may hold dots; only the dot after the account number is punctuation
    ("1. USERID Read/Write\n2. svc.admin Read/Write\n", "svc.admin", "2"),
    ("1. a.b.c Read/Write\n", "a.b.c", "1"),
    ("1. svc.admin Read/Write\n", "admin", None),
    ("1. svc.admin Read/Write\n", "svc", None),
    ("12 svc.admin Read/Write\n", "svc.admin", "12"),
])
def test_lenovo_user_id_matches_the_whole_name(output, user, user_id):
    assert BMCsetup.lenovo_user_id(output, user) == user_id


def test_hpe_output_with_an_equals_sign_in_a_value():
    parsed = BMCsetup.hpe_string_to_dict("status=0\r\nstatus_tag=COMMAND COMPLETED\r\nerror_tag=a=b\r\n")
    assert parsed["status"] == "0" and parsed["error_tag"] == "a=b"


def test_bmc_config_reports_each_failure_and_exits_1(tool, monkeypatch):
    results = {"10.0.0.1": True, "10.0.0.2": False}

    def bmc_setup(host, user, password):
        if host == "10.0.0.3":
            raise OSError("no route to host")
        return results[host]

    monkeypatch.setattr(bios_tool, "bmc_setup", bmc_setup)
    tool.hosts([(host, "admin", "secret") for host in ("10.0.0.1", "10.0.0.2", "10.0.0.3")])
    assert tool.run("--bmc-config") == 1
    assert "2 of 3 BMCs could not be configured: 10.0.0.2, 10.0.0.3" in tool.log
