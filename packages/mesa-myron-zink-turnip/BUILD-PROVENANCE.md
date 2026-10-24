<!-- SPDX-License-Identifier: MIT -->
# Offline build provenance

Validation date: 2026-10-24. This records one successful unsigned development
build; the package's embedded `.BUILDINFO` remains the complete dependency
inventory for each produced artifact.

- Arch Linux ARM root tarball SHA-256:
  `42a4eeaa038994ffd31fa173256ef2f0ef511358eeb41b9ea1f8626391b9b319`
- Mesa source signer:
  `57551DE15B968F6341C248F68D8E31AFC32428A6` (Eric Engestrom)
- makepkg: `7.1.0`
- GCC: `16.1.1+r12+g301eb08fa2c5-1`
- binutils: `2.46+r70+g155188ea10a7-1`
- glibc: `2.43+r22+g8362e8ce10b2-2`
- Meson: `1.12.1-2`
- Ninja: `1.13.2-3`
- libdrm: `2.4.134-1`
- Vulkan headers/loader and SPIR-V Tools: `1.4.363.0-1`

The upstream signature and every source checksum passed. Both patches applied
with zero fuzz. Meson configured Zink only, Freedreno Vulkan with `msm,kgsl`,
and no LLVM, GLVND, VA frontend, or video codec. All 1421 AArch64 targets
compiled, including `tu_knl_kgsl.cc`; package checks and assembly passed.

The host's `qemu-aarch64` binfmt entry lacked the `F` flag required by the
repository helper. Validation used the same verified Arch Linux ARM build image
with `/usr/bin/qemu-aarch64-static` mounted read-only inside the disposable
container. This changed no source or target package input.

No repository signing key was present, so the artifact was not imported into
`out/repo`, signed, deployed, or installed. No phone was contacted. Hardware
qualification remains pending.
