import os

import pytest

import bios_tool
from fake_bmc import dell, make_bmc

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GOOD = "Dell Inc.:\n  AMD:\n    PowerEdge R6615:\n      LogicalProc: Disabled\n"


def one_host(tool, settings):
    bmc = tool.add("10.0.0.1", make_bmc(dell()))
    tool.settings(settings)
    tool.hosts([("10.0.0.1", "admin", "secret")])
    return bmc


@pytest.mark.parametrize("settings, error", [
    (GOOD + "    bad indent: [\n", "is not valid YAML"),
    (GOOD + "      LogicalProc: Enabled\n", "found the key 'LogicalProc' twice"),
    ("Dell Inc.:\n  AMD:\n    LogicalProc: Disabled\n", "Dell Inc./AMD/LogicalProc should be a model holding settings"),
    ("!!python/object/apply:os.system ['true']\n", "is not valid YAML"),
    ("- just\n- a list\n", "should hold a YAML mapping"),
])
@pytest.mark.parametrize("options", [[], ["--fix"]])
def test_a_broken_settings_file_stops_before_any_bmc_is_contacted(tool, settings, error, options):
    bmc = one_host(tool, settings)
    assert tool.run(*options) == 1
    assert error in tool.log
    assert "No changes are needed" not in tool.log
    assert not bmc.logged_in and bmc.patches == []


@pytest.mark.parametrize("text", [
    "﻿name,user,password\n10.0.0.1,admin,secret\n",       # saved by Excel
    "name, user, password\n10.0.0.1, admin, secret\n",
    "hosts:\n  - name: 10.0.0.1\n    user: admin\n    password: secret\n",
])
def test_host_lists_as_csv_or_yaml(tool, text):
    one_host(tool, GOOD)
    (tool.dir / "host_config.csv").write_text(text, encoding="utf-8")
    assert tool.run() == 0
    assert "1 changes are needed on 10.0.0.1" in tool.log


@pytest.mark.parametrize("text, error", [
    ("10.0.0.1,admin,secret\n", "neither YAML with a 'hosts' list nor CSV"),
    ("name,user,password\n10.0.0.1,admin\n", "host 1 needs a name, a user and a password"),
    ("hosts:\n  - name: 10.0.0.1\n", "host 1 needs a name, a user and a password"),
])
def test_a_broken_host_list_is_an_error(tool, text, error):
    one_host(tool, GOOD)
    (tool.dir / "host_config.csv").write_text(text)
    assert tool.run() == 1
    assert error in tool.log


def test_dump_does_not_need_a_settings_file(tool):
    tool.add("10.0.0.1", make_bmc(dell()))
    tool.hosts([("10.0.0.1", "admin", "secret")])
    assert tool.run("--dump") == 0


def test_save_defaults_does_not_overwrite_a_broken_database(tool):
    one_host(tool, GOOD)
    (tool.dir / "defaults-db.yml").write_text("Dell Inc.: [\n")
    tool.run("--save-defaults")
    assert (tool.dir / "defaults-db.yml").read_text() == "Dell Inc.: [\n"


@pytest.mark.parametrize("name", ["bios_settings.yml", "WEKApod.yml", "Dell-Genoa-bios.yml"])
def test_the_shipped_settings_files_load(name):
    bios_tool.load_bios_settings(os.path.join(REPO, name))


def test_the_shipped_defaults_database_loads():
    bios_tool.load_yaml(os.path.join(REPO, "defaults-db.yml"))
