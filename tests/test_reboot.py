import builtins
import sys

import pytest

from fake_bmc import dell

SETTINGS = {"Dell Inc.": {"AMD": {"PowerEdge R6615": {"LogicalProc": "Disabled"}}}}


@pytest.fixture
def hosts(tool):
    drifted, staged, clean = tool.servers(SETTINGS, dell(), dell(LogicalProc="Disabled"),
                                          dell(LogicalProc="Disabled"))
    staged.pending()["ProcVirtualization"] = "Disabled"     # left by an earlier --fix without --reboot
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


def test_without_a_terminal_or_yes_no_bmc_is_contacted(tool, hosts):
    assert tool.run("--fix", "--reboot") == 1
    assert not any(bmc.logged_in for bmc in hosts)
    assert "run with --yes" in tool.log


@pytest.mark.parametrize("reply, rebooted", [("y", True), ("yes", True), ("n", False), ("", False)])
def test_the_question_decides(tool, hosts, monkeypatch, reply, rebooted):
    answer(monkeypatch, reply)
    assert tool.run("--fix", "--reboot") == 0
    assert (hosts[0].resets() == ["GracefulRestart"]) is rebooted


def test_a_failed_reboot_is_an_error(tool, hosts):
    hosts[0].post_status = 500
    assert tool.run("--fix", "--reboot", "--yes") == 1
    assert "10.0.0.1 refused to reboot (GracefulRestart): HTTP 500" in tool.log
