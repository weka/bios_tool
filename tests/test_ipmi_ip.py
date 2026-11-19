import subprocess

import pytest

import BMCsetup


def run_raising(exc):
    def run(command, **kwargs):
        raise exc
    return run


@pytest.mark.parametrize("exc", [
    FileNotFoundError(2, "No such file or directory", "ipmitool"),
    subprocess.CalledProcessError(1, ["sudo", "-n", "ipmitool"], stderr="sudo: a password is required\n"),
    subprocess.TimeoutExpired(["ipmitool"], 30),
])
def test_no_ipmitool_or_no_passwordless_sudo_is_a_warning(monkeypatch, caplog, exc):
    monkeypatch.setattr(subprocess, "run", run_raising(exc))
    assert BMCsetup.get_ipmi_ip() is None
    assert "Cannot tell whether this host is one of the servers" in caplog.text


def test_sudo_is_never_allowed_to_prompt(monkeypatch):
    seen = []

    def run(command, **kwargs):
        seen.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="IP Address Source : Static\nIP Address : 10.0.0.9\n")

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(BMCsetup.os, "geteuid", lambda: 1000)
    assert BMCsetup.get_ipmi_ip() == "10.0.0.9"
    assert seen[0][:2] == ["sudo", "-n"]
