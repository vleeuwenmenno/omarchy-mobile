<!-- SPDX-License-Identifier: MIT -->
# Myron synthetic adapter rehearsal (Phase 2.13)

Status (2026-10-25): offline, deterministic, **synthetic**.
`tools/myron-session` 0.1.0 proves one thing: a fixed, reviewed set of
**synthetic** input projections can be adapted deterministically into the exact
R1-R7 capture fixture that `tools/myron-collect` 0.1.0 already consumes, and
the collector accepts the result unchanged.

It is **not** real acquisition, **not** a live transport, **not** hardware
evidence, **not** authorization, **not** blocker closure, and **not**
device-format qualification. Nothing here reads a phone, and nothing here shows
that a real GPT, Android boot image or device tree would parse into these
inputs. All seven blockers stay `missing` and every authority flag stays
`false`.

## Commands

| Command | Effect |
| --- | --- |
| `show` | Verify the committed session contract against its derived form and print it. |
| `derive-contract` | Print the canonical contract derived from the pinned upstream contracts and the loaded implementation bytes. Stdout only: it needs no committed session contract, writes nothing and authorizes nothing. |
| `plan --request R` | Print the deterministic, value-free plan: input closure, bounds, parser per operation, output closure, accounting rule, coverage classes and limitations. No commands, no device paths. |
| `verify-plan --request R --plan P` | Recompute the plan; `P` must match byte for byte. |
| `rehearse --request R --reads D --out O` | Adapt the synthetic reads in `D` and publish a new rehearsal artifact. |
| `verify-rehearsal --request R --reads D --rehearsal O` | Recompute the whole rehearsal from `R` and `D`; `O` must match byte for byte. |

`R` is a preflight request built by `tools/myron-preflight`, read with its own
`read_request`. Output is canonical JSON only, never shell syntax.

## Synthetic reads (the input)

One flat directory with exactly 11 payload files plus `reads.json`, 12 files in all, and
nothing else:

```text
reads.json
r1-source-a.json  r1-source-b.json
r2-partitions.json
r3-header-summaries.json
r4-selection.json
r5-modules.tsv
r6-filesystem.json
r7-release.txt  r7-notes.bin  r7-cmdline.txt  r7-bootconfig.txt
```

`reads.json` carries exactly `schema` 1, `kind` `myron-synthetic-reads`,
`format_version` `0.1.0`, `session_contract_sha256`, `request_sha256`,
`synthetic: true` and `files`: one row of `path`, `bytes`, `sha256` per payload
file, sorted by path. The contract and request hashes bind the reads to one
session contract and one request. The registry in the contract, not the input,
chooses each file's parser, path and byte bound; a manifest cannot name a
parser or add a path.

Admission happens in a fixed order, and no payload byte is read until every step
before the read has passed:

1. the directory is opened through the trusted-artifact ancestry checks and its
   listing must equal the exact closure (at most 13 entries, so an overbound
   tree stops at the listing);
2. every one of the 12 files is pinned by a descriptor-relative, no-follow open and
   judged on its metadata alone: regular file, one link, caller or root owner,
   not group- or world-writable, not executable, same device and mount as the
   directory, and its stat size inside its own bound and inside the 4 MiB total;
3. the listing, the directory's identity and every pinned descriptor are
   re-checked against their names, so a file deleted, added, renamed, replaced or
   chmod-ed since the listing refuses here;
4. only then are the pinned descriptors read, each for exactly its stat size, with
   an end-of-file probe and an unchanged-metadata check per file;
5. the listing, the directory and every name are checked once more.

A missing, extra or metadata-unsafe file that is visible before traversal
therefore stops the read at zero payload bytes. A file that visibly changes while
it is read fails as unstable (grew, shrank, changed, was replaced), not later as
a manifest mismatch.

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
- a race first observable during or after traversal may consume bounded bytes
  (at most 4 MiB) and then rejects with no output;
- a race that lands after the captured bytes' final observation can yield the
  already-bound snapshot of those bytes, so the artifact is valid evidence of
  what was read, not of the source's current state;
- a later `verify-rehearsal` against the changed source rejects.

Other rules:

- flat only: no nested directory, symlink, hard link, FIFO or special file,
  executable file, mount crossing, writable ancestry, or alias of the request
  or output;
- at most 4 MiB in total, `reads.json` at most 64 KiB, and a smaller bound per
  file (the contract lists each);
- JSON is strict, canonical, ASCII, at most 8 levels deep, with no duplicate
  keys, floats, non-finite numbers or booleans where integers belong;
- the files and the tree must not change while they are read; this is a
  requirement on the caller and a best-effort check, not an enforced guarantee
  (see the limitation above).

Diagnostics never echo an input value: they name a file, field or rule, so an
identifier planted in an input cannot leak through an error. The same holds for
names. An unknown entry in the reads is reported by count (`2 extra, 1 missing`),
never by name. A rehearsal tree under `verify-rehearsal` (and the tree built
inside `rehearse`) is untrusted too: the shared tree reader's, the entry
comparison's and the collector's capture-read errors are replaced at the session
boundary by fixed text such as `rehearsal tree failed safe inspection (code
symlink)`, `rehearsal has 2 unexpected paths (names withheld)` or `rehearsed
capture was refused by the collector's read (code capture-rejected)`. Only
names the contract itself fixes (the closure, the expected output paths) can
appear.

## Transformations

| Op | Input | Derivation |
| --- | --- | --- |
| R1 | two explicit source records, each a subset of six observed facts | the facts both records hold are compared; any difference, or no overlap, rejects; `sources_agree` is derived and never accepted; the two records must cover every fact, and nothing is filled from the expected identity |
| R2 | `synthetic-gpt-projection-v1`: `sector_bytes`, `disk_lbas`, rows of `name`, `first_lba`, `last_lba`, `simulated_bootable` | size is `(last - first + 1) * sector_bytes`; suffix from the name; recovery from the name; rows must be in ascending `first_lba` order, unique, non-overlapping and inside the disk; output is sorted by name; flags are copied, never inferred |
| R3 | explicit header summaries, in the collector's R3 row form | copied as supplied; `header_sha256` is an unverified fixture claim; every R2 partition that names a boot image needs a present row, and an absent row is only accepted where R2 lacks the partition; a missing row never means absent |
| R4 | explicit selection record | copied; the board id and revision are both set or both null; no selection is inferred |
| R5 | strict TSV: module name, tab, taint flags | file order is kept; indexes are line positions (not historical load chronology); names repeat if equal after treating `-` and `_` alike; the declared-order flag is recomputed |
| R6 | purpose-specific JSON: GPT name, filesystem, mount options, `block_size`, `allocation_unit_bytes`, `block_count`, `free_block_count` | totals are `block_count * allocation_unit_bytes` and free is `free_block_count * allocation_unit_bytes` (the free-block count, `f_bfree`), each floored to 1 MiB; `ro` with `rw` rejects; sizes above 2^50 or below 1 MiB reject |
| R7 | one release line, bounded notes bytes, command line, bootconfig | release parsed; notes hashed (the bytes are not kept); the command line is space-separated tokens and the bootconfig is one `key=value` per line; only keys and values the request lists are accepted; quoting, escapes, comments, nesting, unknown or duplicate keys, and unlisted values reject rather than being filtered |

Every operation document uses the collector's current envelope (`schema`,
`kind`, `id`, `request_sha256`, `transport`, `read_only`, `bytes_read`, `data`)
and is checked with the collector's `validate_operation` and `cross_check`
before anything is published. A wrong codename, notes hash or slot therefore
fails in the collector, not in a copy of its rules.

`bytes_read` is the exact number of fixture payload bytes an operation
consumed, excluding `reads.json` and any verification re-read. It is fixture
accounting only.

## Coverage and unresolved claims

The contract and every rehearsal classify each emitted field:

| Class | Meaning |
| --- | --- |
| `parsed-bytes` | derived by this tool from raw fixture bytes (R5, and R7's release, notes hash, command line and bootconfig) |
| `synthetic-projection` | derived from an explicit synthetic record by arithmetic and rules (R1, R2 sizes, names and recovery, R3 and R4 identity fields, R6) |
| `unverified-source-claim` | supplied by the fixture with no bytes behind it: R2 `bootable_flag`, the R3 header fields and hash, the R4 counts and board pair |

`rehearsal.json` lists every `unverified-source-claim` as an unresolved claim.

## Rehearsal artifact

Exactly these entries, deterministic, mode 0644 files in 0755 directories:

```text
manifest.json
rehearsal.json
SHA256SUMS
capture/capture.json
capture/operations/R1-identity-and-slot.json  ...  R7-kernel-identity-revalidation.json
```

`capture/` is the capture fixture, byte for byte what `myron-collect collect
--capture` reads; it is never reshaped for the collector. `manifest.json` and
`rehearsal.json` bind the session contract, the capture contract, the preflight
contract, the request hash, the `reads.json` hash and the capture digest, and
state `synthetic: true`, `live: false`, `executes: false`,
`kit_snapshot_reverified: false`, empty `remote_commands`, all nine authority
flags `false` and all seven blockers `missing`, with the coverage table, the
unresolved claims, the limitations and the non-goals.

`verify-rehearsal` recomputes every byte from the original request and reads and
compares the tree exactly, then reads `capture/` through the collector's own
`read_capture`. A matching `SHA256SUMS` is never enough: a tampered file with a
re-sealed checksum list is refused.

## Session contract

`device/myron/session-contract.json` (0.1.0) is derived and canonical; the tool
refuses any other bytes. It binds:

- the preflight contract (0.2.1) and the capture contract (collector 0.1.0)
  hashes, and the deployment, snapshot and kernel-reference hashes they carry;
- the session implementation digest: `tools/myron-session` is a minimal loader
  (the same pattern as `myron-collect`) that reads `tools/lib/myron-session-impl.py`
  once with no symlink following, hashes those bytes and executes the same bytes,
  so a replaced or restored file cannot claim the pin;
- the fixed raw-tree schemas, the parser and derivation registry, the limits,
  the exact output closure and accounting rule, and the coverage classes;
- `synthetic: true`, `live: false`, `executes: false`,
  `kit_snapshot_reverified: false`, empty `remote_commands`, every authority flag
  `false`, all seven blockers `missing`, and the limitations and non-goals.

The collector, preflight, snapshot and deployment tools are imported in-process
as **trusted, version-pinned dependencies**. They are pinned by version, not by
bytes: this contract does not make their execution byte-pinned. The collector
implementation digest is bound only through the capture contract the session
contract pins. Changing any session constant, schema or registry row, or the
implementation bytes, changes the derived contract and every command refuses
the committed one until it is regenerated from the final source.

### Regenerating and comparing (fish)

`derive-contract` prints the contract the current source and pinned upstream
contracts derive. It does not read, write or replace anything. After any edit to
`tools/lib/myron-session-impl.py` (or an upstream contract it pins):

```fish
set derived (mktemp)
tools/myron-session derive-contract > $derived
cmp $derived device/myron/session-contract.json        # silent: nothing to do
cp $derived device/myron/session-contract.json          # differs: take the derived bytes
tools/myron-session show > /dev/null                   # verifies the committed bytes
rm $derived
```

Review the diff of `device/myron/session-contract.json` like any other change:
the derived bytes are the only accepted ones, so a contract edited by hand is
refused. `tests/myron-session` fails if the committed file is not byte for byte
the output of `derive-contract`. The command authorizes nothing: it only shows
what `show` will accept.

## Safety and publication

The tool starts no process and has no network, archive, decompression or
broad-copy facility. The reads tree has its own flat reader (see Synthetic reads); the rehearsal
trees use the deployment tool's trusted tree reader, and publication uses its
`publish` (private same-parent temp directory, `renameat2(RENAME_NOREPLACE)`).
The request and reads are protected inputs: an output inside, equal to or
aliasing either is refused, and both are gathered again with the rehearsal
recomputed inside `verify_built`, which also runs the collector's `read_capture`
on the built tree. A difference observed by that gather, or a collector
rejection, aborts the run and normally leaves no output. The descriptor-read
snapshot limitation above still applies: a source change after its final
observation can yield the already-bound snapshot, and a publication failure
whose identity-bound cleanup also fails can leave an output while reporting
failure.

## Limitations and boundary

- The reads are synthetic projections. Nothing shows a real phone, GPT, boot
  image or device tree would produce them.
- No GPT, Android boot image or device-tree parser exists here; a real one needs
  its own gate and its own qualification against real captures.
- R3 header values and the R4 selection are claims, not parsed values.
- R5 order is the fixture file order, not historical load chronology.
- The R7 projections are deliberately narrow, not full command-line or
  bootconfig parsers.
- The dependency imports are version-pinned, not byte-pinned.
- The reads are a validated descriptor-read snapshot, not an atomic or
  writer-excluded filesystem snapshot; a mutation first observable after
  payload traversal can consume bounded bytes, and a later verification against
  a changed source rejects (see Synthetic reads).
- Publication is durable only if `fsync` of the output parent succeeds; a
  failure there is a `publish-rejected` refusal with a best-effort removal of
  the just-published output. If that removal also fails the output can remain
  while the command reports failure.

A passing rehearsal says only that the adapter and the collector agree on
synthetic structure. A live transport, a real format parser and the human
approval of one bounded read-only session remain separate, later, reviewed
gates, and all seven blockers remain open.
