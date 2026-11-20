# One file per profile, matching servers explicitly and extending an explicit base

2026-11-20. Each profile is one file with the settings it wants, the servers it matches (manufacturer, CPU
architecture and, usually, models) and, optionally, the name of a `base` profile whose settings it extends. A profile
with no `match` is only a base. A server must match exactly one profile, and the plan names it and its base chain.
There is no `'*'` wildcard.

## Why

Python bios_tool's `'*'` stanza applied boot-critical settings (`BootMode`, `SecureBoot`, legacy BIOS) to every model of
a vendor without the operator seeing it, and duplicated stanzas for one model drifted apart. An explicit base shares
settings in one place, and an explicit match makes which settings a server gets something the plan shows.

## Considered Options

- **Keep the nested manufacturer, architecture, model map with `'*'` as the base** (as PR #31 left it). Rejected for the
  reasons above, and because one file holding every vendor is where duplicate keys and wrong indentation hid.
