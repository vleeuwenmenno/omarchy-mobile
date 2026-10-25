<!-- SPDX-License-Identifier: MIT -->
# Myron synthetic R3 image parsers (Phase 2.15B)

Status (2026-10-25): offline, deterministic, **synthetic binary parser
qualification**. `tools/myron-bootchain` 0.3.0 (0.4.0 since Phase 2.15C, see the note below) gains three commands that parse
synthetic Android boot (v0-v4), vendor_boot (v3, v4) and DT table (v0) images
into the exact, metadata-only R3 operation (`R3-boot-image-headers`, the 18-row
schema of [R3-SCHEMA-GATE.md](R3-SCHEMA-GATE.md)) that `tools/myron-collect`
already consumes. The collector validates the result unchanged. The GPT
commands (`show`, `derive-contract`, `plan`, `parse`, `verify-parse`) keep
their R2 semantics and emit byte-equivalent R2 operations.

It is **not** captured provenance, **not** a live transport, **not** hardware
evidence or qualification, **not** authorization and **not** blocker closure.
No SSH, ADB, fastboot, block device, firmware or vendor byte is read or
committed: the tests generate every image at runtime in a temporary directory.
All nine authority flags stay `false`, all seven blockers stay `missing`, and
R4 (DTB/DTBO selection) was not implemented in this phase; Phase 2.15C adds a
separate synthetic count and index-membership mechanism that never produces a
selection ([R4-SELECTION-GATE.md](R4-SELECTION-GATE.md)).

Command-specific truth: `parse` produces only R2; `parse-images` produces only
R3 (and `parse-selection`, Phase 2.15C, only R4). The bootchain contract's
qualification lists R2, R3 and R4 as implemented (synthetic-fixtures-only,
`captured_provenance: false`, `hardware_qualified: false`; R4 as parser and count
mechanics only) with R4 deferred as `hardware-witness-required`.

Phase 2.15C is a second deliberate generation break: bootchain 0.4.0, collector
0.3.0, preflight 0.4.0 and operation schema 3. The R3 operation data semantics and
the image parser contract (1.0.0) are unchanged, but the envelope bytes and request
bindings change, so artifacts and manifests of the 0.3.0 generation refuse.

## Commands

| Command | Does |
| --- | --- |
| `plan-images --request REQUEST --inventory R2_OPERATION` | Value-free plan: image-parser contract, R3 request binding, the fixture closure the inventory implies. Reads no image. |
| `parse-images --request REQUEST --inventory R2_OPERATION --images FIXTURES --out OUTPUT` | Admit, parse, collector-validate and publish the R3 operation. |
| `verify-images --request REQUEST --inventory R2_OPERATION --images FIXTURES --parse OUTPUT` | Recompute everything and compare the artifact byte for byte. |

The implementation stays in `tools/lib/myron-bootchain-impl.py` behind the
trusted loader. The derived contract (`device/myron/bootchain-contract.json`,
0.3.0) gains an independently versioned `image_parser` contract (1.0.0). The
collector, preflight, session, snapshot, deployment and device descriptor
contracts and versions are unchanged. Bootchain 0.2.0 artifacts refuse: the
manifest binds the contract hash and the artifact carries `format_version`.

Regenerating the contract is deliberate: `tools/myron-bootchain derive-contract`
prints the bytes `show` verifies (they include the implementation digest), and
`tests/myron-bootchain-images` fails until the committed file equals them.

## Inputs

**R2 inventory.** `--inventory` is one regular file: a request-bound
`R2-gpt-and-recovery-inventory` operation. It is read once through a trusted
no-follow ancestry (single link, not executable, not writable by others, same
mount) and validated by the collector's `validate_operation` against the R2
request row *before any image byte is read*. Its exact bytes are bound by
`inventory_sha256` in `images.json` and in the artifact, and its inode is
rechecked at the end of the gather. `image: null` in R3 means **absence from
this inventory**, never mere absence of a file, and says nothing about the
device. Unrelated inventory rows (a root partition, say) are ignored.

**Image fixture.** A flat directory: `images.json` plus one fixed file
`<partition_name>.img` per present row. The filenames are derived internally
from the 18 logical names (`boot`, `init_boot`, `vendor_boot`,
`vendor_kernel_boot`, `dtbo`, `recovery`, each unsuffixed, `_a`, `_b`); there is
no path field. `images.json` is canonical strict JSON (at most 16,384 bytes):

```json
{"schema": 1, "kind": "myron-synthetic-r3-images", "format_version": 1,
 "bootchain_contract_sha256": "...", "request_sha256": "...", "inventory_sha256": "...",
 "synthetic": true,
 "images": [{"partition_name": "boot_a", "present": true, "size_bytes": 8192, "fixture_sha256": "..."}]}
```

Exactly 18 rows sorted by `partition_name`. Absent: `present` false, size and
hash `null`, no file. Present: `present` true, size 1..16,777,216 exact, the
exact SHA-256 of one fixed regular file, and the name must be in the inventory
with a partition no smaller than the image.

**Safety.** The exact closure (manifest plus present files) is derived from
the admitted manifest and checked against the directory listing before any
image byte is read. Every file is pinned by descriptor and judged on metadata
first: regular, one link, not executable, not writable by others, trusted
ownership and ancestry, same device and mount, exact manifest size. The output
path may not overlap or alias the request, inventory or image tree. Mutation
is detected by repeated descriptor and name checks. A closure or metadata defect
found before traversal reads zero image bytes.

**Immutable buffers.** Each closure file is read once, from its pinned
descriptor, into a bounded in-memory buffer. The manifest hash check, the
parse and every emitted hash use those same bytes. The claim is a
**descriptor-read snapshot** only: not atomic, no writer exclusion, and a later
verify against a changed source rejects.

## Accounting

| Symbol | Meaning | Bound | Source of the bound |
| --- | --- | --- | --- |
| `S` | canonical `images.json` bytes plus every present image file's bytes | 67,108,864 per gather; each image 16,777,216 | collector R3 `max_fixture_input_bytes` |
| `M` | union bytes of the exact header structures and nonempty tables (represented metadata coverage) | 65,536 | collector R3 `max_hardware_read_bytes` |
| `O` | canonical serialized R3 operation bytes, newline and whitespace included | 65,536 | new `max_output_metadata_bytes`, **image-parser contract only** |

The three collector R3 limits are unchanged (`max_output_bytes` 1,048,576,
`max_fixture_input_bytes` 67,108,864, `max_hardware_read_bytes` 65,536); the
collector's old output bound and its 244,003-byte high-cardinality case are
untouched. The O cap exists only in the new parser.

The operation's `bytes_read` is `S`. `M` is metadata coverage that is
*represented*, not read from hardware: `hardware_bytes_read` is 0 and
`hardware_transport` is `none`. The outer `parse.json` records
`scope: one-admitted-fixture-snapshot`, `fixture_payload_bytes` = `S`,
`fixture_payload_read_bytes` = `S`, `fixture_image_hash_bytes` = the sum of the
image sizes, `represented_metadata_bytes` = `M`, `operation_output_bytes` = `O`,
`hardware_bytes_read` 0, `hardware_transport` none, `full_image_evidence` false.

The 64 MiB bound is **per complete gather**, not per invocation. Publication
revalidation and verification each run separate complete gathers:
`parse-images` gathers three times (admission, temporary and published
verification), `verify-images` twice. Total invocation I/O therefore exceeds
`S`, and no one-read claim is made.

## Evidence semantics

Metadata-only: `image.sha256` is `null`, header and table hashes are recomputed
from the admitted buffer, and coverage is exactly the header structure plus
each nonempty table with adjacent ranges merged. It never includes page
padding, payload, EOF or the whole image; an image whose metadata equals the
whole image is refused. An empty table gets the SHA-256 of empty bytes and no
range. A component hash is present only if the whole component lies inside
covered metadata (payload normally does not). All 18 rows are emitted, and
zero-size component slots are preserved with their computed layout offset.

## Parser rules

All readers are exact-length and endian-explicit. Page sizes are validated
(2048, 4096, 8192, 16384; other powers of two unsupported, non powers corrupt)
before any alignment arithmetic. Every offset, alignment and extent is checked
for 32-bit overflow and image bounds before any allocation or loop; counts are
bounded first.

| Format | Rules |
| --- | --- |
| Boot v0-v2 | little endian, `ANDROID!`, version at 40, page size at 36, packed `os_version` at 44 (literal 0 preserved). Headers 1632/1648/1660; v1/v2 `header_size` must match. Kernel at one page, then page-aligned ramdisk, second, recovery_dtbo (v1+), dtb (v2). A nonempty recovery_dtbo's stored u64 offset must equal the computed layout; an empty one may be 0 (or the layout position); the v2 dtb offset never derives from the stored value. |
| Boot v3-v4 | headers 1580/1584 with matching `header_size` and version, fixed page 4096. Kernel, ramdisk, and for v4 `boot_signature` after the aligned ramdisk (a structure extent, no cryptographic claim). `init_boot` requires v4 and a zero-size kernel. |
| vendor_boot v3-v4 | `VNDRBOOT`, headers 2112/2128 with matching `header_size`, accepts page 2048. Header span `align(header_size, page)`; v3: ramdisk, dtb; v4: ramdisk section, dtb, ramdisk table, bootconfig. Table entry 108 bytes, count 0..64, `table_size` = count x 108. Fragment `ramdisk_offset` is relative to the section (emitted absolute adds the header span); the table index is the component index; positive fragments must not overlap and must exactly cover the section; row order need not follow offset order; zero-size entries sit at in-bounds offsets. Names compare as bytes before the first NUL, must be unique (one empty name allowed), and an unterminated name is unsupported. Numeric `ramdisk_type` 0..3 is emitted; names and board ids are not. Count 0 requires a zero-size section. No selection or load order is inferred. |
| DT table v0 | big endian, 32-byte header and entries, version 0, stride 32, count 1..256. The explicit table offset and payload offsets are respected (no blanket page alignment); `total_size` must fit the fixture and contain every extent; trailing fixture bytes are allowed. Ids, revisions, custom values and any FDT content are never emitted. Shared or overlapping payload extents are valid AOSP but outside the collector's disjoint-extent profile: unsupported, not corrupt. |

## Diagnostics

Image admission, parsing and publication refusals are one fixed line ending
`(code ...)` and never contain an untrusted path, name, byte, size, hash, board
id, command line, address or exception text: `image-input-rejected`,
`image-identity-mismatch`, `image-unstable`, `image-corrupt`,
`image-unsupported`, `image-budget`, `image-operation-rejected`,
`publish-rejected`. Shared output-tree verification keeps the pre-existing
fixed diagnostics instead: unexpected names are withheld, fixed expected paths
may be named, and those lines do not append an image code.

## Output

`parse.json` (kind `myron-synthetic-r3-image-parse`, carrying the synthetic
parser provenance, accounting and the unchanged authority and blockers),
`SHA256SUMS` and `operations/R3-boot-image-headers.json` (schema 2,
`read_domain: fixture`, the collector's own transport label, which is not
provenance). No binary copy is published. Publication is private, atomic,
no-replace and verified twice, using the same code as the GPT parse.

## Tests

`tests/myron-bootchain-images` (registered in `tests/all`) with the independent
builder `tests/myron-fixtures/boot_images.py` covers every supported version,
family, role and page size; truncation, endianness, version, stride, count,
arithmetic and extents, the recovery_dtbo rule, vendor layout, relative offsets,
gaps, overlaps, duplicates and reorder, DT shared extents; exact and plus-one
budgets for `S`, `M` and `O` and 16 MiB images; all-absent and all-present
fixtures; link, mode, special-file, alias and race refusals; privacy canaries;
forged outputs and bindings; determinism; and GPT command compatibility.
`tests/myron-bootchain` carries the 0.3.0 contract expectations and the full
GPT matrix.

## Limitations and next gate

- The fixtures are synthetic; a real Myron image may differ from them, and no
  result here is evidence about a device, its freshness, slot state,
  bootability or flash safety.
- Only the listed versions and the collector's R3 profile are supported; other
  valid variants refuse as unsupported.
- The gather is a descriptor-read snapshot with best-effort mutation detection.
- The collector, preflight, snapshot and deployment imports remain trusted
  version-pinned dependencies, not byte-pinned.

The next gates are **R4 selection-source qualification**
(`r4-selection-source-qualification`, the hardware-witness gate that
[R4-SELECTION-GATE.md](R4-SELECTION-GATE.md) keeps open) and a
separate **hardware acquisition gate** (a transport that counts actual returned
bytes, rereads and overreads separately, with provenance and freshness). Both
need a human-reviewed request and approval; neither is authorized here.
