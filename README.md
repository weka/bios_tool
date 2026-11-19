# bios_tool
A tool for viewing/setting bios settings for Weka servers

```
usage: bios_tool [-h] [-c HOSTCONFIGFILE] [-b BIOS] [--bmc-config] [--fix] [--reboot] [-y] [--dump]
                 [--save-defaults] [--defaults-database DEFAULTS_DATABASE] [-f] [--reset-bios] [--diff DIFF DIFF]
                 [--diff-defaults] [--version] [--bmc-ips [BMC_IPS ...]] [--bmc-username BMC_USERNAME]
                 [--bmc-password BMC_PASSWORD] [--ca-file CA_FILE] [-v]

View/Change BIOS Settings on servers

options:
  -h, --help            show this help message and exit
  -c HOSTCONFIGFILE, --hostconfigfile HOSTCONFIGFILE
                        filename of host config file. Default is host_config.csv
  -b BIOS, --bios BIOS  bios configuration filename. Default is bios_settings.yml
  --bmc-config          Configure the BMCs to allow RedFish access
  --fix                 Correct any bios settings that do not match the definition
  --reboot              Reboot the servers with BIOS changes waiting to be applied (those --fix changed now or
                        earlier), after asking
  -y, --yes             Answer yes to the question before rebooting or resetting, so it can run without a terminal
  --dump                Print out current BIOS settings only
  --save-defaults       Save default BIOS settings to defaults-database - should be factory reset values
  --defaults-database DEFAULTS_DATABASE
                        Filename of the factory defaults-database. Default is defaults-db.yml
  -f, --force           With --save-defaults, overwrite a model already in the defaults database
  --reset-bios          Reset the BIOS to factory defaults, after asking. To also reboot, add the --reboot option
  --diff DIFF DIFF      Compare 2 hosts BIOS settings
  --diff-defaults       Compare hosts BIOS settings to factory defaults
  --version             Display version number
  --bmc-ips [BMC_IPS ...]
                        a list of hosts to configure instead of using the host_config.csv
  --bmc-username BMC_USERNAME
                        a username to use on all hosts in --bmc-ips
  --bmc-password BMC_PASSWORD
                        a password to use on all hosts in --bmc-ips; visible to other users in ps and in shell
                        history, so prefer $BIOS_TOOL_BMC_PASSWORD or the prompt
  --ca-file CA_FILE     check each BMC's TLS certificate against the CA certificates in this file; by default
                        certificates are not checked, as most BMCs' are self-signed
  -v, --verbose         enable verbose mode
```

## Getting Started
There are 3 configuration files for bios_tool: a host configuration file (`host_config.csv`), a BIOS settings file (`bios_settings.yml`), and a defaults database (`defaults-db.yml`). They are looked for in the current folder.
You can either use these default names or override them with `-c`/`--hostconfigfile`, `-b`/`--bios` and `--defaults-database`, or list the BMCs with `--bmc-ips` instead of a host file (see Command-line Host Specification below).

bios_tool needs Python 3.9 or later (its tests run on 3.11 and 3.13) and the packages in `requirements.txt`; `pyinstall.sh` builds a single binary that needs neither.
### host_config.csv
The host configuration file lists the BMCs (IPMI, iLO, iDRAC, XCC) and their logon credentials. It may be CSV or YAML, whatever its name: bios_tool reads it as YAML if it holds a `hosts` list, and otherwise as CSV, which must start with a `name,user,password` line. It holds BMC passwords, so keep it readable only by you, and do not commit it.

The default format is standard CSV, as such: (compatible with Excel)
```angular2html
name,user,password
192.0.2.11,ADMIN,<password>
192.0.2.12,Administrator,<password>
192.0.2.13,root,<password>
```

The format can also be standard YAML, as such:
```angular2html
hosts:
  - name: 192.0.2.11
    user: Administrator
    password: <password>
  - name: 192.0.2.12
    user: Administrator
    password: <password>
```

You should set all the servers you want to work with here.   Note they may have different passwords for each server.

See the section on `--bmc-ips` to configure the hosts on the command line instead of in configuration files.

### bios_settings.yml (and others)
The `bios_settings.yml` defines general BIOS settings that you want set on the servers that are defined in the host configuration file.   There are other settings files provided: `Dell-Genoa-bios.yml` for Dell servers equipped with Genoa generation AMD processors, and `WEKApod.yml`, specifically for WEKApod servers (which come pre-set anyway, but if you want to make the same settings to similar servers, these are the settings).

The format of the bios settings file is standard YAML, as such:
```angular2html
server-manufacturer:
  architecture:
    server-model:
      setting: value
      setting: value
  architecture2:
    server-model2:
      setting: value
      setting: value
```
The server-manufacturer is matched to the `Manufacturer` the server's Redfish `Systems` resource reports, so this tool can be used with most manufacturers that support Redfish.
Currently known manufacturer names are "Dell Inc.", "HPE", "Lenovo", "Supermicro" and "WEKA", and settings for these manufacturers are in the example file.

The architecture is "AMD", "Intel" or "ARM", from the server's CPU.

The file is read as YAML with no tricks: a key given twice, a model holding something other than settings, or a YAML error stops bios_tool before it contacts any server.

See the provided `bios_settings.yml` for a full example, but here's what it looks like:
```angular2html
Dell Inc.:
  AMD:
    PowerEdge R6615:
      LogicalProc: Disabled
      NumaNodesPerSocket: "1"
      PcieAspmL1: Disabled
      ProcCStates: Disabled
      ProcPwrPerf: MaxPerf
[...snip...]
```

A model of `'*'` holds the settings every model of that manufacturer and architecture needs. A server gets the `'*'` settings with its own model's settings laid over them: a setting in both takes the model's value, and a server whose model is not listed gets the `'*'` settings alone.

## Default Behavior
With no command-line overrides, bios_tool will scan the hosts in the `host_config.csv` and note where they differ (if they differ) from the settings in the `bios_settings.yml` file.
No changes are made to the servers (read-only mode)

Every run that checks settings ends with a table of each server, its platform, and what happened to it.

Example output:
```angular2html
Opening sessions to hosts:
Connected to 192.0.2.11
Connected to 192.0.2.14
[...snip...]
Looking at 192.0.2.11: HPE/AMD/ProLiant DL325 Gen10 Plus:
No changes are needed on 192.0.2.11
Looking at 192.0.2.14: HPE/AMD/ProLiant DL325 Gen10 Plus:
192.0.2.14: BIOS setting ApplicationPowerBoost is Enabled, but should be Disabled
192.0.2.14: BIOS setting CStateEfficiencyMode is Enabled, but should be Disabled
192.0.2.14: BIOS setting DataFabricCStateEnable is Auto, but should be Disabled
192.0.2.14: BIOS setting DeterminismControl is DeterminismCtrlAuto, but should be DeterminismCtrlManual
4 changes are needed on 192.0.2.14
[...snip...]
There are 1 hosts needing changes
```

## Exit status
bios_tool exits with status 0 when it did everything it was asked, and 1 when anything was left undone: a server it
could not reach, a server or setting the settings file does not cover, a change or reboot a BMC refused, or a question
it could not ask. Check it in scripts; the log says what was left undone.

A server the settings file has no entry for (no manufacturer, architecture, or model or `'*'`) is reported by name.
With `--fix` or `--reboot`, no server is changed if any is unknown.

## Optional Behaviors
### BMC Configuration mode
Using the `--bmc-config` command line option will cause bios_tool to ssh to each of the servers and turn on RedFish and IPMI Over LAN.   The RedFish is strictly REQUIRED for bios_tool operation.   IPMI Over LAN is required for WMS deployment to operate properly, so is automatically enabled.
### Fix Mode
Using the `--fix` command line option will cause the tool to make the settings to the bios as defined in the `bios_settings.yml`.
It writes only the settings that differ, skips those already staged by an earlier `--fix`, and reads them back to
confirm the BMC staged them. They apply at the server's next reboot; it will not reboot the server(s) unless given the
`--reboot` option.
### Reboot option
`--reboot` reboots the servers whose BIOS has changes waiting to be applied: those that `--fix` changed in the same
run, and those changed by an earlier `--fix` that were not rebooted. Other servers are not rebooted. bios_tool lists
the servers and asks before rebooting them; `--yes` answers for you, and without a terminal to ask on it reboots
nothing unless given `--yes`.
### Dump option
Using the `--dump` command line option will cause the tool to simply print out all the bios settings for each server. (read-only)
### Save Defaults option
Using `--save-defaults`, it will record the server(s) bios settings and populate the `defaults-db.yml` file.  It will not overwrite existing definitions unless you also add `--force`.
The defaults db is used to help generate the `bios_settings.yml` definitions, and the servers should be in factory-reset state so that you record the bios default values.
### Defaults Database option
Use a different filename for the defaults database (default name is `defaults-db.yml`)
### Force option
With `--save-defaults`, `--force` overwrites the definition of a model already in the defaults database.

### How settings are matched to a server's BIOS
A setting in `bios_settings.yml` is matched to the server's BIOS setting with the same name. If there is none, it is
matched to the one with the same name once a Supermicro `_XXXX` suffix is removed from both, and then to the one with
the same letters and digits, ignoring case and punctuation (so `Hyper-Threading[ALL]` matches `Hyper_Threading_ALL_`);
each of those only if exactly one setting matches. A setting that matches none, or several, is reported with the
closest names, is neither checked nor changed, and makes bios_tool exit with status 1.
### Diff option
Using the `--diff` option will compare all the settings on 2 servers, and print out which settings differ.  This is used to help generate the `bios_settings.yml` file.

Example diff output:
```angular2html
Fetching BIOS settings of host 192.0.2.1
Fetching BIOS settings of host 192.0.2.6

Settings that are different between the servers:
Setting                     192.0.2.1                 192.0.2.6
--------------------------  -------------------------  ----------------------------
ApplicationPowerBoost       Disabled                   Enabled
CStateEfficiencyMode        Disabled                   Enabled
DataFabricCStateEnable      Disabled                   Auto
DeterminismControl          DeterminismCtrlManual      DeterminismCtrlAuto
InfinityFabricPstate        P0                         Auto
MinProcIdlePower            NoCStates                  C6
NumaGroupSizeOpt            Clustered                  Flat
NumaMemoryDomainsPerSocket  TwoMemoryDomainsPerSocket  Auto
PerformanceDeterminism      PerformanceDeterministic   PowerDeterministic
PowerRegulator              StaticHighPerf             OsControl
ProcAmdIoVt                 Disabled                   Enabled
ProcSMT                     Disabled                   Enabled
SerialNumber                SERIAL0001                 SERIAL0002
Sriov                       Disabled                   Enabled
ThermalConfig               IncreasedCooling           OptimalCooling
WorkloadProfile             I/OThroughput              GeneralPowerEfficientCompute
```
### Diff Defaults option
Using `--diff-defaults` will compare the server(s) bios settings with the `defaults-db.yml`, and output YAML that is suitable for inclusion in `bios_settings.yml`.

The idea here is to help make definitions for new servers easier.   Simply record the factory default settings with `--save-defaults`, and then manually set one server's bios settings, and run the tool with `--diff-defaults` and you get the YAML needed to change all future servers of that make/model.

Example diff-defaults output:
```angular2html
Bios Differences (Edit these before adding to the bios_settings file):
Dell Inc.:
  AMD:
    PowerEdge R6615:
      DeterminismSlider: PerfDeterminism
      DfCState: Disabled
      DfPstateFreqOptimizer: Disabled
      DfPstateLatencyOptimizer: Disabled
      PowerProfileSelect: MaxIOPerformanceMode
      ProcVirtualization: Disabled
      SysProfile: Custom
HPE:
  AMD:
    ProLiant DL325 Gen10 Plus:
      CStateEfficiencyMode: Disabled
      DataFabricCStateEnable: Disabled
      InfinityFabricPstate: P0
[...snip...]
```

### Command-line Host Specification
Using `--bmc-ips` with a space separated list of IP addresses (ie: `--bmc-ips 192.168.1.1 192.168.1.2`) and `--bmc-username` will allow you to easily configure a set of servers that have the same userid/password settings, rather than providing a configuration file. The password is read from `$BIOS_TOOL_BMC_PASSWORD`, or asked for; `--bmc-password` works too, but leaves it in `ps` and shell history.

`--save-defaults` and `--diff-defaults` leave out the settings that identify one machine or hold its passwords (service tag, serial number, asset tag, setup and system passwords) and any MAC address, so the defaults database and the suggested settings can be shared.
### Version option
Using `--version` will simply print the bios_tool version number and exit.

## Adding New Server Definitions
From time to time, we run across new servers - a new model, for example.   When this happens, we need to determine the optimal BIOS settings and add them to `bios_tool` so we can easily set these servers in the field.

The process for doing this is pretty straightforward:
1. Reset the BIOS to default values (brand-new servers should already have default values set, so this can sometimes be skipped), and reboot the server to have the settings take effect.
2. Use the `bios_tool --save-defaults` option to copy the default values from the server and save it in the defaults database
3. Run bios_tool against the server: it applies the `'*'` settings of its manufacturer and architecture, if there are any
   3a. If every setting matches, try testing with those values
   3b. If some settings are reported as not in this server's BIOS, look at the closest names it reports and set them on the server yourself, following the guidelines on get.weka.io
4. Use `bios_tool --diff-defaults` to generate the YAML definition of the new server and add it to `bios_settings.yml`
   4a. Use some judgement and edit the YAML; it should be fairly obvious what settings aren't needed or incorrect
5. Apply the settings to the rest of the servers that are to be clustered
6. Configure your cluster as normal
7. TEST the BIOS settings (performance test - might we suggest using `wekatester`?)
8. Tweak the BIOS settings as needed; try some different settings if this is a really new configuration
9. Repeat Step 4-8 as needed, until a stable, well-performing configuration is attained.
10. Submit the new definition to R&D - you can even create a PR with the new files (`bios_settings.yml` and `defaults_db.yml`) in the github repo.

## Development
The tests run bios_tool against a fake Redfish BMC, with no hardware:
```
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest tests
```
