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
| `plan --request R` | Print the deterministic, value-free collection plan: the request's forbidden operations and redaction, and per operation its purpose, bounds, emits, field policy, never-emits, stop conditions, input path, row container and typed policy. |
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
  runs (IMEI-shaped), long hex, and every name the request lists under
  `never_emits` (`serial`, `imei`, `meid`, `mac`, `ssid`, `android_id`,
  `partition_uuid`, `disk_guid`, `raw_payload`, `kernel_bytes`,
  `ramdisk_bytes`, `firmware_bytes`, `module_bytes`). A name matches as a run
  of whole tokens split on any non-alphanumeric character, so `android_id`,
  `android-id`, `android_id_2` and `x_raw_payload` all reject, while
  `android_idx` or `serials` do not. A bare 64-hex SHA-256 value is exempt;
  nothing else is;
- R5 lists at most 256 modules (names, load-order index and taint flags);
- R7 accepts only the command-line and bootconfig keys and values the request
  lists; any other key or value fails;
- identity is compared exactly to the pinned contract, not merely shaped: R1
  codename, SoC and compatible prefix and R4 compatible prefix equal the
  kernel contract's device values, and R7 `kernel_release` and `notes_sha256`
  equal its kernel release and notes hash (a well-formed but different value
  is a stop condition and is rejected);
- cross-checks: R1 slot agreement, R2/R3/R6 partition consistency, R7 against
  R1, and the R5 order claim against the module list.

## Policy registry and capture contract

`policy_registry()` in the tool is the single typed source of every validation
constant: patterns, enums, numeric and list bounds, row containers, the
identifier patterns, capture limits and the exclusion list, plus the named
cross-check rules. The validators, the collection plan and the capture contract
all read it. The committed `device/myron/capture-contract.json` embeds, besides
the preflight pin and the claims above:

- `requested_operations`: the exact R1..R7 definitions (purpose, bounds,
  targets, emits, field policy, never-emits, stop conditions);
- `forbidden_operations` and `redaction` from the request;
- `identity`: the device and kernel values the checks compare against;
- `policy`: the typed registry.

Changing any validator constant, pattern, enum or bound changes the derived
contract, and the tool refuses a committed contract that differs from it
(`capture contract differs from its derived form`), so a policy change is
always a reviewed contract change. The named cross-check rules are recorded in
the registry, but the logic behind them is code: a new rule's logic is not
bound by the contract hash alone.

A capture that reports a stop condition (identity mismatch, source
disagreement, `sources_agree: false`) is rejected, not recorded.

## Evidence artifact

Exactly five files:

- `contracts/capture-contract.json`
- `evidence.json`
- `status.json`
- `STATUS.txt`
- `SHA256SUMS`

`evidence.json` records, per operation, its file hash, size, `bytes_read`,
`max_bytes` and the exact validated `data`: only the allowlisted, typed fields,
with identifiers and raw payloads already rejected, so it holds no raw payload.
Evidence therefore carries the (fixture) values: treat it with the same care as
the capture. The artifact is deterministic: `verify-evidence` recomputes every
byte, including the data, from the request and the capture.

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
