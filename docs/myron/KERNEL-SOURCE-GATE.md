<!-- SPDX-License-Identifier: MIT -->
# Myron external kernel-source bundle identity gate (Phase 2.17)

Status (2026-10-25): offline, read-only, **identity and structure only**.
`tools/myron-kernel-source` 0.1.0 checks that a user-supplied private directory
holds exactly the seven files that [`kernel-contract.json`](../../device/myron/kernel-contract.json)
and [`kernel-source-contract.json`](../../device/myron/kernel-source-contract.json)
name, byte for byte, and that the structured ones have the expected shape. It
proves nothing else.

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
| `--version` | Print `0.1.0`. |

There are no other arguments, overrides, environment paths or test switches.
`show` and `plan` need no private root.

On failure the tool exits 1 with empty stdout and the single stderr line
`myron-kernel-source: E_REFUSED`. Misuse exits 2 with `myron-kernel-source: E_USAGE`.
Neither line ever carries a path, a value, an identity or a traceback.

## Binding

The contract has schema `1` and version `0.1.0` and independently binds the
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
fragment 4 KiB, patches 64 KiB each, JSON depth 8, output 64 KiB.

### Limitations

- There is no atomic snapshot of the bundle: a writer can change it between
  the rechecks and the process exit.
- A writer running as the same user, or a privileged writer, is not defended
  against.
- A successful `verify` is a point-in-time check of the bytes this process read.

## What a pass means

`verify` reports `private-bundle-identity-matched`: the private bundle matches
the pinned identities and structure. All authority flags stay `false`,
activation stays disabled and the blocker is unchanged. It does **not** verify:
that any project is still downloadable, that any revision descends from another,
that a patch applies to `common`, that `vt.fragment` is used by any build, that a
toolchain exists, or anything about build output. The source-lock reproduction
stays `not_verified` in the kernel contract.
