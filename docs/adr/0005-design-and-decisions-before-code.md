# The rewrite starts from a design and ADRs, and is reviewed as a draft PR from the start

2026-11-20. The first commits on `rewrite-in-go` are [the design](../design.md) and these ADRs. Code follows package by
package, each with its tests, one commit per change, on a draft PR opened early so its automated reviewers and people
can comment as it grows. A decision taken along the way gets an ADR here; an old ADR is superseded, never rewritten.

## Why

The rewrite is a redesign of a tool that changes real hardware. Agreeing the commands, the profile format and the
behaviour first is cheaper than reworking code, and keeps the reasons where the next maintainer will look.

## Considered Options

- **Code first, documented at the end** (as wekatester's rewrite did). Not chosen: the redesign's open questions need
  answers before the code that depends on them.
