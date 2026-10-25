<!-- SPDX-License-Identifier: MIT -->
# omamobile-device-myron

Build-only device metadata for Xiaomi codename `myron` (POCO F8 Ultra,
Qualcomm SM8850). This package can be built and inspected while the correct
Arch kernel/module and rootfs integration is developed. Module-push, kexec,
fastboot, image, flash, push, installer, and bootable-rootfs paths all refuse
Myron before starting work. The sole exception is the explicit
`tools/build-rootfs --stage-only` package-resolution tree; it carries no
kernel, modules, boot payload, private firmware, or install path. It also
ships the local `[omamobile]` mirrorlist (`file:///var/lib/omamobile/repo/$arch`).

It installs only the device descriptor, local package mirrorlist, this notice,
its version, and the MIT license. It contains no firmware, kernel, modules, systemd units, udev rules,
session configuration, boot images, partition names, writer, or pacman hook.
Installing it cannot activate hardware support.

The descriptor uses `BOOT_METHOD=external-android`. Generic rootfs and
device-transition commands must reject that method before contacting a phone
or starting a build container, except for the non-bootable stage paired with
`ROOTFS_INTEGRATION=external-contract`. `ROOTFS_PACKAGE_PROFILE=myron` excludes
Panfrost and unqualified camera, fingerprint, and NFC packages while selecting
the isolated Myron Mesa/profile pair. The resolved stage must use
`omamobile-apps-myron` and is rejected if generic camera, NFC, fingerprint, or
Panfrost packages re-enter through dependencies. Hardware integration will be
added subsystem by subsystem only after the downstream postmarketOS
implementation is translated and tested.
