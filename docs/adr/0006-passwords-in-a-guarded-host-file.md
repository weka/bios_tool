# BMC passwords come from a host file that bios-tool guards, never from a repo

2026-11-20. The host file is the one way to give bios-tool its servers and their passwords: a password per BMC, because
sites increasingly give every BMC its own, and an optional `defaults:` user and password for sites that share one. It
is CSV or YAML. There is no other password source (no environment variable, no prompt). bios-tool refuses a host file that other users can read, that git tracks or would not ignore, or that still holds
a placeholder password. No real password is ever committed: the repo ships only example host files with placeholders,
and passwords never reach logs, plans, `--json` output or captures.

## Why

One password per run in an environment variable, or several in a multi-line shell string, is what humans get wrong
when every BMC has its own password; a file one row per BMC is what they can edit. The guards keep that file from
being readable by others, committed, or used with the example's placeholders.

## Considered Options

- **No passwords in files: environment variable, prompt or a password file with one password** (the first draft of the
  design). Rejected: it does not fit a password per BMC.
- **A password manager command per host (`password_command`).** Rejected for the rewrite: beyond about ten BMCs,
  writing a command per host is copy-and-paste that people get wrong, and no customer install has needed a password
  manager yet. Worth revisiting when sites ask for one, as a single integration that looks up every BMC by name or
  address rather than a command per host (design, § Future work).
- **An environment variable or a prompt as well as the file.** Rejected: one method is easier to explain and to guard,
  and a shell string holding several passwords is what people get wrong.
- **An encrypted host file (sops, age).** Not chosen for now: every editor of the file would need the tool and the key,
  which is the ergonomic cost this decision avoids.
