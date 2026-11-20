# bios-tool in Go: Design

Status: draft, on the `rewrite-in-go` branch. Decisions already taken are recorded as ADRs in [`adr/`](adr/); everything
else here is a proposal until it has one. The Python tool on `master` (after PR #31) is the behaviour to beat, not the
design to copy.

## Why rewrite

PR #31 made the Python tool safe, but its shape still fights it: one module of free functions around a mutable
`Server`, vendor quirks as `if` branches in the write path, flags that combine into modes (`--fix --reboot`,
`--reset-bios --reboot`), settings data shipped inside the tool, a PyInstaller binary with unpinned dependencies, and a
separate install for cs-platform-tools to carry. The rewrite keeps every behaviour PR #31's tests pin down and drops
the rest.

## Goals

1. **Nothing changes that the operator did not see first.** Every run computes a plan, prints it, and only `apply`
   carries it out, after asking.
2. **Never silently pass.** Unknown servers, unmatched settings, values the BMC would refuse, unreachable BMCs and
   unconfirmed writes are errors with a non-zero exit, named per server.
3. **Hard to use wrongly.** Verbs instead of flag combinations; no credentials in files; one profile chosen per server,
   shown in the plan.
4. **Vendor quirks in one place each.** A new BMC family is one file, not edits across the write path.
5. **Tested without hardware**, against a fake Redfish service fed with real captures.
6. **One binary, linked into `wekactl-platform`** ([ADR 0001](adr/0001-go-library-linked-into-wekactl-platform.md)).

Non-goals: BMC firmware updates, boot order and virtual media, OS-level tuning, a daemon or web UI.

## Layout

```
go.mod                      module github.com/weka/bios_tool
cmd/bios-tool/              standalone binary: main() around cli.NewRootCmd
cli/                        the cobra command tree; the only public package (wekactl-platform imports it)
internal/profile/           load, validate and resolve profiles; choose a server's profile
internal/inventory/         the servers to work on, and their credentials
internal/bmc/               one connected BMC, over gofish: identity, CPU, BIOS, registry, staged settings, writes
internal/bmc/vendor/        per-vendor behaviour behind one interface: dell, supermicro, hpe, lenovo, generic
internal/plan/              server state + profile -> Plan (what differs, what is staged, what is refused, why)
internal/apply/             carry out a Plan, verify every write, reboot after asking
internal/report/            tables for people, JSON for scripts
internal/fakebmc/           an httptest Redfish service for the tests, fed from testdata/
testdata/                   captured Redfish documents and registries
docs/                       this design and the ADRs
```

Everything but `cli` is `internal`, so cs-platform-tools depends on one small API: `cli.NewRootCmd()`, as it does
with tatool.

## The model

- **Server**: an entry in the inventory (address, user, where its password comes from).
- **BMC**: a connected Redfish service ([ADR 0002](adr/0002-redfish-through-gofish.md)): manufacturer, model, CPU
  architecture, current and staged BIOS settings, the attribute registry, supported apply times, and its `Vendor`.
- **Profile**: one file, one set of wanted settings, an optional `base` it extends, and the servers it matches
  ([ADR 0004](adr/0004-one-file-per-profile-with-an-explicit-base.md)). Profiles live in `weka/bios-contrib`
  ([ADR 0003](adr/0003-profiles-live-in-bios-contrib.md)).
- **Plan**: per server, the chosen profile and its base chain, and for each wanted setting one of: as wanted, staged
  (waiting for a reboot), to change (from, to), refused before sending (not in this BIOS, read-only, value not
  allowed by the registry, ambiguous name), plus server-level problems (no profile, several profiles, unreachable).
- **Vendor**: the hooks where BMCs differ: how to find the settings object, how to name-match settings (Supermicro's
  `_XXXX` suffixes), how to write (ETag, per-setting retry, apply time and its fallback), what makes staged settings
  apply (Dell's BIOS job), how to reboot.

## Commands (proposed)

| Command | Does | Changes servers |
|---|---|---|
| `bios-tool check` | Plan every server and print it | No |
| `bios-tool apply [--reboot]` | Plan, show, ask, stage the changes, verify them, and with `--reboot` reboot the servers with changes waiting | Yes |
| `bios-tool reboot` | Reboot the servers whose staged changes are waiting, after asking | Yes |
| `bios-tool reset [--reboot]` | Reset the BIOS to factory defaults, after asking | Yes |
| `bios-tool dump` | Print a server's settings, staged settings and registry facts | No |
| `bios-tool diff A B` | Compare two servers' settings | No |
| `bios-tool capture` | Write a server's factory defaults as a file in bios-contrib's layout, without identifiers | No |
| `bios-tool profiles` | List the profiles found, their bases, and which servers each matches | No |

Common options: `--hosts FILE` or `--host ADDR...`, `--profiles DIR` (repeatable), `--yes`, `--json`, `--ca-file`,
`--parallel N`. Exit status: 0 done (or, for `check`, nothing to change), 1 something left undone, 2 usage error,
3 `check` found changes to make.

## Profiles (proposed format)

```yaml
# bios-contrib: vendors/dell/PowerEdge-R6615.yml
about:
  source: WEKA lab, verified on 8 nodes with wekatester
  captured: 2026-11-20 by J. Hamill
base: dell-amd-common          # a profile name: another file's name without .yml
match:
  manufacturer: Dell Inc.
  cpu: AMD
  models: [PowerEdge R6615]
settings:
  LogicalProc: Disabled
  NumaNodesPerSocket: "1"
```

- A profile with no `match` is only a base. A server must match exactly one profile; none, or two that match it
  equally, is an error that names them. A profile listing the model beats one listing only the manufacturer and CPU.
- The base chain is resolved first and the profile's own settings laid over it; cycles and missing bases are errors.
- Factory defaults use the same file with `kind: defaults` and no `base`; `capture` writes them.
- Files are read strictly: YAML without implicit booleans surprises (`Off` must be quoted), duplicate keys and unknown
  fields rejected.

## Inventory and credentials (proposed)

`--hosts FILE` lists servers (`address`, optional `user`, optional `name`); never passwords. The password comes from
`$BIOS_TOOL_BMC_PASSWORD`, a prompt, or `--password-file` (refused unless readable only by its owner). Per-server
passwords, when sites need them, come from a credentials file of the same kind, kept out of any repo.

## Running

- Connections, checks and writes run in parallel (`--parallel`, default 10), each server on its own: one BMC failing is
  reported and the others carry on. Output is collected and printed per server, never interleaved.
- Reboots run in parallel after one question listing every server; the host bios-tool runs on, if it is one of them,
  is rebooted last.
- Every request has a timeout, every session is closed, and Ctrl-C stops new work and closes the sessions.
- Before any write, wanted values are checked against the attribute registry (allowed values, read-only), so a value a
  BMC would refuse is reported in the plan instead of failing the PATCH.

## Testing

- `internal/fakebmc` serves Redfish from JSON fixtures and records every request, as PR #31's Python fake did, with
  hooks for status codes, ETag demands and staging that silently drops a value.
- Fixtures come from real captures: the Dell R7725XD, HPE DL325 Gen10 Plus v2 and Supermicro SYS-222BT-HER captures in
  bios-contrib carry full attribute registries, current and pending settings.
- Every behaviour PR #31's 136 Python tests check is carried over as a Go test before the Python is removed.
- CI runs `go vet`, `go test -race` and golangci-lint on every push.

## Moving over

The Python tool, `requirements*.txt`, `pyinstall.sh` and the settings files leave this repo in the same PR that brings
the Go tool to parity. A `bios-tool convert` turns today's `bios_settings.yml`, `WEKApod.yml` and `defaults-db.yml`
into profiles for bios-contrib, so no tuned setting is retyped by hand.

## Open questions

1. The command and option names above, and whether `check` should exit 3 when it finds changes.
2. Whether `--bmc-config` (enabling Redfish and IPMI over SSH with racadm, XCC and iLO commands) is kept, as a
   `bmc-setup` command, or dropped.
3. Per-server credentials: needed at sites, or is one password per run enough?
4. Where cs-platform-tools installs bios-contrib's profiles, and how they are pinned.
5. Whether the profile selection rule (model beats manufacturer and CPU) is enough, or profiles need a priority.
