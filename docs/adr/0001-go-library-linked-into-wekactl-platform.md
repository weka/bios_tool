# bios-tool is rewritten in Go as a library that wekactl-platform links in, replacing the Python

2026-11-20. bios-tool is rewritten in Go on the `rewrite-in-go` branch, from `master` `da045b6` (PR #31), and lands as
one PR that also removes the Python tool, its packaging and its settings files, as wekatester's rewrite does
([weka/wekatester#47](https://github.com/weka/wekatester/pull/47)).

- The command tree is a public package, `cli`, whose `NewRootCmd()` cs-platform-tools links into `wekactl-platform` and
  runs as `wekactl platform bios-tool`, as it does tatool. `cmd/bios-tool` builds the same commands as a standalone
  binary. Everything else is `internal`.
- It is a free redesign: commands, options and file formats may change. What PR #31's tests check is kept.

## Why

A linked Go package needs no Python, no PyInstaller and no second install on the host, and cs-platform-tools pins it
like its other Go dependencies. A redesign, rather than a port, is the chance to make the safe behaviour PR #31 bolted
on the default shape of the tool.

## Considered Options

- **Keep Python, packaged by cs-platform-tools.** Rejected: the binary is unreproducible today (unpinned dependencies,
  built on one machine), and every host needs Python or a PyInstaller bundle.
- **Port the Python as it is.** Rejected: its flag combinations and in-line vendor branches are where its bugs were.
