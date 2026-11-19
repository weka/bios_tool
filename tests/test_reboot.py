import builtins
import sys

import pytest

from fake_bmc import dell, make_bmc

SETTINGS = {"Dell Inc.": {"AMD": {"PowerEdge R6615": {"LogicalProc": "Disabled"}}}}


@pytest.fixture
def hosts(tool):
    drifted = tool.add("10.0.0.1", make_bmc(dell()))
    staged = tool.add("10.0.0.2", make_bmc(dell(LogicalProc="Disabled")))
    staged.pending()["ProcVirtualization"] = "Disabled"     # left by an earlier --fix without --reboot
    clean = tool.add("10.0.0.3", make_bmc(dell(LogicalProc="Disabled")))
    tool.settings(SETTINGS)
    tool.hosts([(host, "admin", "secret") for host in ("10.0.0.1", "10.0.0.2", "10.0.0.3")])
    return drifted, staged, clean


def answer(monkeypatch, reply):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr(builtins, "input", lambda prompt: reply)


def test_reboot_alone_reboots_only_servers_with_changes_waiting(tool, hosts):
    drifted, staged, clean = hosts
    assert tool.run("--reboot", "--yes") == 0
    assert (drifted.resets(), staged.resets(), clean.resets()) == ([], ["GracefulRestart"], [])
    assert drifted.patches == []


def test_fix_and_reboot_reboots_what_was_changed_and_what_was_waiting(tool, hosts):
    drifted, staged, clean = hosts
    assert tool.run("--fix", "--reboot", "--yes") == 0
    assert (drifted.resets(), staged.resets(), clean.resets()) == (["GracefulRestart"], ["GracefulRestart"], [])


def test_without_a_terminal_or_yes_nothing_is_rebooted(tool, hosts):
    assert tool.run("--fix", "--reboot") == 1
    assert all(bmc.resets() == [] for bmc in hosts)
    assert "run with --yes" in tool.log


@pytest.mark.parametrize("reply, rebooted", [("y", True), ("yes", True), ("n", False), ("", False)])
def test_the_question_decides(tool, hosts, monkeypatch, reply, rebooted):
    answer(monkeypatch, reply)
    assert tool.run("--fix", "--reboot") == 0
    assert (hosts[0].resets() == ["GracefulRestart"]) is rebooted


def test_a_failed_reboot_is_an_error(tool, hosts):
    hosts[0].post_status = 500
    assert tool.run("--fix", "--reboot", "--yes") == 1
    assert "Unable to reboot 10.0.0.1" in tool.log
    assert "1 have been modified, and 1 rebooted" in tool.log
