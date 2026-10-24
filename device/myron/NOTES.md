<!-- SPDX-License-Identifier: MIT -->
# Xiaomi myron notes

Status (2026-10-24): reference userspace audited; native Hyprland passed on
the downstream kernel; Arch rootfs integration is build-only. No Omarchy
Mobile image has been built, booted, installed, or flashed.

Phase 2 now provides an activation-disabled, metadata-only kernel contract.
It verifies externally supplied qualified VT artifacts and the private runtime
asset manifest; it does not install or load any hardware payload.

Kernel contract 0.2.0 adds `device/myron/stage-contract.json` (a byte-identical
copy ships in the package) and `omamobile-myron-kernel-verify show-stage`,
`plan-stage --assets ARCHIVE` and `verify-stage --assets ARCHIVE --root ROOT`.
They describe and check an external, immutable module stage tree read-only
(the candidate selector at `/usr/local/sbin/myron-attempt79-module-dir`, mode
0755, plus seven modules directly under the notes-keyed module directory, mode
0644; archive metadata is validated but not staged): the
verifier writes nothing, runs no external command, and never executes staged
bytes. The release-marker and hash proof is not full ABI, import, provider or
load-order proof. There is still no stage writer, extraction, `depmod`, module
install, boot work, or hardware/deployment authorization.

Kernel contract 0.3.0 (Phase 2.6) adds `omamobile-myron-kernel-verify
verify-abi --assets ARCHIVE --vmlinux-symvers FILE --module-symvers FILE`: a
read-only, pure-Python, staged-set-only check of module imports, exports, CRCs,
providers and declared load order against the two exact symvers files. The
parser handles a synthetic ELF layout only and is unqualified on real modules;
vendor modules are `not-verified`, activation stays disabled and nothing is
authorized.

Phase 2.5 adds `device/myron/deployment-contract.json` and the laptop-only
`tools/myron-deployment` (`show`, `stage-modules`, `assemble`, `verify`,
`gate`). It stages the exact qualified module overlay (selector plus seven
modules) and binds the rootfs stage (by digest and manifest hash, not copied),
kernel contract, GPU profile and private runtime-manifest identity into a
deterministic kit, and its gate always refuses deployment. The kit is not
bootable, flashable or image-ready, is no atomic-snapshot proof, is not
hardware-qualified, and is no authorization; no kit has been built from the real
archive. See [DEPLOYMENT-GATE.md](../../docs/myron/DEPLOYMENT-GATE.md).

Phase 2.7 (`tools/myron-deployment` 0.2.0) adds `--runtime-assets none|DIR`: the
kit records `runtime_assets` evidence, either `not-bound` or a hash-only
`verified` closure of the required stock-extracted `gpu`/`wifi`/`touch` files
(contract and blockers unchanged). Binding is not provisioning, extraction,
redistribution, ABI or hardware qualification; no private bytes or manifest are
copied, no real runtime tree has been bound, and
`private-runtime-asset-bytes-not-bound-to-kit` stays until a real, separately
reviewed bound kit and contract revision.

Phase 2.8 (`tools/myron-deployment` 0.3.0) integrates that verifier as optional
hash-only kit evidence. `assemble`, `verify` and `gate` require both
`--vmlinux-symvers` and `--module-symvers`, each either `none` or an exact file.
A bound kit records only a fixed staged-set summary plus report/evidence hashes;
symvers bytes and symbol tables stay external. The parser and vendor inventory
remain unverified, module order remains `unverified`, activation remains
disabled, all seven blockers stay unchanged, and the gate still refuses. No
real archive or symvers pair has been bound.

Phase 2.9 adds `device/myron/snapshot-contract.json` and the laptop-only
`tools/myron-snapshot` 0.1.0. It re-verifies every deployment-kit input, then
binds only the kit identity, rootfs digest/manifest, archive hash, runtime
summary and ABI summary into a deterministic five-file metadata artifact. Its
read-only rollback rehearsal compares a candidate tree with the bound rootfs
digest but always reports atomicity and rollback as unproven. Version 0.1.0
accepts only `not-captured` and `not-proven` evidence, preserves all seven
blockers, copies no payload bytes and performs no capture, restore or deploy.
See [SNAPSHOT-GATE.md](../../docs/myron/SNAPSHOT-GATE.md).

Stage-only rootfs (`ROOTFS_INTEGRATION=external-contract`): `tools/build-rootfs
--stage-only` writes a package tree and MANIFEST under `out/`. It is not
bootable, not image-ready, and not hardware-qualified; it carries no kernel,
modules, boot payload, or proprietary/vendor payload and activates no GPU or
session service. No image is produced, and a rootfs build without
`--stage-only` is still refused.

The stage uses `ROOTFS_PACKAGE_PROFILE=myron`: Qualcomm/mobile userspace and
the isolated Zink/Turnip packages are selected, while Panfrost and unqualified
camera, fingerprint, and NFC packages are excluded. A Myron-only app provider
keeps Maps/GeoClue without pulling camera or NFC dependencies; the resolved
package closure is checked before a stage is emitted. Selection does not claim
hardware qualification.

## Verified reference facts

- [V] The live device tree identifies the board as a Myron design based on
  SM8850 and begins with `qcom,canoe-mtp`.
- [V] The running kernel is
  `6.12.23-android16-5-g5a0e85dd9db0-dirty-4k`.
- [V] `msm_drm` exposes DSI-1 at 1200x2608 with 60, 90, and 120 Hz modes;
  `focaltech_ts` supplies touch input.
- [V] Native Hyprland 0.54.3 with Aquamarine 0.12.0 obtained DRM/KMS control,
  rendered through Zink/Turnip on Adreno 840, saw touch, and returned to
  Plasma automatically after a bounded test.
- [V] The reference root is ext4 on `pmos_root`. Repository documentation says
  postmarketOS occupies slot A while Android/recovery remain on slot B.
- [V] The live kernel command line and bootconfig do not expose a usable slot
  suffix. The slot claim therefore remains repository evidence, not an
  independently revalidated bootloader fact.

Evidence and subsystem status are recorded in
[`docs/myron/`](../../docs/myron/). The read-only reference repository is
expected beside this checkout as `../myron-postmarketos`.

## Safety state

`BOOT_METHOD=external-android` is a refusal marker. Generic rootfs,
module-push, kexec, fastboot, image, flash, push, and installer paths refuse
it before external access. The supported Pixel-shaped `android-v4` installer
always targets slot B and `userdata`, which is incompatible with the reference
Myron arrangement. Do not change the method until all of these are verified
from non-identifying captures:

1. boot, init_boot, vendor_boot, vendor_kernel_boot, DTBO, and recovery layout;
2. current and rollback slots plus exact recovery images;
3. DTB/DTBO selection and Android boot-image header values;
4. root partition and storage-guard model;
5. a Myron-specific dry run whose write allowlist has independent tests.

No Pixel `SOC_IDS`, Exynos early console, display register, or `_b` write
allowlist belongs in this descriptor.
