<!-- SPDX-License-Identifier: MIT -->
# omamobile-device-myron

Build-only device metadata for Xiaomi codename `myron` (POCO F8 Ultra,
Qualcomm SM8850). This package can be built and inspected while the correct
Arch kernel/module and rootfs integration is developed. The current rootfs,
module-push, kexec, fastboot, image, flash, push, and installer paths all refuse
Myron before starting work.

It installs only the device descriptor, this notice, its version, and the MIT
license. It contains no firmware, kernel, modules, systemd units, udev rules,
session configuration, boot images, partition names, writer, or pacman hook.
Installing it cannot activate hardware support.

The descriptor uses `BOOT_METHOD=external-android`. Generic rootfs and
device-transition commands must reject that method before contacting a phone
or starting a build container. Hardware integration will be added subsystem by
subsystem only after the downstream postmarketOS implementation is translated
and tested.
