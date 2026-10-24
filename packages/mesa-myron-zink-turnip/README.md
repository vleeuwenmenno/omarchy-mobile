<!-- SPDX-License-Identifier: MIT -->
# mesa-myron-zink-turnip

Activation-disabled Arch Linux ARM source package for Xiaomi `myron`. It
rebuilds the proven Mesa 26.2.2 Zink + Turnip path against glibc and installs
only into `/usr/lib/omamobile/myron-gpu`.

It does not provide, conflict with, replace, or modify Arch's `mesa` package.
It installs no Vulkan loader registration, environment file, systemd unit,
udev rule, firmware, kernel module, hook, or compositor configuration. Merely
installing it cannot select this driver.

## Reference reconciliation

Attempt105 r0 used APK SHA-256
`0cd3b2fb24af4b07f2863561e39c78afb41a487c5ae80d97deb0ab6aa56fc9a7`.
The promoted r1 APK SHA-256 is
`f03111c858112c3b3d71717fd5482eb7982e23d018defda8c3335c9ecdfad538`.
The tracked-to-working-tree diff proves r1 adds only the KGSL calibrated
timestamp patch to the same checksum-pinned Mesa source and build options.
Its Gallium, EGL, GLES2, and GBM payload hashes match r0; Turnip changes.

The reference Alpine base image was digest-pinned, but `apk add` resolved
rolling package versions. Therefore r1's complete compiler/dependency set is
not recoverable from repository evidence. This Arch build is source-equivalent,
not expected to be byte-identical. It must pass the hardware equivalence ladder
before any session profile may use it.

The two package patches express the same changes as the reference patches but
refresh context so both apply to Mesa 26.2.2 with zero fuzz. `reference.json`
records original reference-patch hashes separately.

## Build and inspect

Use repository tooling:

```sh
tools/build-packages packages/mesa-myron-zink-turnip
tests/packages mesa-myron-zink-turnip
```

The build is intentionally classified as slow. No phone deployment or live
graphics change is part of this package.

After package installation in an offline root, validate bytes without loading
them:

```sh
omamobile-myron-gpu-verify verify-layout
```

Hardware activation belongs in the future `omamobile-myron-gpu-profile`
package and remains blocked pending staged equivalence tests.
