<!-- SPDX-License-Identifier: MIT -->
# Myron synthetic R4 selection mechanism (Phase 2.15C)

Status (2026-10-25): offline, deterministic, **synthetic binary parser
qualification**, and the final *planned* synthetic gate. Hardware discovery may
reveal another selection source or format, so this is not guaranteed final parser
work. `tools/myron-bootchain` 0.4.0 gains three commands (`plan-selection`,
`parse-selection`, `verify-selection`, selection parser 1.0.0) that:

1. reparse the **same exact R3 image fixture bytes** that the R3 parser admitted,
2. count the flattened device tree (FDT) blobs of one fixed base partition's `dtb`
   component and the entries of one DT table (`dtbo`),
3. check a synthetic index witness for **membership and binding only**, and
4. emit the R4 operation (`R4-dtb-dtbo-selection`) that the unchanged
   `tools/myron-collect` validates, with `selected_board_id`,
   `selected_board_revision` and `selection_source` **always null**.

It is **not** captured provenance, **not** a live transport, **not** hardware
evidence or qualification, **not** authorization and **not** blocker closure. It
does not establish which board a real Myron selects, from which source, how
fresh that is, or what any board id means. All nine authority flags stay `false`,
all seven blockers stay `missing`, `live` is `false`, `remote_commands` is `[]`
and `complete_capture` is `false`. No SSH, ADB, fastboot, block device, firmware or
vendor byte is read or committed: the tests generate every image and device tree at
runtime in a temporary directory.

## What the mechanism implements, and what stays deferred

| Implemented (synthetic bytes only) | Deferred: `hardware-witness-required` |
| --- | --- |
| FDT v17 parsing of one base partition's dtb component, DT table v0 entry counting | The actual Myron witness: which blob and which entry a real bootloader selects |
| A synthetic witness claim, bound by hash, checked for membership in the parsed sets and for the exact contract compatible token | The selection source and its semantics (a DTBO header word, the live device tree, bootconfig, or something hardware discovery finds) |
| Binding to the request, the R2 inventory, the exact R3 fixture and the R3 parse | Captured provenance and freshness of the witness and of the images it indexes |
| The R4 operation with counts, the contract compatible constant and a null selection triple | A multi-overlay ordering model, a live merged tree, a complete-device claim |

The contract records this as `implemented_operations: [R2, R3, R4]` with an
`r4_capability` object (`counts_from_synthetic_bytes: true`,
`synthetic_index_binding: true`, `selected_board_fields_produced: false`,
`captured_provenance: false`, `hardware_qualified: false`) **and** as one deferred row:
state `hardware-witness-required`, successor gate
`r4-selection-source-qualification`. The unresolved claims are
`r4-selection-provenance-not-established`, `r4-selection-source-semantics-not-established`,
`r4-actual-myron-witness-not-established`, `r4-selection-freshness-not-established`
and `r4-multi-overlay-ordering-not-established`.

Two rules protect the successor gate:

- A synthetic index and a DT table entry's id or revision are **never promoted** to
  actual selected-board facts. The decoded id and revision exist only in the parse
  sidecar, labelled `parse-sidecar-only`; the operation fields stay null.
- Nothing is inferred from an id, a singleton, the highest revision or entry 0.
  Duplicate ids and revisions are valid DT tables and select nothing.

One base source and one overlay index is deliberately narrow: no multi-overlay
ordering, no live merged tree and no complete-device claim.

## A second deliberate generation break

Phase 2.15C changes the envelope bytes and request bindings, so it is a break with
**no adapters**. Old and mixed generations refuse.

| Tool | Before | Now | Change |
| --- | --- | --- | --- |
| `tools/myron-preflight` | 0.3.0 | 0.4.0 | capture schema `myron-capture-evidence-v3`; R4 budget 65,536 / 67,121,152 / 65,536 |
| `tools/lib/myron-collect-impl.py` | 0.2.0 | 0.3.0 | operation envelopes schema 3 (R1-R7); `selection_source` nullable enum; `null_together` over the whole selection triple |
| `tools/lib/myron-session-impl.py` | 0.2.0 | 0.3.0 | `r4-selection.json` schema 2 (nullable source, all-or-none triple); R3 summary schema stays 2 |
| `tools/lib/myron-bootchain-impl.py` | 0.3.0 | 0.4.0 | the three selection commands; contract pins collector 0.3.0 and preflight 0.4.0 |

R2 and R3 data semantics are unchanged. The image parser keeps contract 1.0.0. The
selection parser is independently versioned 1.0.0. The exact dependency pins, every
derived contract, fixture and test moved together.

### The selection triple

`selected_board_id`, `selected_board_revision` and `selection_source` are `nullable`
and covered by one `null_together` constraint: **all null, or a full non-null
tuple**. An integer zero is a value, not an absence. The collector therefore still
represents a non-null tuple (a future witness may need it), and the session stays a
synthetic JSON claim adapter that never promotes one to parsed hardware evidence. The
bootchain parser always emits all three null, and refuses (as
`selection-operation-rejected`) any R4 operation that carries a non-null field, even
one the collector would accept.

## Commands

| Command | Does |
| --- | --- |
| `plan-selection --request REQUEST --inventory R2_OPERATION` | Value-free plan: selection-parser contract, R4 request binding, expected inputs. Reads no image. |
| `parse-selection --request REQUEST --inventory R2_OPERATION --images R3_FIXTURES --r3-parse R3_OUTPUT --selection SELECTION_FIXTURE --out OUTPUT` | Admit, reparse, check the witness, collector-validate and publish the R4 operation. |
| `verify-selection ... --parse OUTPUT` | Recompute everything and compare the artifact byte for byte. |

GPT commands stay R2-only, image commands R3-only and selection commands R4-only;
no command accepts another family's options.

## Inputs

`R3_FIXTURES` is the original flat R3 image fixture (`images.json` and the image
files): there is **no detached dtb or dtbo copy**. `R3_OUTPUT` is the published R3
parse. `SELECTION_FIXTURE` is an exact flat closure of two files:

```text
selection.json   <= 8192 bytes
witness.json     <= 4096 bytes
```

Any other entry, `bootconfig.txt` included, refuses before a payload byte is read.
Bootconfig is not parsed in this phase: no Xiaomi or `androidboot` key and no
qualcomm board semantics are interpreted.

`selection.json` (strict canonical ASCII JSON, `schema` 1, kind
`myron-synthetic-r4-selection`) binds `bootchain_contract_sha256`, `request_sha256`,
`inventory_sha256` (the R2 operation bytes), `r3_parse_sha256` (the R3 parse's
`SHA256SUMS`), `r3_operation_sha256`, `images_sha256` (`images.json`), the two source
partition names and the witness size and hash. It names no path, offset, parser,
algorithm or limit.

- Scope: `base_source_partition` is one of the supported `boot`, `recovery`,
  `vendor_boot` or `vendor_kernel_boot` variants (`""`, `_a`, `_b`); `init_boot` is
  never a base. `dtbo_source_partition` is a `dtbo` variant. The two must share one
  slot suffix, a synthetic profile restriction and **not** an active-slot claim.
- A source partition absent from the bound R3 fixture is a binding mismatch.

`witness.json` (kind `myron-synthetic-r4-witness`) carries `request_sha256`,
`r3_operation_sha256`, the same two scope names and `claim`: `null`, or exactly
`dtb_index` 0..63 and `dtbo_entry_index` 0..255. It is a synthetic, unverified claim.
The manifest hashes the witness; the witness never hashes the manifest, so there is no
circularity.

## Binding: the R3 parse is recomputed, never trusted

An R3 operation carries header and table hashes and extents only. Two fixtures whose
device tree payload differs can produce **byte-identical R3 operations**
(`tests/myron-bootchain-selection` builds such a pair: two tightly concatenated blobs
versus one blob of the same total size). So the R3 operation's hashes alone cannot
bind the payload, and this gate does not rely on them. It:

1. validates the request and the R2 inventory through the shared reader and the
   collector,
2. gathers the exact R3 fixture (each image read once into an immutable buffer and
   checked against its manifest hash),
3. recomputes the expected R3 artifact from those buffers and requires `--r3-parse` to
   equal it entry for entry and byte for byte,
4. reads the selection closure and checks every binding against the recomputed values,
5. parses the chosen base dtb component and the chosen DT table from the same buffers.

## Formats

**Android DT table v0** reuses the R3 layout rules. Only for the sidecar's claimed
entry are the big-endian words at entry offsets 8 (id) and 12 (revision) decoded.
Duplicate ids and revisions are allowed, custom words are opaque, and a DTBO payload
need not parse as a device tree (it is never parsed). A table of 1..256 entries is
supported; an empty or 257-entry table is refused by the shared R3 admission under
its own `image-unsupported` / `image-budget` codes before any R4 code runs.

**Base FDT**: the exact R3 `dtb` component is one v17 blob or tightly concatenated v17
blobs. A blob has a big-endian `0xd00dfeed` magic, a 40-byte header and
`last_comp_version` 16. The parser validates block extents and alignment, the reserve
map terminator, structure tokens by an iterative, balanced traversal, string
references, a single `FDT_END`, zero gaps and slack, and exact component consumption
(no scanning for a magic, no gap between blobs, no trailing byte). Only the root node's
`compatible` is read; a duplicate root compatible is corrupt and a missing one is
unsupported. A candidate matches the contract compatible (`qcom,canoe-mtp`, the capture
contract's `device.compatible`) only as one exact whole token.

| Limit | Value |
| --- | --- |
| blobs per component | 64 |
| node depth | 64 |
| nodes per blob | 4096 |
| properties per blob | 8192 |
| node and property names | 128 bytes |
| root compatible | 1..16 NUL-terminated printable ASCII tokens, each 1..64 bytes |

Classification: malformed bytes are `selection-corrupt`; valid bytes outside the
profile (another version, no root compatible, an empty or dtb-less base) are
`selection-unsupported`; exceeded numeric limits are `selection-budget`.

## Membership and binding

With a null claim the parse reports counts only. With a claim, `dtb_index` and
`dtbo_entry_index` must lie inside the parsed counts and the chosen base candidate
must contain the exact compatible token (otherwise `selection-witness-rejected`). The
sidecar then records the computed membership result and the selected table entry's raw
id and revision. This still produces **no** non-null selection field.

## Output

The exact closure is `parse.json`, `SHA256SUMS` and
`operations/R4-dtb-dtbo-selection.json`; no binary, raw or witness copy is published.
The operation holds the parsed `dtb_count`, the parsed `dtbo_entry_count`, the contract
`compatible_prefix` constant and the null triple. `parse.json` classifies every item as
`parsed-bytes`, `unverified-synthetic-witness-claim`, `computed-membership-result`,
`parse-sidecar-only-raw-words`, `contract-constant` or `not-established`, and lists what
is not established (actual board id, revision and source, provenance, freshness, source
semantics, board semantics, multi-overlay ordering).

## Accounting

| Quantity | Meaning | Bound |
| --- | --- | --- |
| per image | each image file | 16,777,216 |
| S | complete R3 fixture bytes (`images.json` plus every present image) + `selection.json` + `witness.json`; the operation's `bytes_read` | 67,121,152 (R3's 64 MiB plus 12 KiB) |
| M | per image, the union of the reused R3 metadata coverage and, for the one base image, the complete parsed dtb component range; overlap counted once; summed | 65,536 |
| O | canonical R4 operation bytes, newline included | 65,536 |
| output | `parse.json` 131,072, operation 65,536, `SHA256SUMS` 1,024 | 197,632 total |

These are the collector's own R4 budgets (`max_fixture_input_bytes`,
`max_hardware_read_bytes`, `max_output_bytes`). The request tree, the R2 inventory and
the R3 parse artifact are dependency reads, reported separately in the sidecar and
never counted in S. `hardware_bytes_read` is 0 and no transport exists.

## Diagnostics and safety

Fixed, value-free codes: `selection-input-rejected`, `selection-binding-mismatch`,
`selection-unstable`, `selection-corrupt`, `selection-unsupported`, `selection-budget`,
`selection-witness-rejected`, `selection-operation-rejected` and `publish-rejected`.
Untrusted paths, names, bytes, sizes, hashes, compatible strings and exception text are
never echoed. The shared request, R2 inventory and R3 image admissions keep their
documented `request-rejected` and `image-*` codes, as do the shared output comparison
messages.

The gather reuses the strict admissions: exact closures before payload reads, regular,
no-follow, single-link files with trusted mode and ancestry, no executable, writable,
special or mount-crossing entries, path and inode alias checks across all five inputs
and the output, bounded descriptor reads, one buffer for hashing and parsing, repeated
settle checks, and deterministic private no-replace atomic publication with fresh
recomputation of every gather.

**Snapshot limitation.** Each gather is an internally validated descriptor-read
snapshot of the exact bytes consumed, not an atomic filesystem snapshot and not writer
exclusion. A source can diverge after any file's final observation, a writable shared
mapping can change bytes without changing metadata, and a later verify against a
changed source rejects. `parse-selection` gathers three times and `verify-selection`
twice, so total invocation I/O exceeds S.

## Contract and regeneration

`device/myron/bootchain-contract.json` (0.4.0) carries the independently versioned
`selection_parser` contract next to `image_parser`. Regenerate derived contracts from
the tools' own derivation, never by hand, in dependency order: the preflight and capture
contracts (`expected_preflight_contract`, `expected_capture_contract`, pinned by hash
one way), then `tools/myron-session derive-contract` and `tools/myron-bootchain
derive-contract`. Every test that derives a contract compares it with the committed
bytes.

## Tests

`tests/myron-bootchain-selection` (in `tests/all`) generates its device trees and DT
tables at runtime with `tests/myron-fixtures/selection.py`, independently of the parser.
It covers migration and mixed generations, every null-triple combination (zero valid),
FDT and DT table format boundaries (1, 64 and 65 blobs; 1 and 256 entries; empty and 257
tables), malformed and unsupported forms, witness indexes (nonzero, duplicates,
membership, incompatible candidates), a changed payload under unchanged R3 metadata,
binding forgeries, exact and one-over S, M and O, closure, link, mode, alias, race and
output-substitution cases, privacy canaries, deterministic output and the false
authorities and missing blockers.

## Successor gate

`r4-selection-source-qualification` stays open and needs a human-reviewed request: an
actual Myron witness, a qualified source and its semantics, captured provenance and
freshness, and a multi-overlay ordering model. Hardware discovery may require another
source or format than this gate parses. Nothing here authorizes any of it.
