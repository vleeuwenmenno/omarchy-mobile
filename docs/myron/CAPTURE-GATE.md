<!-- SPDX-License-Identifier: MIT -->
# Myron fixture capture gate (Phase 2.12)

Status (2026-10-24): offline, deterministic, structure-only.
`tools/myron-collect` 0.1.0 checks a **pre-captured fixture** against one
preflight request and records that it matched. It is **not live evidence**,
**not approval**, and **clears no blocker**. It has **no live transport**: it
executes nothing, contacts no phone, and reads only local files.

The only transport is `external-precaptured-fixture`: a trusted local tree
that someone else produced earlier. Nothing here proves the fixture came from
the phone, that the phone state is real, or that any read was permitted.

## What it does and does not establish

| Claim | Value |
| --- | --- |
| `evidence_level` | `artifact-structure-only` |
| `status` | `fixture-evidence-recorded` |
| `live` | `false` |
| `executes` | `false` |
| `remote_commands` | `[]` |
| `kit_snapshot_reverified` | `false` (the kit and snapshot are not re-read) |
| `human_approval_required` | `true` |
| blockers | all seven `missing`; no `blocker_cleared` field exists |
| authority | the nine flags stay `false` |

A recorded fixture lets a human reviewer see that a capture is well formed,
bounded, redacted and bound to a request hash. Whether it is true, and whether
a read session or deployment may follow, stays a separate human decision.

## Commands

| Command | Effect |
| --- | --- |
| `show` | Print the canonical capture contract. |
| `plan --request R` | Print the deterministic, value-free collection plan. |
| `verify-plan --request R --plan P` | Recompute the plan; `P` must match byte for byte. |
| `collect --request R --capture C --out O` | Validate the fixture and publish a new evidence artifact. |
| `verify-evidence --request R --capture C --evidence E` | Recompute the evidence from `R` and `C`; `E` must match exactly. |

`R` is a preflight request built by `tools/myron-preflight`. The collector
reads it with `myron-preflight`'s own `read_request` and binds
`sha256(request/SHA256SUMS)`. It does not take a kit or snapshot, so it does
not re-verify them.

## Capture fixture tree

Exactly these entries, canonical ASCII JSON, owned by the invoking user or
root, not group/world-writable, not executable:

```text
capture.json
operations/R1-identity-and-slot.json
operations/R2-gpt-and-recovery-inventory.json
operations/R3-boot-image-headers.json
operations/R4-dtb-dtbo-selection.json
operations/R5-module-load-order.json
operations/R6-storage-and-mount-model.json
operations/R7-kernel-identity-revalidation.json
```

`capture.json` binds the capture contract hash, the request hash, the
transport, `live: false`, and each operation file's SHA-256 and size.
Each operation file binds the request hash, the transport, `read_only: true`,
`bytes_read`, and one `data` object whose fields are the request's `emits`
list for that operation.

Bounds and rejections:

- each operation file and its `bytes_read` stay within the request's
  `max_bytes` for that operation (64 KiB or 1 MiB); the whole tree stays
  within 4 MiB;
- no extra, missing, nested, symlinked, hard-linked, FIFO/special, executable,
  or mount-crossing entry; no symlinked root or ancestor; no writable parent;
- strict schemas: exact keys, no booleans for integers, no floats, ranges,
  enums, ASCII patterns, sorted unique lists, list-length bounds;
- identifier rejection everywhere (keys and values): MAC, UUID, 14+ digit
  runs (IMEI-shaped), long hex, and the words the request lists under
  `never_emits` (serial, IMEI, MEID, MAC, SSID, partition UUID, disk GUID,
  raw payload, kernel/ramdisk/firmware/module bytes);
- R7 accepts only the command-line and bootconfig keys and values the request
  lists; any other key or value fails;
- cross-checks: R1 slot agreement, R2/R3/R6 partition consistency, R7 against
  R1, and the R5 order claim against the module list.

A capture that reports a stop condition (identity mismatch, source
disagreement, `sources_agree: false`) is rejected, not recorded.

## Evidence artifact

Exactly five files:

- `contracts/capture-contract.json`
- `evidence.json`
- `status.json`
- `STATUS.txt`
- `SHA256SUMS`

`evidence.json` holds hashes, sizes and bounds per operation, not the captured
values. The artifact is deterministic: the same request and capture give the
same bytes.

## Safety and publication

The tool imports exact `myron-preflight` 0.2.0, `myron-snapshot` 0.2.0 and
`myron-deployment` 0.4.0 in-process and refuses any other version. The capture
contract pins the preflight contract hash; the preflight contract does not
reference the capture contract. The tool starts no process and has no network
or broad-copy facility.

It reuses the deployment tool's trusted tree reader and `publish` (private
same-parent temp directory, `renameat2(RENAME_NOREPLACE)`). The request and
capture are protected inputs: an output inside, equal to, or aliasing either is
refused, and both are re-read and recomputed inside `verify_built`, so a byte
that changes between the first read and publication aborts the run and leaves
no output.

## Boundary after Phase 2.12

A passing fixture says only that its structure is acceptable. Before any real
read, a human still needs to review the request hash and approve one bounded
read-only session. Even then the collector does not run it: a live transport
would be a new, separately reviewed gate. All seven blockers remain open.
