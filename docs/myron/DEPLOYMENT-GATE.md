<!-- SPDX-License-Identifier: MIT -->
# Myron deployment gate (Phase 2.5, runtime 2.7, ABI 2.8/2.11)

Status (2026-10-24): laptop-only, offline, deterministic. `tools/myron-deployment`
builds and verifies a **deployment-candidate kit** and then **always refuses to
authorize deployment**. The kit is not bootable, not flashable, not image-ready,
not an atomic-snapshot proof, not hardware-qualified, and not a deployment
authorization. No kit has been built from the real qualified archive: `out/repo`
is empty and the archive and private runtime assets are external. As of
`myron-deployment` 0.2.0 the tool can bind a runtime-asset closure by hashes
only, but **no real runtime tree has been bound**; every real run so far, if any,
would be `not-bound`. Version 0.4.0 can also bind the staged-set ABI
verifier report from the exact archive and two exact symvers files. No real
archive or symvers pair has been bound. Standard AArch64/GKI layouts have
synthetic coverage, but the parser remains unqualified on real modules.
The current tool also provides a local-only writer for the exact required
private runtime closure. This does not change the 0.4.0 kit format and does not
put those bytes in a kit, package or release.

## What it binds

`device/myron/deployment-contract.json` is derived, never hand-edited. It pins
the SHA-256 of three canonical components:

| Component | Path |
| --- | --- |
| kernel reference | `device/myron/kernel-contract.json` |
| stage contract | `device/myron/stage-contract.json` |
| GPU profile reference | `packages/omamobile-myron-gpu-profile/reference.json` |

and records: the device identity; the rootfs requirements and digest algorithm
(`myron-rootfs-tree-v1-sha256`); the module archive hash, the file count (the
selector plus seven modules) and the public Attempt79/VT staging order, with
load semantics status `unverified`; the private runtime manifest hash, the
required features `gpu`, `wifi`, `touch`, and `bytes: external-private`; the
permanent blocker list; and the flags `deployment_authorized`, `bootable`,
`flashable`, `image_ready`, all `false`. Loading rejects duplicate keys,
unknown fields, non-finite numbers, a boolean where an integer belongs, and any
non-canonical rendering.

## Commands

All paths are canonical absolute paths: no `/`, relative, `.`, `..`, empty
components or symlinks. No command runs an external program or `depmod`.

| Command | Effect |
| --- | --- |
| `show` | print the validated contract |
| `stage-modules --assets ARCHIVE --out DIR` | validate archive and contract with the kernel verifier, then write exactly the selector and seven modules (planned paths and modes) |
| `stage-runtime --runtime-assets SOURCE_DIR --runtime-manifest FILE --out DIR` | traverse the bounded private source, validate the pinned manifest, and publish only the required `gpu`, `wifi` and `touch` closure with private storage modes |
| `assemble --rootfs-stage DIR --rootfs-manifest FILE --module-stage DIR --assets ARCHIVE --runtime-assets none\|DIR [--runtime-manifest FILE] --vmlinux-symvers none\|FILE --module-symvers none\|FILE --out DIR` | validate both inputs against the archive, bind or explicitly not-bind runtime and ABI evidence, reject collisions, write the kit |
| `verify --kit DIR --rootfs-stage DIR --assets ARCHIVE --runtime-assets none\|DIR [--runtime-manifest FILE] --vmlinux-symvers none\|FILE --module-symvers none\|FILE [--rootfs-manifest FILE]` | recompute every binding, content, mode and closure, including runtime and ABI evidence |
| `gate` (same arguments) | `verify`, then print `artifact_verified: true`, `deployment_authorized: false` and the blockers |

The manifest defaults to `<rootfs-stage>.MANIFEST`, the name
`tools/build-rootfs --stage-only` writes.

A stage built from the unsigned development repository
([DEV-UNSIGNED.md](DEV-UNSIGNED.md)) is never accepted here: its MANIFEST line
`repository signatures: none (unsigned development build; not a release)` or the
marker `.omamobile-dev-unsigned` in its tree makes `assemble`, `verify` and
`gate` fail.

Writers publish only to a nonexistent `OUT`: the tree is written into a private
same-parent temp directory, verified complete, and published with
`renameat2(RENAME_NOREPLACE)`, reopened by identity, verified again, and checked
once more by name before success. The output parent must be owned by the
invoking user and must not be group- or world-writable. Every ancestor must be
root- or invoking-user-controlled and protected from other-user rename; a
sticky directory is accepted only when it protects an invoking-user-owned next
component. Concurrent processes running as that same user are inside the trust
boundary, as they can mutate any finished kit too. Failure cleanup considers only path/inode pairs created by
the run and never follows links or mounts. `OUT` may not lie inside an input.
`verify` and `gate` apply the same ancestry/ownership boundary to the named kit
and require every kit descendant to be root- or invoking-user-owned and not
writable by group/other. They re-open the canonical path after verification to
confirm the inode did not change.

Publication is reported successful only after `fsync` of the output parent
succeeds. If that `fsync` fails (for example `EIO`), `publish` raises a
`DeploymentError` instead of returning, and removes the just-published output
only if the name still resolves to the inode this run created; a pre-existing
path is never touched. The durability error is never swallowed. Residual
limit: if that best-effort removal also fails (the filesystem is already
failing), the output may remain on disk even though the command reported
failure, and the removal itself is not made durable.

## The kit

`contracts/` (the four canonical JSON files), `overlay/` (the module overlay at
its target paths and modes), `kit.json`, `status.json`, `STATUS.txt` and
`SHA256SUMS`. The rootfs stays outside: it is bound by a deterministic digest
(path, type, mode, size, content hash and symlink target of every entry; no
owner, time or hardlink identity) and by the manifest hash. Runtime assets stay
outside; the kit holds only the `runtime_assets` evidence described below, never
a runtime byte or the manifest. Symvers files also stay outside; `kit.json`
holds only the strict `abi` evidence described below. There are no timestamps;
two runs give identical bytes.

## Runtime-asset binding (0.2.0)

`--runtime-assets` is required by `assemble`, `verify` and `gate`: the literal
`none`, or a canonical absolute runtime root. `--runtime-manifest` (the pinned
private TSV, canonical absolute path) is required with a root and rejected with
`none`. `kit.json` (never `status.json`) gets a strict `runtime_assets` object:

- `none` records `status: not-bound`, `asset_count: 0`, `files: []`,
  `digest: null`, plus the algorithm `myron-runtime-assets-v1-sha256`, the
  contract's manifest hash and required features, and
  `bytes_copied_into_kit: false`.
- A root records `status: verified`, the sorted rows (`target`, `sha256`, `size`,
  `mode`, `feature`, `provenance`) and a digest over the algorithm, the pinned
  manifest hash, the required feature order and those rows.

The manifest is opened through trusted, descriptor-relative no-follow ancestry,
must be singly linked and not group/world-writable, and is parsed from one
bounded, stable byte capture against the contract's pinned hash using the kernel
verifier's TSV schema. Its pinned inode and canonical path are rechecked after
the runtime walk. Its parent-directory identity may not alias the runtime root,
rootfs, module stage or kit through another path or bind mount. Rows of the
required features `gpu`, `wifi`, `touch` must each be `stock-extracted` and
`extract-only` with a target below
`/usr/local/lib/myron-`; anything else fails closed. Optional rows are ignored
and must not exist in the tree. The root is read by the existing
descriptor-confined walk (trusted ancestry and ownership, no symlinks, hardlinks,
special files, mount or device crossing, no unstable reads; bounds 256 entries,
depth 12, 256 MiB per file, 1 GiB total). It must contain exactly the selected
targets and their parent directories. All asset hashes and the digest come from
that single walk; no asset file is reopened and no byte is retained in the kit.

A kit assembled `verified` is verified or gated only with its root and manifest
and the evidence must recompute equal; a kit assembled `not-bound` is verified or
gated only with `none` (a root is rejected: reassemble). The output may not lie
in, contain or alias the runtime root, its manifest or any other input.

This is hash binding of a tree. It is not provisioning, extraction,
redistribution clearance, ABI compatibility or hardware qualification. It does
not clear `private-runtime-asset-bytes-not-bound-to-kit` or reorder any blocker,
and the gate still refuses. The gate reports `runtime_status`,
`runtime_asset_count` and `runtime_digest`.

`stage-runtime` is the local preparation step for a source tree that also
contains optional features. It safely traverses the complete source under the
same bounds, retains only the selected manifest bytes, validates their hashes,
and atomically publishes an exact no-replace closure. Optional files never
enter the output. Staged ancestors use mode `0700`, files use `0600`, and the
stage root created by the common publisher uses `0755`; these are private
storage modes, not final installation permissions. Assembly recomputes its
digest from those normalized modes. Source and manifest paths remain pinned and
are rechecked during both pre- and post-publication verification.

The staging output contains private, `extract-only` bytes. Keep it in a
dedicated access-controlled local directory, for example
`/absolute/private/myron-runtime-stage`, and never commit, package, publish or
redistribute it. `out/` is ignored by Git but is not a secrecy boundary.
Staging proves only that the selected closure matches the pinned manifest; it
does not prove an atomic source snapshot, ABI compatibility, redistribution
rights, hardware operation or deployment authorization.

## Staged-set ABI binding (0.4.0)

`--vmlinux-symvers` and `--module-symvers` are required by `assemble`, `verify`
and `gate`. They must both be the literal `none`, or both be canonical absolute
regular files. `none` records strict `status: not-bound` evidence. With files,
the tool opens each through trusted descriptor-relative no-follow ancestry,
requires one link and safe ownership/mode, rejects file mount points and path
or input-tree collisions, captures each file once with bounded stable reads,
and rechecks both pinned inodes and canonical paths after verification.

The existing kernel verifier runs in-process over those captured bytes and the
same archive bytes already proven against the module stage. `kit.json` records
only a fixed summary and hashes: `status: staged-set-consistent`,
`scope: staged-set-only`,
module hashes and dependency counts/order, a SHA-256 of the canonical full
verifier report, and a separate evidence digest. Symvers bytes, symbol names,
paths and full import/export tables are not copied into the kit. `verify` and
`gate` must receive the same mode: a bound kit requires both files and
recomputes equal evidence; a not-bound kit requires both literals `none`.

This proves only consistency of the staged module set under a parser whose
standard AArch64/GKI layouts are covered by synthetic fixtures only.
`vendor_modules` remains `not-verified`, the parser remains
`linux-gki-layouts-offline-unqualified-on-real-modules`, activation remains disabled,
the overlay order remains `unverified`, and
`module-abi-import-and-load-order-not-verified` remains in the unchanged
seven-item blocker list. The gate reports `abi_status`, `abi_scope`,
`abi_module_count` and `abi_digest` and still refuses.

## Rules enforced

- **Rootfs**: equivalent to `tests/rootfs-stage` (required files, stage marker
  and manifest lines, firmware allowlist, `/lib` alias, empty `usr/lib/modules`,
  an absent or empty real `/boot`, no vendor/activation paths, and no known
  kernel/module/boot payload names anywhere). Files whose names begin with
  `Image` are admitted only when their race-checked first 64 bytes do not carry
  the arm64 `ARMd` magic at offset 56; symlinks with those names are rejected.
  GPU checks use bytes and hashes captured by the same bounded tree pass that
  produces the rootfs digest. A missing
  symlink target is allowed only for a relative link below `/etc/skel` whose
  normalized target is below `/etc/skel/.local/state/omarchy`; all target
  ancestors that exist must be real directories. Installed kernel, stage and
  GPU references must be byte-identical to the contract. Other symlinks are
  recorded and never followed; hardlinks are rejected.
- **Module stage and kit**: exact closure; symlinks, hardlinks and special files
  rejected; modes exact; selector equals the qualified candidate selector;
  modules carry the exact release marker.
- **Every tree**: no mount-point (Linux mount ID) or device crossing, bounded
  entries, depth and bytes, descriptor-relative `O_NOFOLLOW` opens, and
  rejection of files or directories that change while read.
- **Collisions**: the overlay destinations may not exist in the rootfs.

## Limits (read these)

- `--assets` is mandatory for assembly, verification, and gating. The archive
  stays external, but every accepted overlay must match its qualified plan.
- The module order is the public Attempt79/VT staging order; load semantics
  remain unverified. Bound ABI evidence is staged-set-only, uses a parser not
  qualified on real modules, and excludes the vendor module inventory. It is
  not full ABI, provider, or load-order proof.
- Runtime assets are bound only by hash evidence, and only when a root is
  supplied; no runtime or manifest byte is copied into the kit, and the kit is
  not proof that those files are the ones ever deployed. The blocker stays until
  a real, separately reviewed bound kit and a contract revision say otherwise.
- The rootfs directory and manifest are ordinary external paths, not an atomic
  filesystem snapshot. They must be quiescent while a command runs. This is why
  `atomic-snapshot-and-rollback-not-proven` remains a permanent blocker.

Phase 2.9 adds a separate metadata-only snapshot candidate around a fully
re-verified kit and its pre-deployment rootfs digest. Its rollback rehearsal is
read-only and deliberately cannot record a capture, quiescence, atomicity or
successful restore. It does not alter this kit format or clear the blocker.
See [SNAPSHOT-GATE.md](SNAPSHOT-GATE.md).

## Permanent blockers

The gate refuses while these hold, and this tool can clear none of them:

1. `kernel-source-lock-reproduction-not-verified`
2. `module-abi-import-and-load-order-not-verified`
3. `private-runtime-asset-bytes-not-bound-to-kit`
4. `atomic-snapshot-and-rollback-not-proven`
5. `no-bootable-image-or-captured-boot-chain`
6. `composed-kit-not-hardware-qualified`
7. `no-independent-deployment-review-or-authorization`

Any kit or status file that claims authorization, omits a blocker or adds a
field is rejected. Tests: `tests/myron-deployment` (synthetic fixtures only).
