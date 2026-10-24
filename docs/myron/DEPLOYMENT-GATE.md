<!-- SPDX-License-Identifier: MIT -->
# Myron deployment gate (Phase 2.5)

Status (2026-10-24): laptop-only, offline, deterministic. `tools/myron-deployment`
builds and verifies a **deployment-candidate kit** and then **always refuses to
authorize deployment**. The kit is not bootable, not flashable, not image-ready,
not an atomic-snapshot proof, not hardware-qualified, and not a deployment
authorization. No kit has been built from the real qualified archive: `out/repo`
is empty and the archive and private runtime assets are external.

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
| `assemble --rootfs-stage DIR --rootfs-manifest FILE --module-stage DIR --assets ARCHIVE --out DIR` | validate both inputs against the archive, reject collisions, write the kit |
| `verify --kit DIR --rootfs-stage DIR --assets ARCHIVE [--rootfs-manifest FILE]` | recompute every binding, content, mode and closure |
| `gate` (same arguments) | `verify`, then print `artifact_verified: true`, `deployment_authorized: false` and the blockers |

The manifest defaults to `<rootfs-stage>.MANIFEST`, the name
`tools/build-rootfs --stage-only` writes.

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

## The kit

`contracts/` (the four canonical JSON files), `overlay/` (the module overlay at
its target paths and modes), `kit.json`, `status.json`, `STATUS.txt` and
`SHA256SUMS`. The rootfs stays outside: it is bound by a deterministic digest
(path, type, mode, size, content hash and symlink target of every entry; no
owner, time or hardlink identity) and by the manifest hash. Runtime assets stay
outside and are identified by the contract's manifest hash only; no private byte
is copied. There are no timestamps; two runs give identical bytes.

## Rules enforced

- **Rootfs**: equivalent to `tests/rootfs-stage` (required files, stage marker
  and manifest lines, firmware allowlist, `/lib` alias, empty `usr/lib/modules`,
  no vendor/activation paths, no kernel/module/boot payload names anywhere) plus
  GPU checks performed from bytes and hashes captured by the same bounded tree
  pass that produces the rootfs digest, plus byte-identity of the installed kernel
  reference, stage contract and GPU reference with the contract. Symlinks are
  allowed there only as recorded, never-followed entries; hardlinks are
  rejected.
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
  remain unverified. This is not full ABI, import, provider, or load-order proof.
- The tool reads no runtime asset bytes; they are not bound to the kit.
- The rootfs directory and manifest are ordinary external paths, not an atomic
  filesystem snapshot. They must be quiescent while a command runs. This is why
  `atomic-snapshot-and-rollback-not-proven` remains a permanent blocker.

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
