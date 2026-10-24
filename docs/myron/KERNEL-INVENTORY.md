<!-- SPDX-License-Identifier: MIT -->
# Myron kernel and boot inventory

Status: audited from the postmarketOS reference and live kernel on 2026-10-24.
No boot image or partition was read or written for this audit.

## Kernel contract

| Item | Value |
| --- | --- |
| Family | Android 16 GKI, Qualcomm/Xiaomi downstream integration |
| Branch | `common-android16-6.12-2025-06` |
| GKI source revision | `5a0e85dd9db068df8f0cdff9be76fe4211bd8af9` |
| `build/kernel` revision | `63effe2e370fdae20270d1f2040a4834a1740a89` |
| Running release | `6.12.23-android16-5-g5a0e85dd9db0-dirty-4k` |
| Live DT compatible | `qcom,canoe-mtp` first |
| Live DT model | Myron based on SM8850 |

The reference source lock is
`../myron-postmarketos/config/myron-gki-sources.lock.json`. It pins GKI,
Kleaf, toolchain, mkbootimg, and build dependencies, but explicitly says the
original toolchain identity and accepted output reproduction are not yet
verified. It is a bootstrap seed, not a release-qualified kernel recipe.

## Qualified VT contract

Phase 2 records the latest systemd/VT-qualified downstream pair as metadata in
`device/myron/kernel-contract.json`. The package
`omamobile-myron-kernel-contract` verifies external inputs but distributes none
of their bytes.

Version 0.2.0 adds `device/myron/stage-contract.json`, bound to the SHA-256 of
the reference above. It fixes the exact destination, mode and SHA-256 of the eight
target files, derived from the reference: the candidate selector at
`/usr/local/sbin/myron-attempt79-module-dir` (0755) and the seven modules
directly under `/usr/local/lib/myron-gki-module-sets/<notes sha256>/` (0644).
Archive checksums, manifest, notes and the previous selector are validated but
not staged, and the manifest's `selector_destination` must match. It also lists
the paths that must stay absent. `plan-stage` prints that plan and `verify-stage` compares a tree with it
using descriptor-confined, `O_NOFOLLOW`, bounded, read-only traversal. The
verifier writes nothing and executes nothing. It stays limited to byte identity
and the exact release marker: that is not full ABI, import, provider or
load-order proof, and it does not authorize hardware access or deployment.

| Input | Qualified SHA-256 |
| --- | --- |
| Raw `Image` | `9dc9d4a00544af130e04b534cb566e26329dbaa9b2f0e6596ad52c1e657d9e09` |
| ELF `.notes` payload | `8ba2b05e346c638d699e16d4b782378e394bba374a12b16abacc1b905cb8d608` |
| Full kernel configuration | `33b6eaf87b7ca2d0d06dd10dbe2a4ce3d58e50ad804d6b385cd5f953e2fe3b95` |
| `vmlinux.symvers` | `aaf3fa84f4ccbab54327eee5a7fed7903e3f79af9ab53fdffe5165b27f2fa9f1` |
| `kernel_aarch64_Module.symvers` | `d5507f9cfb0ba26541dd7c76e077601da89e0ab650ec69acaf854b62ee247f37` |
| VT module asset archive | `342139d347edcb1a0bcb37498eead80657b307709920666fc7fae40e0dcd3496` |
| Runtime asset manifest | `6e4cd92a61b246c52255ccdbea8cc6280d6ceecdae12d083417f220fe6b90fbc` |

The verifier requires all five kernel/ABI files and the exact asset archive.
It validates the archive allowlist, internal checksums and manifest, exact
release marker in all seven GKI modules, notes-keyed selector, and the explicit
`rmnet_core` conflict. Runtime firmware and vendor assets remain private and
are accepted only through the exact 105-row manifest.

Source provenance records the exact source-lock and stamped-manifest hashes
plus the four patches used by the qualified build path (Bluetooth
preinitialization, GENI clock voting, in-tree RMNET export, and IPC namespace
exports). Those hashes describe the accepted dirty reference checkout; they do
not claim a clean independent rebuild.

This does not make the source lock reproducible: the reference checkout is
dirty, and its lock still labels original toolchain identity and accepted
output reproduction unverified. The contract therefore fixes activation to
`disabled`. A live re-read was also withheld because SSH presented a changed
host key; the local trust record was not modified or bypassed.

`linux-xiaomi-myron-android` is only a postmarketOS rootfs compatibility
marker. Its `/boot/vmlinuz-*` is text saying not to flash it. The real Image,
DTB/DTBO, vendor modules, and Android boot images remain externally managed.

## Required patch series

The reference repository currently carries:

1. QCA Bluetooth attachment for a userspace-preinitialized controller;
2. MSM GENI UART clock voting from Qualcomm IBS;
3. Kleaf export of in-tree RMNET;
4. Qualcomm PD mapper canoe-domain support;
5. GKI export of FastRPC, SCM, and TZMEM modules;
6. FastRPC acceptance of the downstream transport-domain labels;
7. IPC namespace symbol exports.

Patches 1-3 are part of the proven Bluetooth/RMNET baseline. Later patches
belong to container and audio candidates and require their own KMI gates. Do
not assume every file in `kernel-patches/` belongs in one accepted kernel.

## Configuration progression

- Attempt79: boot-proven PID/IPC namespace baseline, POSIX mqueue, RMNET.
- Attempt80: adds `CONFIG_USER_NS=y`; attended display, touch, Wi-Fi, mobile
  data, and Flatpak Telegram gates passed.
- Attempt83: adds networking address-type support for container work.

The exact build is identified by the SHA-256 of `/sys/kernel/notes`, not only
`uname -r`. Several builds intentionally share the same release string.
Matching modules by release alone is unsafe.

## Module model

The running kernel reported 451 loaded modules during audit. Important loaded
components included msm_drm, msm_kgsl, in-tree RMNET, stock IPA/IPANETM and
RMNET control, Qualcomm remoteproc, and the touch stack. The rootfs did not
expose a conventional `/lib/modules/<release>` tree during the read-only
capture; modules are selected and staged through the reference boot/runtime
tooling.

The working replacement relationship is strict:

- in-tree `rmnet.ko` replaces proprietary `rmnet_core.ko`;
- stock `ipam.ko`, `ipanetm.ko`, and `rmnet_ctl.ko` remain required;
- `rmnet.ko` and `rmnet_core.ko` must never load together;
- vendor QMI, QRTR, IPA, remoteproc, WLAN, AudioReach, and camera modules
  cannot be replaced merely because their vermagic matches.

Every Arch kernel/module package must verify:

1. exact kernel notes hash and release;
2. protected GKI ABI;
3. shared symbol CRCs and full exported symbol set;
4. all saved Xiaomi vendor-module imports and provider conflicts;
5. module load order and rollback pairing with the exact Image.

## Device tree and boot-image unknowns

The live downstream DT is useful evidence but is not an Omarchy Mobile board
DTB. No `qcom/sm8850-myron.dtb` is claimed in the target. These items remain
unknown or unverified for an Arch install path:

- boot, init_boot, vendor_boot, vendor_kernel_boot, recovery, and DTBO headers;
- bootloader DTB selection rules and overlay identifiers;
- boot arguments and console path;
- active-slot source of truth;
- exact partition write allowlist;
- initramfs handoff, module staging, firmware timing, and recovery counter;
- whether the current postmarketOS root partition should be reused or an
  offline image should target another location.

Repository history says Linux is on slot A and Android/recovery on slot B.
Omarchy Mobile's generic tools assume Linux images on slot B and root on
`userdata`. They must remain disabled for Myron.

## Arch packaging strategy

Initial Arch work reuses the exact boot-proven Image and matched module sets;
it does not install `linux-omamobile`, replace DTBs, or generate boot images.
The staged approach is:

1. define an external-kernel manifest package containing only hashes,
   provenance, and compatibility checks;
2. build an Arch rootfs offline with no kernel post-install hook;
3. translate module selectors and service order from the reference modules;
4. prove a read-only rootfs inspection and a temporary boot mechanism with a
   separate recovery design;
5. only then implement a Myron-specific kernel/image package.

No Arch package may own or overwrite the proven boot images during phases 0-3.

The Phase 2 package follows that rule: it installs only a Python verifier,
contract JSON, documentation, license, and version. It has no systemd unit,
pacman hook, module payload, firmware, Image, DTB/DTBO, or partition writer.
