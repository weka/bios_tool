# Redfish goes through gofish, with vendor behaviour on top of its raw requests

2026-11-20. bios-tool talks to BMCs with [gofish](https://github.com/stmcginnis/gofish) (BSD-3, no dependencies of its
own), pinned in `go.mod`. `internal/bmc` wraps it, and `internal/bmc/vendor` adds what gofish does not do, using its
`Get`/`Patch`/`Post` calls with headers.

gofish already provides, at v0.27.0: sessions and logout, a caller-supplied `http.Client` (for timeouts and CA files),
contexts, the BIOS settings object from `@Redfish.Settings` with a fallback to the BIOS resource itself, PATCHing only
the attributes that differ from the staged ones, `If-Match` from the settings object's `ETag` header, supported apply
times, attribute registries, and Dell's job resources.

bios-tool adds: Supermicro's ETag when it is only in the body (`@odata.etag`), retrying a refused batch one setting at
a time, retrying without the apply time when iDRAC refuses it, creating Dell's BIOS configuration job, Supermicro's
per-BIOS-version `_XXXX` setting names, and treating null Redfish objects as missing.

## Why

A maintained, typed Redfish client saves writing and testing the transport, sessions and schema plumbing, and its
`ETag`, apply-time and settings-object handling matches what PR #31 had to build by hand.

## Considered Options

- **A small client of our own over `net/http`.** Not chosen: less to vet, but everything gofish already tests would be
  ours to write and test again.
