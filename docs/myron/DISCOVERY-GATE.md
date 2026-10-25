<!-- SPDX-License-Identifier: MIT -->
# Myron read-only layout discovery gate (Phase 2.16 readiness)

Status (2026-10-25): **prepared and documented only**. This gate is **not
approved**, **not executed** and **not deployment authorization**. No tool,
transport or code is added by it. All nine authority flags stay `false`, all seven
blockers stay `missing`, and nothing here permits an SSH, ADB, fastboot or block
device read.

Phase 2.19 adds an offline, synthetic Stage 1 planning contract and a pure plan
validator ([DISCOVERY-CONTRACT.md](DISCOVERY-CONTRACT.md)). It checks structure only,
creates no request, approval, transport, capture, provenance or ledger, and leaves
Stage 0 unresolved and Stages 2 to 4 documentation-only.

## Why a discovery session comes next

The synthetic work is complete: the R2 GPT parser, the R3 boot, vendor boot and DT
table header parsers and the R4 count and membership mechanism all run on
synthetic fixtures ([BOOTCHAIN-GATE.md](BOOTCHAIN-GATE.md),
[R3-PARSER-GATE.md](R3-PARSER-GATE.md), [R4-SELECTION-GATE.md](R4-SELECTION-GATE.md)).
An independent design review rejected the obvious next step, a producer that
copies hardware bytes into a synthetic-style regular-file fixture, for these
reasons:

- The R3 parser consumes complete synthetic image files, while the hardware R3
  allowance (`max_hardware_read_bytes`) is 64 KiB aggregate. A partial read cannot
  be presented to that parser as a full image.
- R2 carries no partition offsets and no source mapping, so it cannot say which
  block range a partition name refers to.
- A hardware capture needs a private provenance and read ledger. It must never
  masquerade as synthetic R2, R3 or R4 input.

The correct next boundary is therefore an explicitly approved, staged, read-only
**discovery session**. Each stage answers one question, produces private raw
evidence plus a ledger, and ends at a human decision.

## What synthetic outputs mean

Parser outputs built from synthetic fixtures stay **non-authoritative**. They show
that the parsing mechanics work, nothing about the real device. Real captures are
**private raw evidence** and a **provenance and read ledger**. Both are kept
separate from any derived artifact (an R2, R3 or R4 operation, a manifest or a
summary), and a derived artifact never replaces or hides the capture it came from.
Hashing a private capture can still fingerprint a build, so hashes of raw bytes are
private too.

## Stage 0: prerequisites (nothing is read)

All of these must exist and be reviewed before Stage 1 can be requested:

1. A verified real kit, snapshot and preflight request. If the incomplete
   identity or the private raw evidence cannot fit the current contracts, a
   **distinct discovery contract** is written, reviewed and hash-pinned first. It
   must not be forced into the synthetic fixture schemas.
2. Bound hashes: the reviewed code, the contract and the request.
3. The target identity the session is allowed to talk to.
4. The exact metadata sources Stage 1 may read. Each later stage needs its own
   reviewed source-and-range allowlist before that stage can be approved; no source
   is added during a stage.
5. Byte, call and time limits per stage.
6. A private, no-overwrite output location (directories `0700`, files `0600`).
7. A recovery and SSH path the operator has confirmed, so a failed stage can end
   without touching device state.

## Stage 1: identity and storage topology (metadata only)

No partition bytes are read.

1. Revalidate the SSH host identity against an **independent trusted source**, not
   against a value the device or an earlier capture supplies.
2. Record each source identity, partition names, start and size with their units,
   the logical sector size and the capacity.
3. Stop on any disagreement between sources, any unknown source, and any unknown or
   ambiguous unit.

## Stage 2: exact GPT ranges per approved source

Only for sources Stage 1 accepted. This stage has two separately reviewed steps.
With logical sector size `s` and `N` logical sectors, `s` must be 512 or 4096,
`N >= 2*(16384/s)+4`, and checked arithmetic must show `N*s <= 2^50`.

First approve and read only the two header sectors:

| Range | Offset | Length |
| --- | --- | --- |
| Primary header | `s` | `s` |
| Backup header | `(N-1)s` | `s` |

Validate both headers offline before any table read: the fixed supported profile is
GPT revision 1.0, 92-byte headers, 128 entries of 128 bytes, primary entries at LBA
2, backup entries ending immediately before the backup header, reciprocal header
locations, matching geometry and checked usable ranges. A mismatch stops Stage 2;
no observed offset is followed and no alternative location is searched.

Only after that validation, separately approve these two table reads:

| Range | Offset | Length |
| --- | --- | --- |
| Primary entries | `2s` | 16384 |
| Backup entries | `(N-1)*s-16384` | 16384 |

Every read, retry and overread is counted. Sources are never found by scanning
content. The four planned reads return exactly `32768+2*s` bytes per source; any
reread or overread counts in addition. The raw bytes contain GUIDs and stay private.

## Stage 3: image discriminator, header and table ranges

A separate approval with two header-dependent steps. First, approve a small fixed
discriminator and minimum-header range inside each partition extent established by
accepted private provenance from Stages 1 and 2. Parse those captured header bytes
offline. Then review and separately approve any exact table or component range whose
offset and length the accepted header establishes, after checking it against the
same partition extent. No header value expands an active approval automatically.

- The discriminator, headers, dependent ranges, rereads and overreads share one
  aggregate limit of 65536 actual returned hardware bytes for R3.
- If a format or a length semantic is unknown, the stage stops.
- An unread gap is never filled, and a prefix is never presented as a full image.

## Stage 4: R4 base-DTB source and selection witness

A separate approval for the base device tree source and an **independently
meaningful** bootloader selection witness.

- Never infer a selection from entry 0, a singleton or DT table identifiers.
- At most 65536 hardware bytes, including rereads.

## Rules for every stage

- No writes, read-write mounts, reboots, recovery transitions, flashing, slot
  changes, service changes or package changes.
- No automatic retry. A failed or short read ends the stage.
- Fixed literal commands from an allowlist only. No observed value is placed in a
  shell command.
- Output directories `0700`, files `0600`. Diagnostics are fixed text and carry no
  identifiers.
- A stop condition ends the session: any limit reached, any unexpected output or
  identity, any unknown source, any error from the transport.
- Each approval is bound to the hashes of its stage, is specific to that stage and
  does not carry over to the next. An approval for one stage says nothing about
  another.

## Required before Stage 1

These must be supplied and reviewed before Stage 1:

1. The target identity and an independent trusted source for its SSH host identity.
2. The fixed metadata commands and source namespace Stage 1 may inspect.
3. Stage 1 byte, call and time limits, private output location and recovery path.
4. The discovery contract, if the current contracts cannot hold the evidence.

## Facts that deliberately remain for later stages

- Stage 1 must establish the storage source identities, partition-to-source mapping,
  GPT count, logical sector sizes and capacities. Those facts gate Stage 2; their
  absence does not block Stage 1.
- Stage 3 must establish the format and length semantics of the boot, vendor boot
  and DT table images through its separately approved header steps.
- Stage 4 must establish the base device tree source and an independently meaningful
  bootloader selection witness. An unknown witness blocks Stage 4, not Stage 1.

## Estimate

Roughly 2 to 4 hours of operator time for Stage 0 review and approvals, and a few
minutes of device time per stage. This is an estimate, not a commitment.
