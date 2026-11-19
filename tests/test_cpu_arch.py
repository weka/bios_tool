import pytest

from RedFishBMC import cpu_arch
from fake_bmc import ARM_CPU, dell, make_bmc


@pytest.mark.parametrize("processor, arch", [
    ({"ProcessorArchitecture": "x86", "ProcessorId": {"VendorId": "AuthenticAMD"}, "Model": "whatever"}, "AMD"),
    ({"ProcessorArchitecture": "x86", "ProcessorId": {"VendorId": "GenuineIntel"}}, "Intel"),
    (ARM_CPU, "ARM"),
    ({"InstructionSet": "ARM-A64", "Model": "Neoverse-V2"}, "ARM"),
    # BMCs that leave the Redfish fields out are recognised by the CPU's name, not its first letter
    ({"Model": "AMD EPYC 9454P 48-Core Processor"}, "AMD"),
    ({"Model": "Intel(R) Xeon(R) Gold 6530"}, "Intel"),
    ({"Model": "Ampere(R) Altra(R) Max Processor"}, "ARM"),
    ({"Manufacturer": "Advanced Micro Devices, Inc.", "Model": "4th Gen EPYC"}, "AMD"),
    ({"ProcessorArchitecture": "x86", "ProcessorId": None, "Model": "Xeon 6"}, "Intel"),
    # not a CPU, an empty socket, or nothing to go on
    ({"ProcessorType": "GPU", "Model": "AMD Instinct MI300X"}, None),
    ({"Status": {"State": "Absent"}, "Model": "AMD EPYC"}, None),
    ({}, None),
    ({"Model": None}, None),
])
def test_cpu_arch(processor, arch):
    assert cpu_arch(processor) == arch


def test_the_first_processor_that_is_a_cpu_decides(tool):
    docs = dell()
    system = "/redfish/v1/Systems/System.Embedded.1"
    docs[f"{system}/Processors"]["Members"].insert(0, {"@odata.id": f"{system}/Processors/GPU1"})
    docs[f"{system}/Processors/GPU1"] = {"ProcessorType": "GPU", "Model": "Intel Data Center GPU"}
    tool.add("10.0.0.1", make_bmc(docs))
    tool.settings({"Dell Inc.": {"AMD": {"PowerEdge R6615": {"LogicalProc": "Disabled"}}}})
    tool.hosts([("10.0.0.1", "admin", "secret")])

    tool.run()

    assert "Dell Inc./AMD/PowerEdge R6615" in tool.log
