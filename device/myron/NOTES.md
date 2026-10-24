<!-- SPDX-License-Identifier: MIT -->
# Xiaomi myron notes

Status (2026-10-24): reference userspace audited; native Hyprland passed on
the downstream kernel; Arch rootfs integration is build-only. No Omarchy
Mobile image has been built, booted, installed, or flashed.

Phase 2 now provides an activation-disabled, metadata-only kernel contract.
It verifies externally supplied qualified VT artifacts and the private runtime
asset manifest; it does not install or load any hardware payload.

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
