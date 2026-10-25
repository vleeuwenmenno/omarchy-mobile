<!-- SPDX-License-Identifier: MIT -->
# Myron R3 schema gate (Phase 2.15A)

Status (2026-10-25): offline, schema and validation only. This gate migrates the
preflight, collector, session and bootchain tools to an honest **R3 generation**
that can *represent* Android boot images, vendor boot images and DT table
(DTBO) images, and the difference between a metadata-only and a full-image
claim. It changes no authority: all nine authority flags stay `false`, all seven
blockers stay `missing`, nothing is live, nothing executes, `remote_commands`
stays empty, and R4 selection is still not implemented.

**Phase A has no parser.** No tool reads an image, a header or a block device,
and no tool recomputes an offset, a size, a hash or a coverage range. Every R3
value the tools accept is a synthetic claim in a fixture. The collector checks
that the claims are well formed and consistent with each other and with R2. It
does not, and cannot, check that they are true. Binary parsing was the successor
gate `r3-binary-image-parsers`; R4 stays `r4-selection-source-qualification`.

*Update (Phase 2.15B):* the synthetic, offline, metadata-only binary parsers now
exist in `tools/myron-bootchain` 0.3.0 ([R3-PARSER-GATE.md](R3-PARSER-GATE.md)).
They recompute the offsets, sizes, header and table hashes and coverage from
synthetic image bytes and publish an R3 operation this schema accepts unchanged
(the schema, the collector and its three R3 limits are not modified). They carry
no captured provenance. This document describes the schema as of Phase A; the
bootchain row below is the Phase A state.

| Tool | Version | Change |
| --- | --- | --- |
| `tools/myron-preflight` | 0.3.0 | capture schema `myron-capture-evidence-v2`, three separate budgets per requested read, R3 emits as leaf paths |
| `tools/lib/myron-collect-impl.py` | 0.2.0 | operation schema 2 with `read_domain`, nested typed policy engine, R3 profile and rules |
| `tools/lib/myron-session-impl.py` | 0.2.0 | R3 summary input generation 2 (1 MiB), nested coverage registry |
| `tools/lib/myron-bootchain-impl.py` | 0.2.0 (0.3.0 in Phase 2.15B) | GPT to R2 only; operation schema 2; R3 was a successor gate |

The deployment (0.4.0), snapshot (0.2.0), kernel and GPU contracts are
unchanged. Contract and request documents keep their structural `schema` 1;
only the capture operation envelopes moved.

## The R3 data shape

`data` is `{"images": [ImageRow]}` with exactly 18 rows, sorted by
`partition_name`: the six supported roles `boot`, `init_boot`, `vendor_boot`,
`vendor_kernel_boot`, `dtbo`, `recovery`, each unsuffixed, `_a` and `_b`.

| Level | Field | Type and rule |
| --- | --- | --- |
| row | `partition_name` | one of the 18 names |
| row | `role` | the name without its `_a`/`_b` suffix (checked, never inferred) |
| row | `image` | `null`, or an Image |
| Image | `format` | `android-boot`, `android-vendor-boot` or `android-dt-table` |
| Image | `version` | integer 0..4, narrowed by the profile below |
| Image | `page_size` | 2048, 4096, 8192 or 16384; fixed to 4096 for boot v3 and v4 |
| Image | `os_version` | raw packed `uint32` for `android-boot`, **including the literal `0`**; `null` only for vendor boot and DT table. A text form such as `"0.0.0"` is refused: no version is synthesised |
| Image | `size_bytes` | 32..16,777,216 |
| Image | `sha256` | `null` for metadata-only coverage, required for full-image |
| Image | `header` | `{offset, size_bytes, sha256}`: offset 0, the exact header structure size, always hashed |
| Image | `components` | rows `{role, index, offset, size_bytes, sha256, ramdisk_type}`, sorted by `(role, index)`, 1..256 rows |
| Image | `table` | `null`, or `{role, offset, size_bytes, sha256, entry_size, entry_count}` |
| Image | `coverage` | `{kind, ranges, covered_bytes}`; `kind` is `metadata-only` or `full-image`; 1..32 `ranges` `{index, offset, size_bytes}` |

`image: null` means the name is **absent from the R2 inventory the capture is
bound to**. It is not proof that the physical device has no such partition.

All offsets and ranges are half-open (`offset` inclusive, `offset + size_bytes`
exclusive). Every integer is bounded by its type, every extent is checked
against the image size and, through the collector's cross rules, against the R2
partition size, and no sum may pass 32 bits.

### Profile

| Partition role | Format | Versions |
| --- | --- | --- |
| `boot`, `recovery` | `android-boot` | 0, 1, 2, 3, 4 |
| `init_boot` | `android-boot` | 4, with a zero-size kernel component |
| `vendor_boot`, `vendor_kernel_boot` | `android-vendor-boot` | 3, 4 |
| `dtbo` | `android-dt-table` | 0 |

| Format and version | Header bytes | Component slots (emitted even when the size is zero) | Table |
| --- | --- | --- | --- |
| boot 0 | 1632 | `kernel`, `ramdisk`, `second` | none |
| boot 1 | 1648 | boot 0 plus `recovery_dtbo` | none |
| boot 2 | 1660 | boot 1 plus `dtb` | none |
| boot 3 | 1580 | `kernel`, `ramdisk` | none |
| boot 4 | 1584 | `kernel`, `ramdisk`, `boot_signature` | none |
| vendor boot 3 | 2112 | `vendor_ramdisk`, `dtb` | none |
| vendor boot 4 | 2128 | `vendor_ramdisk_fragment` 0..n-1, `dtb`, `bootconfig` | `vendor_ramdisk_table`, 108-byte entries, count 0..64 |
| DT table 0 | 32 | `dt_entry` 0..n-1 | `dt_entry_table`, 32-byte entries, count 1..256 |

A vendor v4 image has no overlapping aggregate ramdisk component: only the
per-fragment components. The table object is always present for vendor v4, even
at count 0; a table's `size_bytes` is exactly `entry_count * entry_size`, and a
zero-size table carries the SHA-256 of empty bytes and needs no coverage range.
Only `vendor_ramdisk_fragment` components carry a `ramdisk_type` (0..3); every
other component has `null`. Boot v0..v2 take the page size from the header
field; vendor boot and DT table also take it from the header.

### Coverage and hashes

| | metadata-only | full-image |
| --- | --- | --- |
| ranges | header, and any nonzero table, fully covered; may add more | exactly one range `[0, image.size_bytes)` |
| `image.sha256` | `null` | required |
| component hash | present exactly when the component has a positive size **and** its whole extent lies in one range; otherwise `null` | every nonzero component hashed, zero-size components `null` |
| unverified | payload, padding and EOF not covered stay explicitly unverified; coverage may not equal the whole image | nothing in the image is outside the claim |

Ranges are positive, sorted, non-overlapping, **adjacent ranges merged**,
indexed sequentially from 0, and `covered_bytes` is their exact sum. Component
hashes are never required to exist for uncovered bytes and never allowed to.
The rule `r3-hash-equal-for-identical-extents` ties the digests together:
whenever two declarations in one image describe exactly the same non-empty
`(offset, size_bytes)` (the image extent `(0, size_bytes)`, the header, a
non-empty table and any component), they must carry the same non-null hash. An
image whose header fills it (boot v4 with `size_bytes` equal to the 1,584-byte
header) cannot carry one digest for the image and another for the header. Only
equal extents are compared; contained or overlapping extents are different
claims, and zero-size extents name no byte, so the empty-table hash and null
zero-size component hashes keep their own rules.

Full-image coverage claims the source bytes and padding were covered. It still
proves **no provenance and no hardware freshness**.

## Budgets

The old single `max_bytes` on a requested operation was ambiguous (output size,
payload read and device read all looked alike). It is replaced by three exact,
separate bounds, and the collector refuses a request row that differs from them
or still carries `max_bytes`:

| Operation | `max_output_bytes` | `max_fixture_input_bytes` | `max_hardware_read_bytes` |
| --- | --- | --- | --- |
| R1, R4, R6 | 64 KiB | 64 KiB | 64 KiB |
| R2, R5, R7 | 1 MiB | 1 MiB | 1 MiB |
| R3 | 1,048,576 | 67,108,864 | 65,536 aggregate metadata coverage |

For R3 the largest image is 16,777,216 bytes, with 64 vendor fragments, 256 DT
entries and 32 coverage ranges per image. The session's R3 summary file may be
at most 1,048,576 bytes. Capture files stay at 1 MiB each and 4 MiB in total
(the four 1 MiB ceilings alone add past 4 MiB, so the total is a separate,
binding limit).

- `max_output_bytes` bounds the serialized operation document.
- `max_fixture_input_bytes` bounds `bytes_read`: the fixture payload actually
  consumed. The aggregate `covered_bytes` of all full-image R3 claims must also
  fit in it, so a claim cannot exceed what a fixture could carry.
- `max_hardware_read_bytes` bounds the aggregate `covered_bytes` of all
  metadata-only R3 images. It is the 64 KiB allowance a future approved read
  could use for headers and tables; no separate bound broadens it.

Accounting stays fixture accounting. `bytes_read` is the fixture payload
acquired: it is **not** coverage bytes and **not** hardware bytes. The
session's R3 `bytes_read` is the summary file, and every coverage and hash
value in it is classified `unverified-source-claim`. No operation document
carries a field for its own serialized length. Schema support does not
authorize a hardware read, and no hardware transport exists. A future transport
must count the **actual returned bytes, rereads and overreads separately**; the
session and bootchain accounting policies name that requirement.

## Operation envelope (all of R1-R7)

Every operation document is now

```json
{"schema": 2, "kind": "myron-precaptured-operation", "id": "...",
 "request_sha256": "...", "transport": "external-precaptured-fixture",
 "read_domain": "fixture", "read_only": true, "bytes_read": 4096, "data": {}}
```

`schema` must be the integer 2 and `read_domain` must be `fixture`. The capture
contract publishes `operation_schema: 2`, the read domain and
`legacy_generations: reject-no-adapters`. The capture schema string moved to
`myron-capture-evidence-v2`, so a v1 manifest is refused too.

## Migration and refusal

There are no adapters. The collector rejects, with no output:

- an operation with `schema` 1 (or 3, a boolean, a float, a string);
- a hybrid capture in which any operation is at the old generation, or lacks
  `read_domain`, or names a domain other than `fixture`;
- the previous R3 parallel-array rows (`absent`, `header_version`,
  `component_sizes`, ...), a row count other than 18, and unknown keys at any
  nesting level;
- a request row with the legacy `max_bytes`, or any budget that differs from
  the policy.

Session inputs follow: `r3-header-summaries.json` is generation 2 (`schema` 2,
parser `synthetic-header-summaries-v2`); the old schema 1 form is refused.

## The policy engine

The typed registry gained an exact-key `object` type and recursive `rows`,
`object` and `nullable` validation. One function checks row sorting and
uniqueness for every rows spec (a key may be one field or a list, as in
`["role", "index"]`). Hash exemptions are discovered recursively and only at the
declared nested hash paths (`data.images.*.image.sha256`,
`...header.sha256`, `...components.*.sha256`, `...table.sha256`); the same hex
string anywhere else is an identifier-shaped value. A hash can still
fingerprint a private build: the exemption makes a value legal here, it does not
make it anonymous. `emits` are leaf paths of the typed structure, and the
collector recomputes them from the registry and refuses a request that differs.
The shape check is recursive and depth-bounded, and refuses a registry whose
rules or profile are not exactly what the validator implements. Boolean variants
and `list_lengths` constraints were removed: nothing uses them.

The derived capture contract publishes `operation_schema`, the envelope, per
operation `budgets`, and for R3 the named semantic rules, the cross rules
against R2 and the profile constants above. The collector enforces completeness
against R2 itself: 18 rows, `image` present exactly where R2 lists the name, and
`image.size_bytes` no larger than the R2 partition. The session reuses those
same functions and adds nothing of its own.

## Trust

This is the same ladder as before, with the R3 claims made explicit:

| Evidence | What it shows |
| --- | --- |
| collector, `artifact-structure-only` | the fixture is well formed, bounded, redacted and bound to a request hash |
| session, `synthetic-adapter-rehearsal-only` | R3 summaries are accepted by the collector's own rules; every R3 value is an `unverified-source-claim` |
| bootchain, `synthetic-binary-parser-only` | a synthetic GPT parses to the R2 fragment; R3 is not produced |

A metadata-only image and a full-image image are different claims and are never
treated as equivalent. Neither establishes that the fixture came from a phone,
that any image boots, or that a flash is safe.

## References

Format facts used for the profile come from the Android Open Source Project's
published boot image documentation (CC BY 4.0 and Apache-2.0 sources):

- boot image header, v0 to v4:
  <https://source.android.com/docs/core/architecture/bootloader/boot-image-header>
- vendor boot image header, v3 and v4:
  <https://source.android.com/docs/core/architecture/bootloader/vendor-boot-image-header>
- DT table (DTBO) partition format, v0:
  <https://source.android.com/docs/core/architecture/dto/partitions>
- `system/tools/mkbootimg/include/bootimg/bootimg.h` and
  `system/libufdt/utils/src/dt_table.h` in AOSP for the structure sizes.

## Boundary

Phase A ends at the schema. Before any real read a human still has to review
the request hash and approve one bounded read-only session, and a live
transport, the binary parsers and R4 selection are separate, later gates.
