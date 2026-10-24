<!-- SPDX-License-Identifier: MIT -->
# Myron hardware-read preflight gate (Phase 2.10)

Status (2026-10-24): offline, deterministic, refusal-only.
`tools/myron-preflight` 0.2.0 consumes a fully re-verified deployment kit and
snapshot candidate and produces a bounded hardware-read **approval request**.
It executes no operation, collects no evidence, contacts no phone, and grants
no approval. No real request exists yet because no real kit or snapshot has
been assembled from the owner-supplied archive and runtime tree.

This is the final offline artifact before a separate, explicit approval for a
read-only evidence session. It is not that approval. Deployment, flashing,
booting, snapshot capture/restore, and hardware qualification remain later,
separate gates.

## Commands

| Command | Effect |
| --- | --- |
| `show` | Print the canonical refusal contract. |
| `assess` | Re-verify kit and snapshot, then publish a new approval-request artifact. |
| `verify` | Recompute all kit, snapshot, request, blocker, redaction, and refusal bindings. |

`assess` and `verify` take the same deployment inputs as
`tools/myron-snapshot verify`: kit, snapshot, rootfs stage and manifest, module
archive, runtime mode/tree and manifest, and the paired symvers mode/files.
`assess` takes a nonexistent `--out`; `verify` takes `--request`.

The request contains exactly:

- `contracts/preflight-contract.json`
- `request.json`
- `status.json`
- `STATUS.txt`
- `SHA256SUMS`

It contains no kit, snapshot, rootfs, module, runtime asset, private asset,
manifest, symvers, firmware, boot image, partition, or source byte.

## Refusal state

The contract pins the deployment and snapshot contracts, the exact seven
blockers, capture schema `myron-capture-evidence-v1`, and nine false authority
flags. Every request has:

```text
decision: refused-pending-live-evidence
human_approval_required: true
hardware_read_authorized: false
deployment_authorized: false
execution.operations: []
execution.evidence_collected: []
```

The request binds the deployment-kit and snapshot checksum identities plus the
rootfs digest/manifest, module archive, runtime status/count/digest, and ABI
status/scope/count/digest. Every blocker remains `missing`; every closure item
keeps `blocker_cleared: false`.

## Declarative read plan

The request names seven stable operations for a future separately approved
collector. These are identifiers and field allowlists, not shell commands:

| ID | Purpose | Maximum captured input |
| --- | --- | --- |
| `R1-identity-and-slot` | Two-source identity, verified-boot, and slot agreement | 64 KiB |
| `R2-gpt-and-recovery-inventory` | Partition names/sizes/flags and recovery presence, without GUIDs | 1 MiB |
| `R3-boot-image-headers` | Header fields and header hashes only | 64 KiB |
| `R4-dtb-dtbo-selection` | Selected DT/overlay facts and compatible prefix | 64 KiB |
| `R5-module-load-order` | Module names/order/taint only | 1 MiB |
| `R6-storage-and-mount-model` | Root GPT name, filesystem, options, rounded sizes | 64 KiB |
| `R7-kernel-identity-revalidation` | Release, notes hash, allowlisted boot fields | 1 MiB |

Every operation says read-only, uses the future transport name
`approved-read-only-recovery-session`, and stops on identity mismatch,
two-source disagreement, a bound overrun, unstable reads, or any write attempt.
No live collector exists. Phase 2.12 adds an offline collector that only
validates pre-captured fixtures against these IDs
([CAPTURE-GATE.md](CAPTURE-GATE.md)); the preflight contract does not know it.

R7 rejects every unlisted command-line or bootconfig key. Its command-line
allowlist is limited to `androidboot.slot_suffix` (`_a` or `_b`),
`androidboot.slot` (`a` or `b`), and the valueless `bootconfig` flag. Its
bootconfig allowlist adds only `androidboot.verifiedbootstate` (`green`,
`yellow`, `orange`, or `red`), `androidboot.hardware` (`myron`), and
`androidboot.product.vendor.device` (`myron`). The request records these exact
key/value sets; a future collector cannot widen them under the same request
hash.

The field policy excludes serial, IMEI, MEID, MAC, SSID, Android ID,
partition UUID, disk GUID, raw payload, and kernel, ramdisk, firmware, or module
bytes. The generic `bin/omamobile capture` is not suitable: it records broad
fastboot/Android state and is not used by this gate.

## Evidence map

The request maps every blocker to its real future producer:

1. clean source-lock rebuild and output reproduction, offline;
2. real-parser/full-vendor ABI proof offline plus approved live load-order read;
3. owner-supplied private runtime tree bound offline;
4. attended quiescent capture, restore, and restored metadata/tree proof;
5. approved read-only boot-chain capture;
6. attended boot and hardware qualification with independent rescue;
7. independent review and explicit human authorization tied to request hash.

Items 1 and 3 need no phone read. Items 2 and 5 need a future read-only
session. Items 4 and 6 are deployment gates and are not implied by permission
to read. Item 7 cannot be produced by this tool.

## Safety and publication

The tool imports exact `myron-deployment` 0.4.0 and `myron-snapshot` 0.2.0
implementations in-process. It reuses strict canonical JSON, stable bounded
descriptor reads, no-follow tree walking, input collision/alias checks, and
same-parent `renameat2(RENAME_NOREPLACE)` publication. It starts no process and
has no network or broad-copy facility.

Any changed byte, unknown or duplicate key, non-canonical JSON, extra/missing
file, symlink, hardlink, special file, changed blocker/order, collected
evidence, execution entry, authorization claim, unbounded read, identifier
emission, or changed component binding fails closed.

## Boundary after Phase 2.10

Offline mechanism is ready to describe the next step, but evidence is not.
Before requesting a hardware read, build a real kit and snapshot candidate from
the exact qualified archive, runtime tree, and symvers pair and generate this
request. Review its SHA-256 and requested reads independently. Then request
human approval for that one bounded read-only session.

No deployment approval should be requested until the resulting boot-chain
evidence, source reproduction, full module/runtime closure, real rollback
mechanism, and independent qualification are complete.
