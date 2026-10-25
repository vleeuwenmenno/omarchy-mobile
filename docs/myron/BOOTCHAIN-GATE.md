<!-- SPDX-License-Identifier: MIT -->
# Myron synthetic GPT-to-R2 parser (Phase 2.14)

Status (2026-10-25): offline, deterministic, **synthetic binary parser
qualification**. The GPT half of `tools/myron-bootchain` proves one thing: one
narrow GPT profile, supplied as synthetic bytes, parses byte for byte into the
exact R2 operation (`R2-gpt-and-recovery-inventory`) that `tools/myron-collect`
0.2.0 already consumes, and the collector accepts the result unchanged. Version
0.2.0 (Phase 2.15A, [R3-SCHEMA-GATE.md](R3-SCHEMA-GATE.md)) moved the R2 envelope
to schema 2 with `read_domain: "fixture"`, split the old `max_bytes` into the
three request budgets and re-pinned the collector 0.2.0 and preflight 0.3.0.
Version 0.3.0 (Phase 2.15B, [R3-PARSER-GATE.md](R3-PARSER-GATE.md)) adds the
independent `plan-images`, `parse-images` and `verify-images` commands that
parse synthetic boot, vendor boot and DT table images into the R3 operation, and
deliberately breaks the contract pin and artifact format (0.2.0 manifests and
artifacts refuse). The GPT commands keep their semantics and emit equivalent R2
operation bytes: `parse` still produces only R2. R4 selection stays a successor
gate.

It is **not** real captured provenance, **not** a live transport, **not**
hardware evidence, **not** authorization, **not** blocker closure, and **not**
qualification of R3 or R4. Nothing here reads a phone or a block device. All
seven blockers stay `missing` and every authority flag stays `false`.

## What this gate qualifies, and what it does not

| Qualified here | Not qualified here |
| --- | --- |
| A GPT byte parser for one profile, tested against GPTs encoded independently in `tests/myron-bootchain` | That a real Myron GPT looks like those bytes |
| The R2 mapping from entries to `partition_name`, `size_bytes`, `bootable_flag`, `slot_suffix`, `recovery_present` | Where the bytes came from, when, or from which disk |
| The exact-closure, descriptor-read snapshot reader and the private durable publication | Acquisition, freshness, or a complete device inventory |

A raw GPT fixture can carry identifiers (the disk GUID and every partition's
unique GUID), so it stays private: the tests build theirs in a temporary
directory, and no raw binary fixture is committed. The parsed artifact omits
every GUID and never copies raw bytes.

## Staged scope: R3 is implemented separately, R4 is a successor gate

The independent design review rejected a combined R2/R3/R4 phase: the R3 row
could not honestly represent the OS version of a vendor boot or DTBO image, and
the R4 row cannot prove a selection. This phase (the GPT `parse` command)
therefore parses R2 only. R3 followed as its own gate (Phase 2.15B,
[R3-PARSER-GATE.md](R3-PARSER-GATE.md)) through separate commands; R4 stays a
**required successor gate** and nothing here implements or claims it.

- **R3 schema migration** (`r3-boot-image-schema-migration`, done in Phase
  2.15A, [R3-SCHEMA-GATE.md](R3-SCHEMA-GATE.md)). Boot images are
  format-specific: Android boot v0-v4, vendor boot v3 and v4, and DT table
  images are distinct formats. The collector and preflight now carry R3 rows
  that represent them (raw OS version, 0 or not applicable, typed components,
  exact header and table hash coverage, metadata-only versus full-image
  coverage). That was schema only. The **R3 binary parsers** now exist as
  synthetic, offline, metadata-only parsers (Phase 2.15B,
  [R3-PARSER-GATE.md](R3-PARSER-GATE.md)): they fill those rows from image
  bytes in a bound fixture, with hashes and coverage recomputed from the admitted
  buffers. They carry no captured provenance. A hardware transport that counts
  returned bytes, rereads and overreads separately, with provenance and
  freshness, is a separate **later acquisition gate**; the contract records it as
  the unresolved claims `r3-acquisition-provenance-not-established`,
  `r3-image-freshness-not-established` and
  `r3-hardware-transport-not-established`.
- **R4 selection-source qualification** (`r4-selection-source-qualification`).
  There is no concrete selected-index source. Parsing a DTBO or a device-tree
  blob does not prove which entry the bootloader selects. R4 needs an actual
  Myron witness for the selection and cross-checks against the contracts before
  any parser may claim `selected_board_id` or `selected_board_revision`.

R4 appears in the contract, the plan and every parse artifact as the one
`not-implemented` row, and the parser has no R4 code. The contract's
qualification lists R2 and R3 as implemented with a per-command scope
(`parse`: R2, `parse-images`: R3), `captured_provenance: false` and
`hardware_qualified: false`.

## Commands

| Command | Effect |
| --- | --- |
| `show` | Verify the committed bootchain contract against its derived form and print it. |
| `derive-contract` | Print the canonical contract derived from the pinned upstream contracts and the loaded implementation bytes. Stdout only: it needs no committed contract, writes nothing and authorizes nothing. |
| `plan --request R` | Print the deterministic, value-free plan: the supported profile, the exact input closure and bounds, the field mappings, the request binding, the deferred R4 row, and no authority. |
| `plan-images --request R --inventory O` | R3 counterpart of `plan`: see [R3-PARSER-GATE.md](R3-PARSER-GATE.md). |
| `parse-images --request R --inventory O --images D --out P` | Parse synthetic boot, vendor boot and DT table images into the metadata-only R3 operation. |
| `verify-images --request R --inventory O --images D --parse P` | Recompute the image parse; `P` must match byte for byte. |
| `parse --request R --reads D --out O` | Parse the synthetic reads in `D` and publish a new parse artifact. |
| `verify-parse --request R --reads D --parse O` | Recompute the whole parse from `R` and `D`; `O` must match byte for byte. |

There is no live, device, transport or executor option. `R` is a preflight
request built by `tools/myron-preflight`, read with its own `read_request`.
`request_sha256` is the SHA-256 of that verified request's `SHA256SUMS` bytes,
exactly as the collector expects. Output is canonical JSON only, never shell
syntax.

## Raw input profile `gpt-v1-128x128-primary-backup`

One flat directory of exactly six ordinary files and nothing else:

```text
reads.json
geometry.json
gpt-primary-header.bin  gpt-primary-entries.bin
gpt-backup-header.bin   gpt-backup-entries.bin
```

| File | Bytes |
| --- | --- |
| `reads.json` | 1..8192 |
| `geometry.json` | 1..1024 |
| each header | 512..4096 at metadata admission, then exactly `sector_bytes` |
| each entry table | exactly 16384 |
| total | at most 50176 |

`reads.json` is strict, canonical JSON with exactly `schema` 1, `kind`
`myron-synthetic-gpt-reads`, `format_version` 1, `bootchain_contract_sha256`,
`request_sha256`, `synthetic: true` and `files`: one row of `path`, `bytes`,
`sha256` per payload file, sorted by path. `geometry.json` is strict, canonical
JSON with exactly `schema` 1, `kind` `myron-synthetic-gpt-geometry`,
`sector_bytes` (512 or 4096) and `disk_lbas`, bounded so the disk size and every
emitted partition size stay at most 2^50 bytes. Nothing in the input selects a
filename, path, offset, count, algorithm or bound.

**Geometry is an explicit synthetic claim.** A GPT does not describe its own
sector size or disk length; `sector_bytes` and `disk_lbas` come from
`geometry.json` and are never pretended to be parsed from the GPT.

### Admission

Admission happens in a fixed order, and no payload byte is read until every step
before the read has passed:

1. the directory is opened through the trusted-artifact ancestry checks and its
   listing must equal the exact closure (at most 7 entries);
2. every one of the 6 files is pinned by a descriptor-relative, no-follow open and
   judged on its metadata alone: regular file, one link, caller or root owner,
   not group- or world-writable, not executable, same device and mount as the
   directory, and its stat size inside its own bound and inside the total;
3. the listing, the directory's identity and every pinned descriptor are
   re-checked against their names;
4. only then are the pinned descriptors read, each for exactly its stat size, with
   an end-of-file probe and an unchanged-metadata check per file. `geometry.json`
   sorts first: it is read and parsed, and both header sizes are compared with
   `sector_bytes`, before any header or table byte is read;
5. the listing, the directory and every name are checked once more.

A missing, extra or metadata-unsafe file visible before traversal therefore stops
the read at zero payload bytes. A header file that is not exactly one sector is
only knowable once `geometry.json` is read, so that refusal costs the geometry
bytes and nothing more.

**Limitation (read this).** Each gather is an internally validated
*descriptor-read snapshot*: the exact bytes consumed from the pinned
descriptors, every one hashed and bound by `reads.json`. It is **not** an atomic
filesystem snapshot, does not exclude writers, and does not claim the
caller-owned source equals those bytes at return. The settle passes (steps 3 and
5, each a double file pass) are best-effort detection: any finite sequence of
observations has a final one, so a change after a file's final observation is
not seen, and a write through a writable shared mapping that was dirtied before
admission changes bytes without changing mtime, ctime or size. Consequences:

- a defect detected before payload traversal costs zero payload bytes;
- a detected race first observable during or after traversal may consume bounded
  bytes (at most 50176) and then normally rejects with no output;
- a race that lands after the captured bytes' final observation can yield the
  already-bound snapshot of those bytes, so the artifact is valid evidence of
  what was read, not of the source's current state;
- a later `verify-parse` against the changed source rejects.

Diagnostics never echo an input value: no GUID, partition name from a refused
entry, hostile file name, caller path, control character or underlying
exception. They name a file, a field or a rule, and an unknown directory entry is
reported by count (`1 extra, 0 missing`), never by name. A parse tree under
`verify-parse` is untrusted too: tree-reader errors become fixed codes such as
`parse tree failed safe inspection (code symlink)`.

## GPT validation

Only GPT revision 1.0 with 92-byte headers, exactly 128 entries of 128 bytes and
sectors of 512 or 4096 bytes. A valid GPT outside that profile is refused as
**unsupported** (`code gpt-unsupported`), not **corrupt** (`code gpt-corrupt`).

**Headers.** `EFI PART` signature; revision `0x00010000`; `header_size` 92;
reserved 0; CRC-32 over the first 92 bytes with the CRC field zeroed. Bytes from
`header_size` to the end of the sector must be zero: a **profile restriction**,
not universal GPT validity (the specification leaves them reserved). The primary
header sits at LBA 1 with its table at LBA 2 and its alternate at
`disk_lbas - 1`; the backup header sits at `disk_lbas - 1`, its alternate at 1,
and its table immediately before it (`16384 / sector_bytes` sectors). The two
headers must agree on the disk GUID (nonzero, never emitted), the usable
interval, the entry geometry and the table CRC. The usable interval must clear
every metadata region (`first_usable >= 2 + 16384 / sector_bytes`,
`last_usable <= disk_lbas - 2 - 16384 / sector_bytes`) and be ordered.

**Tables.** Exactly 16384 bytes each. The copies must be byte-identical and
their CRC-32 must match the header field. There is no fallback, repair or
preference between primary and backup.

**Entries.** A zero type GUID is an unused entry and every other field of it is
ignored. An occupied entry has a nonzero type GUID and a nonzero unique GUID that
is unique among occupied entries (no GUID is ever emitted). Its extent needs
`first_lba <= last_lba` and lies inside the usable interval; extents are sorted
by `first_lba` to find overlaps independently of table order, which is
arbitrary. The 72-byte name is strict UTF-16LE with a NUL terminator and zero
padding after the first NUL (so a name holds at most 35 units: a profile
restriction, and a field of 36 units with no NUL is refused as unsupported, not
corrupt); an invalid surrogate, an empty name, a name outside the
collector's `[a-z0-9_]{1,36}` pattern or a duplicate name is refused. A GPT with
no occupied entry is refused as unsupported.

## R2 mapping

| Field | Derivation |
| --- | --- |
| `partition_name` | the decoded entry name |
| `size_bytes` | `(last_lba - first_lba + 1) * sector_bytes`, 1..2^50 (depends on the explicit geometry claim) |
| `slot_suffix` | `_a` or `_b` only when the name ends that way, else empty |
| `recovery_present` | true when a name is exactly `recovery`, `recovery_a` or `recovery_b` in this one GPT |
| `bootable_flag` | the literal GPT attributes **bit 2** |

Rows are emitted sorted by `partition_name`. The operation document uses the
collector's envelope (`schema` 2, `kind`, `id`, `request_sha256`, `transport`,
`read_domain` `fixture`, `read_only`, `bytes_read`, `data`). `bytes_read` is the
fixture payload only; no hardware transport exists, and a future one must count
the actual returned bytes, rereads and overreads separately (the accounting
policy states it). The document is checked by the unchanged collector's
`validate_operation` before anything is published, and again on the bytes found
in the built tree.

**`bootable_flag` semantics are `legacy-bios-bootable-bit`.** It reports one
attribute bit and does **not** prove Android slot priority, slot success, the
active slot, bootability or recovery viability. `recovery_present` is name
presence in this one GPT, not a viable recovery.

`bytes_read` is the consumed `geometry.json`, both header files and both table
files, and excludes `reads.json`, manifest validation rereads and verification
reruns. It is **fixture payload accounting**, not device I/O: the fixture is read
from files and no device is touched. The serialized operation and `bytes_read`
each obey the collector's 1 MiB bound independently.

## Parse artifact

Exactly these entries, deterministic, mode 0644 files in 0755 directories:

```text
parse.json
SHA256SUMS
operations/R2-gpt-and-recovery-inventory.json
```

`parse.json` is canonical and holds only fixed, bounded fields: the contract,
capture-contract, preflight-contract, request and `reads.json` bindings; the
implementation and dependency bindings; the profile and inventory scope
(`one-synthetic-gpt`); sorted length and hash rows for every input; the
operation's length, hash and `bytes_read`; the coverage rows (field,
classification, source, semantics) and semantic limits; the unresolved claims;
the qualification and the deferred R4 row; all nine authority flags `false`;
and all seven blockers as `missing` (there is no `blocker_cleared` field). It
states `synthetic: true`, `live: false`, `executes: false`, `remote_commands: []`,
`evidence_level: synthetic-binary-parser-only`, `status:
synthetic-parse-recorded` and `complete_capture: false`. It copies no raw bytes
and no GUID. `SHA256SUMS` covers `parse.json` and the operation file in sorted
canonical lines; `parse.json` binds the operation's bytes and hash but not
`SHA256SUMS` itself.

**Unresolved:** geometry provenance, physical acquisition and freshness, the
complete device and disk inventory (one GPT only), the protective MBR (not
parsed), Android slot semantics, bootability, R3 acquisition provenance, image
freshness and hardware transport (`r3-acquisition-provenance-not-established`,
`r3-image-freshness-not-established`, `r3-hardware-transport-not-established`),
and R4 selection provenance. (Version 0.2.0 listed
`r3-binary-parser-successor-required`; the synthetic R3 parsers resolve it.)

The standalone parse is an **operation fragment**, never a complete capture. The
`parse` command produces no R1 or R3-R7 operation. `tests/myron-bootchain` composes the
generated R2 into a complete synthetic R1-R7 fixture, built by independent test
logic, and runs the unchanged collector's `read_capture`, `collect` and
`verify-evidence` on it. The R3 in that fixture is the migrated, synthetic
18-row R3, and the collector itself enforces its completeness against the
generated R2 (an image exactly where R2 lists the name, no image larger than its
partition); a contradictory R3 presence, an oversize image, a missing row and an
R6 root outside the inventory are all rejected by the collector.

`verify-parse` regathers the input, recomputes the expected artifact and compares
the closure, modes, bytes and hashes exactly: a forged operation with a
recomputed `SHA256SUMS` and a matching `parse.json` still fails because its
semantics differ from the recomputation.

## Bootchain contract

`device/myron/bootchain-contract.json` (0.3.0) is derived and canonical; the
tool refuses any other bytes. Regenerate it deliberately with
`tools/myron-bootchain derive-contract` whenever the implementation changes (the
digest of the implementation bytes is part of it). It also carries the
independently versioned `image_parser` contract (1.0.0, see
[R3-PARSER-GATE.md](R3-PARSER-GATE.md)). It binds:

- the preflight contract (0.3.0) and the capture contract (collector 0.2.0)
  hashes, and the deployment, snapshot and kernel-reference hashes they carry;
- the bootchain implementation digest: `tools/myron-bootchain` is a minimal loader
  (the same pattern as `myron-collect` and `myron-session`) that reads
  `tools/lib/myron-bootchain-impl.py` once with no symlink following, hashes
  those bytes and executes the same bytes, so a replaced or restored file cannot
  claim the pin;
- the profile, the input closure and schemas, the output closure and accounting
  rule, the field mappings, the coverage classes and semantic limits, the
  unresolved claims, the deferred R4 row, `synthetic: true`, `live: false`,
  `executes: false`, every authority flag `false`, all seven blockers `missing`,
  and the limitations and non-goals.

The collector, preflight, snapshot and deployment tools are imported in-process
as **trusted, version-pinned dependencies**. They are pinned by version and by the
capture and preflight contract identities above, **not by bytes**: this contract
does not make their execution byte-pinned. The collector implementation digest is
bound only through the capture contract. No existing contract pins the bootchain
contract (pins are one-way), and no existing tool, contract, `device.conf`,
`BOOT_IMAGES`, `UFS_RW`, boot method or storage allowlist changes.

### Regenerating and comparing (fish)

`derive-contract` prints the contract the current source and pinned upstream
contracts derive. It does not read, write or replace anything. After any edit to
`tools/lib/myron-bootchain-impl.py` (or an upstream contract it pins):

```fish
set derived (mktemp)
tools/myron-bootchain derive-contract > $derived
cmp $derived device/myron/bootchain-contract.json        # silent: nothing to do
cp $derived device/myron/bootchain-contract.json          # differs: take the derived bytes
tools/myron-bootchain show > /dev/null                   # verifies the committed bytes
rm $derived
```

Review the diff of `device/myron/bootchain-contract.json` like any other change:
the derived bytes are the only accepted ones. `tests/myron-bootchain` fails if
the committed file is not byte for byte the output of `derive-contract`.

## Safety and publication

The tool starts no process and has no network, archive, decompression or
broad-copy facility, and opens no device node: the CRC-32 is computed in this
file. The reads tree has its own flat reader; the parse trees use the deployment
tool's trusted tree reader, and publication uses its `publish` (private
same-parent temp directory, `renameat2(RENAME_NOREPLACE)`). The request and reads
are protected inputs: an output inside, equal to or aliasing either is refused,
and both are gathered again with the parse recomputed inside `verify_built`,
which also revalidates the built operation with the collector. A difference
observed by that gather, or a collector rejection, aborts the run and normally
leaves no output.

Residuals, as in Phase 2.13:

- Publication is durable only if `fsync` of the output parent succeeds; a failure
  there is a `publish-rejected` refusal with a best-effort removal of the
  just-published output by identity. If that removal also fails the output can
  remain while the command reports failure (the test exercises this residual).
- The descriptor-read snapshot limitation above applies to every gather.

## Limitations and boundary

- The reads are synthetic. Nothing shows a real phone's GPT would produce them or
  parse under this profile.
- One GPT only: no protective MBR, no other disk or LUN, no complete inventory.
- A 36-unit name field has no room for the NUL terminator this profile requires,
  so it is refused as `gpt-unsupported`: a profile restriction, not a claim that
  such a field is invalid GPT. A nonzero byte after the 92-byte header and other
  GPT variants are refused by the profile for the same reason.
- Command-line, contract, environment and dependency failures print one fixed,
  value-free line (`code usage`, `contract-rejected`, `environment-rejected`,
  `dependency-rejected`): no argument, key, number or path from the input is echoed.
  A missing or broken collector, preflight, snapshot, deployment, kernel or GPU
  verifier is `dependency-rejected` for every command, before any input is read, and
  prints no checkout path. A dependency that exits at import time (any status or
  payload) or exports something that is not a plain exception class is refused the
  same way. The runtime exception tuple is validated and built once during that
  startup, so no `except` clause loads anything. A collector version mismatch is
  `dependency-version`; a mismatch found while a nested dependency loads is
  `dependency-rejected`. Neither prints observed or expected versions. An unexpected
  `ValueError` while a command runs is `value-error`, with no
  text. `KeyboardInterrupt` is never caught. The trusted loader reports any capture,
  compile or implementation-import failure as one fixed `loader-rejected` line.
- `bootable_flag` is a bit, not a bootability claim.
- The dependency imports are version-pinned, not byte-pinned.
- R4 selection is not implemented; R3 is parsed from synthetic fixtures only
  ([R3-PARSER-GATE.md](R3-PARSER-GATE.md)).

## Later producer (not part of this phase)

A producer that gathers real GPT bytes is a separate phase and needs its own
approval and independent review before anything reads a phone. It must be
fixed code (no shell interpolation), take an approved storage handle, use
bounded positional reads, write private output, and bind the geometry
(`sector_bytes`, `disk_lbas`) from the **same source** as the GPT bytes. Until
then geometry provenance, acquisition, freshness and the complete device
inventory stay unresolved, and all seven blockers remain open.
