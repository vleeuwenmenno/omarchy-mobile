<!-- SPDX-License-Identifier: MIT -->
# Myron snapshot candidate gate (Phase 2.9)

Status (2026-10-24): laptop-only, offline, deterministic, and deliberately
non-authorizing. `tools/myron-snapshot` 0.1.0 binds a fully re-verified Myron
deployment kit to the pre-deployment rootfs-stage digest. It also defines a
read-only rollback acceptance check. It does not capture, copy, freeze, restore,
mount, boot, flash, deploy, or contact a phone.

This artifact is not a filesystem snapshot. Capture status is always
`not-captured`, quiescence is always `not-proven`, rollback status is always
`not-proven`, and every authority flag is false. All seven deployment blockers
remain unchanged, including `atomic-snapshot-and-rollback-not-proven`.

## Contract and commands

`device/myron/snapshot-contract.json` is a canonical derivative of the current
deployment contract. It pins that contract's SHA-256, the snapshot and rollback
algorithms, the only accepted 0.1.0 refusal states, the unchanged blocker list,
and false authority flags.

| Command | Effect |
| --- | --- |
| `show` | Print the validated snapshot contract. |
| `bind` | Recompute every deployment-kit binding, then publish a new metadata-only snapshot candidate. |
| `verify` | Recompute the kit and compare every snapshot binding and checksum. |
| `rehearse-rollback` | Read a candidate rootfs tree and compare its deterministic digest with the bound pre-deployment digest. |

`bind` and `verify` take the same verification inputs as
`tools/myron-deployment verify`: `--kit`, `--rootfs-stage`, optional
`--rootfs-manifest`, `--assets`, `--runtime-assets none|DIR`, the matching
runtime manifest when bound, and both symvers arguments as `none` or exact
files. `bind` also takes a nonexistent `--out`; `verify` takes `--snapshot`.
`rehearse-rollback` takes only `--snapshot` and `--tree`.

## Candidate contents

The published directory contains exactly:

- `contracts/snapshot-contract.json`
- `snapshot.json`
- `status.json`
- `STATUS.txt`
- `SHA256SUMS`

No rootfs, module, runtime asset, private asset, archive, symvers, firmware, boot
payload, or source byte is copied. `snapshot.json` binds:

- deployment-kit format and the SHA-256 of its canonical `SHA256SUMS` bytes;
- rootfs digest algorithm, digest, and manifest SHA-256;
- qualified module-archive SHA-256;
- runtime status, selected-file count, and evidence digest;
- ABI status, staged-set scope, module count, and evidence digest.

The capture record is fixed to a synthetic directory generation zero with
`not-captured` and `not-proven`. The rollback record is fixed to
`not-proven`. Verification rejects unknown fields, duplicate keys,
non-canonical JSON, altered blockers, changed bindings, changed refusal states,
or any true authority claim.

## Rollback rehearsal meaning

The rehearsal walks `--tree` read-only with the deployment tool's bounded,
descriptor-relative, no-follow traversal. It rejects hardlinks, special files,
mount/device crossing, and unstable reads. Entry modes are part of the digest;
ownership is deliberately outside version 1. It reports `digest-match` only
when the tree digest equals the pre-deployment rootfs digest.
Added overlay files necessarily change that digest.

Even a match reports:

```text
atomicity_proven: false
rollback_proven: false
deployment_authorized: false
```

It proves only equality under `myron-rootfs-tree-v1-sha256`. Version 1 covers
sorted path, entry type, mode, size, regular-file content SHA-256, and symlink
target. It does **not** cover owners, timestamps, xattrs, ACLs, file
capabilities, SELinux labels, or hardlink identity. Hardlinks are rejected, but
lost `security.capability` data would not change this digest. A future real
capture must use a revised algorithm or separately bind those properties.

## Publication and safety

The tool imports `tools/myron-deployment` in-process and requires version 0.3.0.
It reuses its strict JSON, trusted ancestry, stable bounded reads, tree digest,
input-alias checks, and same-parent `renameat2(RENAME_NOREPLACE)` publication.
No external process is started. Output must not exist, lie under an input tree,
or alias an input tree through another path or mount.

A real capture still needs a quiescence witness, filesystem/storage identity,
an immutable generation, an independently reviewed restore mechanism, and an
attended restored-tree qualification. This phase supplies the artifact shape
and acceptance predicate only; it clears no deployment blocker.

Phase 2.10's [PREFLIGHT-GATE.md](PREFLIGHT-GATE.md) consumes this identity and
the deployment kit to produce a refusal-only request for the next evidence
boundary. It does not change this format or grant hardware-read permission.
