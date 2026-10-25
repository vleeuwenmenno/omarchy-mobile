<!-- SPDX-License-Identifier: MIT -->
# Myron external kernel-source bundle identity gate (Phases 2.17 and 2.18)

Status (2026-10-25): offline, read-only. `tools/myron-kernel-source` 0.2.0 checks
that a user-supplied private directory holds exactly the seven files that
[`kernel-contract.json`](../../device/myron/kernel-contract.json) and
[`kernel-source-contract.json`](../../device/myron/kernel-source-contract.json) name,
byte for byte (`verify`), and can then classify the structure of the four pinned patch
bodies against a named profile (`analyze-patches`, Phase 2.18). In `verify`,
"structure" means closure, source-lock and manifest shape and the pinned patch order;
`verify` never examines a patch body. Neither command proves applicability,
availability or build correctness.

## What this repository ships

**No bytes of the bundle are distributed.** The repository holds the contract
(sizes and SHA-256 values), the verifier and tests built from synthetic
fixtures. The private bundle is not in the repository, in a package, or in a
release. The deferred stash that once held a copy of it is **not a deliverable**
and its files must not be published or copied into `device/myron/kernel-source`.
Publication and licensing of the bundle's contents are **unresolved**: that
decision is separate and blocks any distribution of the bundle.

## Commands

| Command | Effect |
| --- | --- |
| `show` | Validate the contract and its kernel-contract binding, then print the contract. |
| `plan` | Print a value-free outline of the input closure and checks. |
| `verify --root ABSOLUTE_PRIVATE_ROOT` | Verify the bundle at the root. Output is buffered and printed only after every check passes. |
| `analyze-patches --root ABSOLUTE_PRIVATE_ROOT` | Run the full `verify` identity check, then analyze the same captured patch buffers against the patch structure profile. Output is buffered and validated before it is printed. |
| `--version` | Print `0.2.0`. |

There are no other arguments, overrides, environment paths or test switches.
`show` and `plan` need no private root.

Exit codes: `verify`, `show` and `plan` exit 0 or fail as below. `analyze-patches`
exits 0 when every patch matches the profile and 3 when the identity matched and at
least one patch does not (complete JSON on stdout, empty stderr in both cases).
Any identity or security prerequisite failure, and any unexpected internal error,
exits 1 with empty stdout and the single stderr line `myron-kernel-source: E_REFUSED`.
Misuse exits 2 with empty stdout and `myron-kernel-source: E_USAGE`. Neither line ever
carries a path, a value, an identity or a traceback.

## Binding

The contract has schema `1` and version `0.2.0` and independently binds the
exact bytes of `device/myron/kernel-contract.json` (SHA-256
`80321c737de5dd4ac7a671a83453c225ae23b7c2c1313e6cba0f8811ddcc8193`). Six hashes
(lock, manifest and four patches) are derived from that kernel contract and
cross-checked against the contract's own pins. `vt.fragment` is a **new pin**
that exists only here. The kernel contract, the package reference and stage
contract, and every deployment, snapshot, preflight, capture, session and
bootchain contract are unchanged.

## Closure

The root is a private directory (mode `0700`) holding exactly:

- `source-lock.json`, `stamped-manifest.xml`, `vt.fragment`
- `patches/` (mode `0700`) with `0001-bluetooth-qca-preinitialized-ibs.patch`,
  `0002-bluetooth-qca-vote-msm-geni-uart-clock.patch`,
  `0003-gki-export-rmnet-module.patch` and
  `0007-ipc-export-namespace-symbols.patch`, in that order, target `common`.

`0007` is pinned and verified here; `0004`, `0005` and `0006` are excluded and
are not part of the closure, so their presence is refused as an extra entry.
Files are regular, mode `0600`, owned by the caller, with one link and no
executable bit. Extra files, extra directories and missing entries are refused.

## Source-lock and manifest profile

The lock must have exactly the keys `schema`, `qualification`,
`manifest_revision`, `superproject_revision`, `source_overrides`, `projects`
and `links`; `schema` is the integer `1` (not a boolean). The qualification
string is compared by digest and is never printed. It must hold exactly 50
projects with unique, non-overlapping, safe ASCII paths (at most 256 bytes),
unique canonical `android.googlesource.com` HTTPS URLs without userinfo, port,
query, fragment or escapes, and lowercase 40-hex revisions. Exactly two
overrides (`common`, `build/kernel`) must match their project revisions, and
`common` must equal the kernel contract's `gki_source_revision`. Exactly four
links need unique safe paths and targets that do not collide with or sit above
or below projects or other links; each target is a checkout-root path inside
exactly one project. Nothing is created or opened for the links.

JSON is parsed strictly: duplicate keys, invalid UTF-8, a byte order mark,
non-finite numbers, floats, wrong types, unknown fields and nesting beyond
depth 8 are refused.

The manifest must be the exact XML declaration and a `manifest` root with
exactly two `project` children (`common` as `kernel/common`, `build/kernel` as
`kernel/build`) carrying only `path`, `name` and `revision`, which must agree
with the lock and overrides. DTDs, entities, includes, namespaces, comments,
processing instructions, CDATA and other text or children are refused, and
nothing external is resolved.

## Filesystem handling

The root must be an absolute path with no relative, root, `.`, `..`, repeated or
trailing components. Every component is opened without following symlinks,
through descriptors. Ancestors must be owned by the caller or root and not group
or other writable (a root-owned sticky directory such as `/tmp` is accepted); a
separately mounted trusted home ancestor is not rejected. Inside the bundle
every directory and file must be on the root's mount, read from
`/proc/self/fdinfo`; the check fails closed when that is unavailable.
Directory enumeration stops after one entry more than expected. Each file is
read once at its pinned size plus one byte, and the same captured bytes are
hashed and parsed. Metadata, names and directory membership are rechecked after
reading to catch replacement, chmod, rename and extra-entry races.

Bounds: invocation 512 KiB in total, contract and lock 64 KiB, manifest and
fragment 4 KiB, patches 64 KiB each, JSON depth 8, output 64 KiB. `analyze-patches`
adds no read: it receives the buffers `verify` captured and never reopens or rereads
a patch file.

### Limitations

- There is no atomic snapshot of the bundle: a writer can change it between
  the rechecks and the process exit.
- A writer running as the same user, or a privileged writer, is not defended
  against.
- A successful `verify` is a point-in-time check of the bytes this process read.

## What a pass means

`verify` reports `private-bundle-identity-matched` with scope
`identity-closure-lock-manifest-and-patch-order-only`: the private bundle matches
the pinned identities, closure, lock, manifest and patch order. It succeeds for an
identity-matched patch that is malformed or noncanonical, because it does not read
patch bodies. All authority flags stay `false`,
activation stays disabled and the blocker is unchanged. It does **not** verify:
that any project is still downloadable, that any revision descends from another,
that a patch applies to `common`, that `vt.fragment` is used by any build, that a
toolchain exists, or anything about build output. The source-lock reproduction
stays `not_verified` in the kernel contract.

## Patch structure analysis (Phase 2.18)

`analyze-patches` is a **structural** check of already captured bytes. It does not
prove that a patch applies to `common`, that `common` is obtainable, that any
revision descends from another, or that anything builds, and it applies nothing.
Its only claim is `patch_structure_admission` against the contract's
`patch_structure_profile` (`myron-patch-structure-v3`); `patch_applicability` and
`application_performed` stay `false`.

Order of work: the full `verify` identity, security and closure checks run first.
Only if they pass does the pure function `analyze_patch_series(patches, profile)`
receive the four captured buffers (the same objects, no I/O) and return allowlisted
metadata. The document is validated against a strict allowlist before it is printed.

### Profile

- Exactly 4 ordered artifacts, each at most 64 KiB, 1 to 16 file sections and 1 to 64
  hunks per artifact, at least one modifying hunk per file section.
- ASCII with LF line ends only (no NUL, no CR), at most 8192 bytes per line, paths at
  most 256 bytes, numeric fields at most 10 digits with value at most 2^31-1 and no
  leading zeros. Payload bytes are never interpreted or reported, but must meet the
  byte rules.
- Either a **bare** git unified diff of modifications, unchanged, or that diff inside
  one of two narrow envelope variants (see below). Anything else before the diff, and any
  unconsumed text after it, is `unsupported`; the parser never scans for a later diff.
  A file section is `diff --git a/REL b/REL`, an optional `index` line (hex ids, an
  optional mode that must be `100644` or `100755`), `--- a/REL`, `+++ b/REL` and
  hunks. `REL` is a relative path of printable ASCII (no space, quote or backslash)
  with no empty, `.`, `..` or `.git` component, identical in all four places. No other
  extended header, no new, deleted, renamed or copied file, no binary or combined
  diff, no mode change or mode-only section, no symlink or submodule mode.
- Hunks are `@@ -S[,C] +S[,C] @@` with an optional ` TEXT` section. A missing count is
  1; zero counts are allowed. The body is consumed by the declared old and new
  counts, so header-looking payload stays payload, and `\ No newline at end of file`
  is legal only directly after a body line. The "ended" state of each side persists
  across all hunks of one file section (including a marker after the final counted line)
  and resets only at the next file section: a later hunk that consumes an ended side is
  `marker-placement`.

### Envelope (`myron-patch-structure-v3`)

An envelope is selected only at byte zero, deterministically by the first line: exactly
`From ` + 40 lowercase hex + ` Mon Sep 17 00:00:00 2001` selects the **mbox** variant;
a first line starting exactly `From: ` selects the **header-only** variant. Nothing is
searched for, resynchronized or backtracked afterwards; any other first line that is not
`diff --git` (including near misses such as `From:x`, `from: `, ` From: `) is
`wrapper-or-prologue`. v3 only adds the header-only variant; the mbox variant is
unchanged.

```
artifact  := bare-diff EOF | envelope diff-sections ending
envelope  := mbox-env | header-only-env
mbox-env  := mbox-line headers LF message "---" LF stat-block?
header-only-env := from-field date-field? subject-field LF message "---" LF stat-block?
headers   := from-field date-field subject-field
from-field := "From: " OPAQUE LF cont*   date-field := "Date: " OPAQUE LF cont*
subject-field := "Subject: " OPAQUE LF cont*
cont      := (SP | HTAB) OPAQUE LF
OPAQUE    := nonempty printable ASCII and HTAB
message   := lines of printable ASCII, HTAB or nothing, up to the first exact "---" line
stat-block:= 1..16 rows, one summary, one empty line, then immediately "diff --git"
ending    := EOF | "-- " LF VERSION LF EOF         (VERSION: 2..4 numeric components of 1..3 digits)
```

- Headers appear in that order, once each; `Date` is optional only in the header-only
  variant (the mbox variant requires all three). Unknown, extra, duplicate or reordered
  headers are `envelope-header`; `MIME-*` and `Content-*` are `mime-encoding`.
- The first exact `---` line is the separator and is never retried. It must be followed
  at once by `diff --git`, or by an exact stat block followed at once by `diff --git`.
  A diff-looking line before the separator is message text. Anything else after it
  (cover letter, unknown block) is `no-diff-envelope`; a PGP block in the message is
  `pgp-signature`.
- Stat rows are ` REL | COUNT` with an optional ` +++---` graph; the summary is
  ` N file[s] changed` with optional `, N insertion[s](+)` then `, N deletion[s](-)`
  (one leading space, as git prints it). Only framing is checked, never agreement with the
  hunks. Other lines after the summary are `unknown-stat`.
- The ending is recognized only after at least one complete file section and outside a
  hunk. Custom signatures are `unknown-footer`; extra blank lines, messages, a second
  envelope or complete trailing line are `trailing-text`. The line reader reports a
  missing final LF as `truncated` before footer classification; `bad-footer` is reserved
  for a complete `-- ` line with no following version line. An invalid ending overrides
  provisional coordinate results: the entry is not parse-complete, counts are `null`
  and no grouping is reported.
- Bounds: the prelude (everything before the first `diff --git`, headers and stat
  included) is at most 16 KiB and 256 physical lines (`envelope-bytes`,
  `envelope-lines`); at most 32 header lines including continuations (`header-lines`);
  at most 16 stat rows (`stat-rows`). The line, path, numeric and 64 KiB artifact bounds
  apply unchanged. The first failing check decides, in reading order.
- Framing and bounds only: author, address, date, subject, message and commit id are
  not interpreted, decoded, retained, hashed or emitted, and the output schema gains no
  envelope field. Acceptance proves a named framing match, not authorship, authenticity,
  provenance, that git produced it, the message, the diffstat or applicability.

### Coordinate policy (`cumulative-boundary-v1`)

For a range `(start, count)` the boundary is `start - 1` if `count > 0`, else
`start`. Within each file section the expected new boundary of a hunk is its old
boundary plus the sum of `new_count - old_count` over the earlier hunks of that
section. Old and new ranges must be monotonic and non-overlapping. The running
delta starts at zero for every file section and every artifact and never carries
across the series. Paths shared by several artifacts only establish repeated-file
participation; that implies no dependency, ordering or applicability.

### Classes and exit codes

| Class | Meaning | Parse complete |
| --- | --- | --- |
| `conformant` | Matches the profile | yes |
| `noncanonical` | Grammar and counts understood; coordinates, ordering, duplicate sections or no modifying hunk fail | yes |
| `malformed` | Recognized grammar broken, truncated or counts disagree | no |
| `unsupported` | A feature outside the profile, or unconsumed text | no |
| `limit-exceeded` | A bound stopped the analysis; never admitted | no |

Analysis of one artifact stops at the first malformed, unsupported or limit
condition, so those classes carry exactly one reason code; `noncanonical` can carry
several. Counts (`file_count`, `hunk_count`) are `null` when the parse is not
complete. Reason codes come from a fixed list in the contract. Exit 0 means all four
are `conformant`; exit 3 means at least one is not.

### Output

`schema`, `kind`, `version`, `profile`, `scope` (`patch-structure-only`),
`bundle_identity` (`matched`), `structural_profile_matched`, `patches` (1-based
`patch_index`, `classification`, `parse_complete`, `file_count`, `hunk_count`,
`reason_codes`, and `repeated_file_group_count` only when every patch parsed
completely), `application_performed` (`false`), the full all-`false` authority map,
activation `disabled` with the blocker unchanged, and the `unverified` list including
`patch-applicability`. Paths, subjects, authors, annotations, coordinates, payload,
hashes, exceptions, other keys and suggested repairs are never emitted.

### Private-bundle result

The preserved private bundle passed the Phase 2.17 identity gate and was analyzed
with this profile from a transient runtime directory. Patches 1, 3 and 4 were
`conformant`; patch 2 was parse-complete but `noncanonical` with the fixed reason
`coordinate-mismatch`. Their reported `(file_count, hunk_count)` pairs were
`(1, 2)`, `(1, 7)`, `(1, 1)` and `(2, 4)`. Patches 1 and 2 participate in one
repeated-file group; patches 3 and 4 participate in none. The aggregate result was
therefore an identity match with `structural_profile_matched: false` and exit 3.

This records only value-free structural evidence. It neither identifies the shared
path nor establishes patch order, dependency, applicability, provenance, source
availability or build correctness. No patch was applied, every authority flag stayed
`false`, activation stayed disabled and the deployment blocker was unchanged.

### Limitations

- A match is relative to the named profile only; a mail file with any other header, MIME,
  a custom signature, or non-ASCII text is `unsupported` by design, not repaired.
- The identity limitations above apply unchanged: no atomic snapshot, no defense
  against a same-user writer.
