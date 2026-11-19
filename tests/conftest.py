import logging
import os
import sys

import pytest
import redfish
import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bios_tool  # noqa: E402
from fake_bmc import FakeBMC, FakeClient  # noqa: E402


class Tool:
    """Runs bios_tool's main() against fake BMCs, in a temporary working folder."""

    def __init__(self, tmp_path, monkeypatch, caplog):
        self.dir = tmp_path
        self.monkeypatch = monkeypatch
        self.bmcs = {}
        self.caplog = caplog
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(bios_tool, "configure_logging", lambda logger, verbosity: logger.setLevel(logging.DEBUG))
        monkeypatch.setattr(redfish, "redfish_client", self._client)
        monkeypatch.setattr(bios_tool, "get_ipmi_ip", lambda: None)
        caplog.set_level(logging.DEBUG)

    def _client(self, base_url, username=None, password=None, **kwargs):
        host = base_url.split("://", 1)[1]
        if host not in self.bmcs:
            raise redfish.rest.v1.RetriesExhaustedError()
        return FakeClient(self.bmcs[host], username, password)

    def add(self, host, bmc):
        self.bmcs[host] = bmc
        return bmc

    def servers(self, settings, *bmcs):
        """FakeBMCs (or their Redfish documents) at 10.0.0.1, 10.0.0.2, ..., listed in the host file, with the
        settings file written unless settings is None."""
        hosts = [f"10.0.0.{number}" for number in range(1, len(bmcs) + 1)]
        bmcs = [self.add(host, bmc if isinstance(bmc, FakeBMC) else FakeBMC(bmc)) for host, bmc in zip(hosts, bmcs)]
        if settings is not None:
            self.settings(settings)
        self.hosts([(host, "admin", "secret") for host in hosts])
        return bmcs

    def settings(self, data):
        (self.dir / "bios_settings.yml").write_text(yaml.safe_dump(data) if not isinstance(data, str) else data)

    def hosts(self, rows):
        lines = ["name,user,password"] + [f"{host},{user},{password}" for host, user, password in rows]
        (self.dir / "host_config.csv").write_text("\n".join(lines) + "\n")

    def run(self, *args):
        self.caplog.clear()
        self.monkeypatch.setattr(sys, "argv", ["bios_tool"] + list(args))
        try:
            bios_tool.main()
        except SystemExit as exc:
            return exc.code or 0
        return 0

    @property
    def log(self):
        return self.caplog.text


@pytest.fixture
def tool(tmp_path, monkeypatch, caplog):
    return Tool(tmp_path, monkeypatch, caplog)
