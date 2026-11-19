import redfish

from fake_bmc import FakeClient, dell, make_bmc


def test_ca_file_reaches_the_redfish_client(tool, monkeypatch):
    bmc = tool.add("10.0.0.1", make_bmc(dell(LogicalProc="Disabled")))
    seen = []

    def client(base_url, username=None, password=None, **kwargs):
        seen.append(kwargs.get("cafile"))
        return FakeClient(bmc, username, password)

    monkeypatch.setattr(redfish, "redfish_client", client)
    tool.settings({"Dell Inc.": {"AMD": {"PowerEdge R6615": {"LogicalProc": "Disabled"}}}})
    tool.hosts([("10.0.0.1", "admin", "secret")])
    assert tool.run("--ca-file", "/etc/pki/bmc-ca.pem") == 0
    assert seen == ["/etc/pki/bmc-ca.pem"]
    assert tool.run() == 0
    assert seen[-1] is None and "BMC certificates are not checked" in tool.log
