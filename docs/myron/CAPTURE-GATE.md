<!-- SPDX-License-Identifier: MIT -->
# Myron fixture capture gate (Phase 2.12)

Status (2026-10-24): offline, deterministic, structure-only.
`tools/myron-collect` 0.3.0 checks a **pre-captured fixture** against one
preflight request and records that it matched. It is **not live evidence**,
**not approval**, and **clears no blocker**. It has **no live transport**: it
executes nothing, contacts no phone, and reads only local files.

Version 0.2.0 (Phase 2.15A, [R3-SCHEMA-GATE.md](R3-SCHEMA-GATE.md)) moves every
operation envelope to integer `schema` 2 with `read_domain: "fixture"`, splits
the old `max_bytes` into three budgets, nests the typed policy and migrates R3
to 18 typed image rows. Version 0.1.0 captures (schema 1) and any capture that
mixes generations are refused; there are no adapters. The collector still has
no parser: every R3 value is a fixture claim it judges for consistency, not
truth.

Version 0.3.0 (Phase 2.15C, [R4-SELECTION-GATE.md](R4-SELECTION-GATE.md)) is a
second deliberate generation break: every operation envelope is integer `schema`
3, the capture schema is `myron-capture-evidence-v3`, and the collector pins
preflight 0.4.0. Schema 1 and 2 envelopes and any capture that mixes generations
are refused; there are no adapters. R2 and R3 data semantics are unchanged, but
envelope bytes and request bindings change. R4's `selection_source` becomes a
nullable enum and the `null_together` constraint covers `selected_board_id`,
`selected_board_revision` and `selection_source`: the triple is all null or a
full non-null tuple, and an integer zero is a value, never an absence. The
collector still has no parser and no selection logic.

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
Each operation file binds the integer `schema` 3, the request hash, the
transport, `read_domain: "fixture"`, `read_only: true`, `bytes_read`, and one
`data` object whose leaf fields are the request's `emits` list for that
operation (nested R3 fields are dotted paths; the collector recomputes them from
its policy registry).

Bounds and rejections:

- each operation file stays within the request's `max_output_bytes`, its
  `bytes_read` within `max_fixture_input_bytes`, and an R3 capture's metadata
  coverage within `max_hardware_read_bytes` (the three are exact and separate,
  see [R3-SCHEMA-GATE.md](R3-SCHEMA-GATE.md)); each file stays within 1 MiB and
  the whole tree within 4 MiB;
- schema 1 and schema 2 operations, any non-3 `schema`, a missing or non-`fixture`
  `read_domain`, and any capture mixing generations are refused;
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
  `android_idx` or `serials` do not. A bare 64-hex SHA-256 value is exempt
  only at a declared hash field: the R3 `image.sha256`, `image.header.sha256`,
  `image.components.*.sha256` and `image.table.sha256`, R7 `notes_sha256`, the
  request hash of each operation file and the contract, request and operation
  hashes of `capture.json`. The same string in any other value, or as a key,
  is rejected as an identifier-shaped value. A hash can still fingerprint a
  private build: the exemption does not make it anonymous;
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
identifier patterns, the hash-field locations, capture limits, the exclusion
list and the declared R5 module order, plus the named cross-check rules. The
validators, the collection plan and the capture contract all read it. The
committed `device/myron/capture-contract.json` embeds, besides the preflight
pin and the claims above:

- `requested_operations`: the exact R1..R7 definitions (purpose, bounds,
  targets, emits, field policy, never-emits, stop conditions);
- `forbidden_operations` and `redaction` from the request;
- `identity`: the device and kernel values the checks compare against;
- `policy`: the typed registry;
- `implementation`: algorithm `sha256-of-captured-implementation-bytes`, path
  `tools/lib/myron-collect-impl.py`, and the SHA-256 of the bytes the loader
  captured and is executing.

Nullable fields, nesting and sorting are policy data, not code. A `nullable`
or `null` type says where `null` is allowed; an `object` is an exact-key nested
structure; `rows` hold exact-key objects and name the field or fields they must
be unique and sorted by. These nest (R3 rows hold an `image` object that holds
`components` rows and a `coverage` object that holds `ranges` rows), and the
validator, the hash-path discovery and the emitted leaf paths all recurse over
the same spec. R3's `image` is `nullable`; the profile and the named semantic
rules (`policy.operations.R3.rules`, `profile`, `cross_rules`) are serialized
beside it and read back by the validator, and `check_policy` refuses a registry
that lists a rule it does not implement or a profile constant that contradicts a
typed bound. R4's board id, board revision and selection source are `nullable`
(integers and a three-value enum) with one `null_together` constraint over all
three. The previous boolean variants (R3 `absent`) and
`list_lengths` constraints are gone. The validators evaluate exactly these
specs, so the serialized policy and the accepted forms cannot disagree, and the
recursive shape check is depth-bounded.

Changing any validator constant, pattern, enum, bound, null form or
constraint changes the derived contract, and the tool refuses a committed
contract that differs from it (`capture contract differs from its derived
form`), so a policy change is always a reviewed contract change. The remaining
rule logic is code (R1 slot, R2 suffix and recovery, R5 order and indexes, R6
rounding, the R7 allowlist and the cross-checks), so the contract also pins the
implementation too: `implementation.sha256` is the digest of the validator
bytes that are running, and any edit to them, even a comment, fails every
command until the contract is regenerated from the final source. The pin
covers `tools/lib/myron-collect-impl.py` only; the preflight, snapshot and
deployment tools it calls stay pinned by version.

A capture that reports a stop condition (identity mismatch, source
disagreement, `sources_agree: false`) is rejected, not recorded.

### Trusted loader

`tools/myron-collect` is a minimal loader (about 80 lines, no process or
network facility) and the trust root of the collector. It opens
`tools/lib/myron-collect-impl.py` once, component by component with no symlink
following, requires a regular file owned by the caller and not group- or
world-writable, reads at most 1 MiB, hashes those bytes, then compiles and
executes **the same bytes** in its own module namespace. The digest it passes
on (`CAPTURED_IMPLEMENTATION_SHA256`) is what the contract and the plan bind;
the implementation path is never opened again. Restoring or replacing the file
after the capture changes neither what runs nor what the pin says, so a
modified validator cannot claim the original pin. The loader itself is reviewed
in git and is not pinned by the contract. Tests import it with
`SourceFileLoader`, as before.

### Nesting

Every operation document and `capture.json` is checked for JSON nesting
(at most 8 levels; a saved plan, which embeds the policy, at most 32)
iteratively and immediately after parsing, before the canonical-JSON renderer or
any recursive check can expand it.

## Evidence artifact

Exactly five files:

- `contracts/capture-contract.json`
- `evidence.json`
- `status.json`
- `STATUS.txt`
- `SHA256SUMS`

`evidence.json` records, per operation, its file hash, size, `read_domain`,
`bytes_read`, the three budgets and the exact validated `data`: only the allowlisted, typed fields,
with identifiers and raw payloads already rejected, so it holds no raw payload.
Evidence therefore carries the (fixture) values: treat it with the same care as
the capture. The artifact is deterministic: `verify-evidence` recomputes every
byte, including the data, from the request and the capture.

## Safety and publication

The tool imports exact `myron-preflight` 0.4.0, `myron-snapshot` 0.2.0 and
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

## Synthetic adapter rehearsal (Phase 2.13)

`tools/myron-session` ([SESSION-GATE.md](SESSION-GATE.md)) builds a capture
fixture of exactly this shape from a flat tree of synthetic projections and
checks it with this collector's `validate_operation`, `cross_check` and
`read_capture`. `capture/` in its rehearsal artifact is consumed by `collect`
unchanged. The collector is not modified by the rehearsal, and its fixture
evidence stays `artifact-structure-only`: the rehearsal adds no provenance to
it.

## Boundary after Phase 2.12

A passing fixture says only that its structure is acceptable. Before any real
read, a human still needs to review the request hash and approve one bounded
read-only session. Even then the collector does not run it: a live transport
would be a new, separately reviewed gate. All seven blockers remain open.
