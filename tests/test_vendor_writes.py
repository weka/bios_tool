from fake_bmc import AMD_CPU, FakeBMC, dell, supermicro

SMC_SD = "/redfish/v1/Systems/1/Bios/SD"
DELL_BIOS = "/redfish/v1/Systems/System.Embedded.1/Bios"


def run_fix(tool, bmc, settings):
    tool.servers(settings, bmc)
    return tool.run("--fix")


SMC_SETTINGS = {"Supermicro": {"AMD": {"AS -1115CS-TNR": {"SMTControl": "Disabled", "IOMMU": "Enabled"}}}}
DELL_SETTINGS = {"Dell Inc.": {"AMD": {"PowerEdge R6615": {"LogicalProc": "Disabled"}}}}


def test_supermicro_gets_its_settings_etag_when_it_demands_one(tool):
    bmc = FakeBMC(supermicro(cpu=AMD_CPU))
    bmc.docs[SMC_SD]["@odata.etag"] = 'W/"7"'
    bmc.patch_hook = lambda uri, body, headers: None if headers.get("If-Match") == 'W/"7"' else 428
    assert run_fix(tool, bmc, SMC_SETTINGS) == 0
    assert bmc.headers == [{}, {"If-Match": 'W/"7"'}]


def test_one_value_the_bmc_refuses_does_not_sink_the_others(tool):
    bmc = FakeBMC(supermicro(cpu=AMD_CPU))
    bmc.patch_hook = lambda uri, body, headers: 500 if "IOMMU_0038" in body["Attributes"] else None
    assert run_fix(tool, bmc, SMC_SETTINGS) == 1
    assert bmc.pending() == {"SMTControl_0037": "Disabled"}
    assert "refused IOMMU_0038=Enabled" in tool.log


def test_dell_without_an_apply_time_gets_a_bios_job(tool):
    docs = dell()
    del docs[DELL_BIOS]["@Redfish.Settings"]["SupportedApplyTimes"]
    bmc = FakeBMC(docs)
    assert run_fix(tool, bmc, DELL_SETTINGS) == 0
    assert bmc.posts == [("/redfish/v1/Managers/1/Jobs", {"TargetSettingsURI": f"{DELL_BIOS}/Settings"})]


def test_dell_that_refuses_the_apply_time_is_asked_again_without_it_and_gets_a_job(tool):
    bmc = FakeBMC(dell())
    bmc.patch_hook = lambda uri, body, headers: 400 if "@Redfish.SettingsApplyTime" in body else None
    assert run_fix(tool, bmc, DELL_SETTINGS) == 0
    assert "@Redfish.SettingsApplyTime" not in bmc.patches[-1][1]
    assert bmc.posts[0][0].endswith("/Jobs")


def test_dell_with_the_apply_time_needs_no_job(tool):
    bmc = FakeBMC(dell())
    assert run_fix(tool, bmc, DELL_SETTINGS) == 0
    assert bmc.posts == []
