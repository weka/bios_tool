# Settings profiles live in weka/bios-contrib, not in bios-tool

2026-11-20. bios-tool ships no BIOS settings. The wanted settings (today's `bios_settings.yml`, `WEKApod.yml`,
`Dell-Genoa-bios.yml`) and factory defaults (`defaults-db.yml`) become profiles in
[weka/bios-contrib](https://github.com/weka/bios-contrib), which bios-tool reads from one or more folders
(`--profiles`). cs-platform-tools installs a pinned copy of bios-contrib's profiles beside the binary.

## Why

The settings change far more often than the tool, and are tuned by the field, who already contribute to bios-contrib.
Keeping them out of the tool means a settings fix needs no tool release, and one place holds every tuned and captured
file. bios-contrib already holds the per-model factory defaults split out of `defaults-db.yml`.

## Considered Options

- **Profiles in weka/bios_tool, as today.** Rejected: every settings change is a tool change, and bios-contrib would
  hold copies that drift.
- **Profiles embedded in the binary.** Rejected: a settings change would need a new build.

## Consequences

- bios-contrib's README and lint will describe and check the profile format
  ([ADR 0004](0004-one-file-per-profile-with-an-explicit-base.md)) once it is settled.
- The settings files leave this repo with the Python tool; `bios-tool convert` turns them into profiles.
