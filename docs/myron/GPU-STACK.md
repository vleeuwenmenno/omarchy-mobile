<!-- SPDX-License-Identifier: MIT -->
# Myron graphics stack and Arch packaging design

## Proven reference path

```text
Hyprland / KWin / Wayland clients
              |
          EGL / GBM
              |
             Zink
              |
     Turnip / Freedreno Vulkan
              |
            KGSL
              |
          Adreno 840
```

The working live stage is
`/var/lib/myron-experiments/attempt105-gpu-wayland`. It combines Mesa 26.2.2
Zink and Turnip with both `msm` and `kgsl` KMD support. The system Mesa package
is not an equivalent fallback.

Required runtime variables are:

```text
LD_LIBRARY_PATH=<stage>/mesa
LIBGL_DRIVERS_PATH=<stage>/mesa/dri
MESA_LOADER_DRIVER_OVERRIDE=zink
VK_DRIVER_FILES=<stage>/freedreno-kgsl.json
```

Native Hyprland must not inherit `WAYLAND_DISPLAY` or force
`AQ_BACKEND=wayland`; Aquamarine selected its native DRM backend during the
successful bounded test.

## Source provenance

Reference implementation:

- `../myron-postmarketos/experiments/attempt104-combined-mesa/`
- `../myron-postmarketos/experiments/attempt105-gpu-global/`
- `../myron-postmarketos/experiments/attempt106-flatpak-turnip-kgsl/`
- `../myron-postmarketos/scripts/install-myron-gpu-rootfs.sh`

Attempt104 builds checksum-pinned Mesa 26.2.2 with:

```text
-Dfreedreno-kmds=msm,kgsl
-Dgallium-drivers=zink
-Dvulkan-drivers=freedreno
-Dplatforms=x11,wayland
-Degl=enabled
-Dgbm=enabled
-Dgles1=enabled
-Dgles2=enabled
-Dllvm=disabled
```

It also applies the sole-physical-device Zink patch and a KGSL patch disabling
unsupported calibrated timestamp exposure.

## Live contents and dependencies

Attempt105 contains isolated EGL, GL/GLES, GBM, Gallium, Zink DRI, GBM DRI,
and Turnip libraries, an ICD manifest, four KGSL-related modules, and four GPU
firmware files. Its SHA256SUMS was present and KWin mapped only the expected
custom graphics libraries during audit.

The live ELF dependencies include musl's
`libc.musl-aarch64.so.1`. Arch Linux ARM uses glibc. Therefore:

> Attempt105 cannot be copied into an Arch rootfs.

The Arch package must rebuild from source against Arch libraries. A successful
copy or `LD_LIBRARY_PATH` experiment under Alpine is only the behavioral
reference.

## Packaging shape

Early Arch builds should use two isolated source packages rather than replace
system Mesa:

1. `mesa-myron-zink-turnip`: Mesa libraries under
   `/usr/lib/omamobile/myron-gpu`, ICD and DRI paths included, no global loader
   configuration;
2. `omamobile-myron-gpu-profile`: an activation-disabled environment contract,
   inert session drop-in template, and static probe around that exact prefix.

The profile package stores its environment and drop-in under its private
`/usr/share/omamobile/myron-gpu-profile` directory, outside systemd,
environment-generator, shell-profile, and Vulkan loader search paths. Its
static probe verifies both packages and rejects literal private-stack markers
in enumerated standard system activation locations. It does not claim coverage
of arbitrary custom paths. The live probe remains absent and always refuses.

The device package must not carry firmware or modules. A private provisioner
places verified vendor assets under a separate versioned path and writes a
manifest. The GPU service fails closed when kernel notes, module, firmware, or
Mesa hashes differ.

Only after equivalence tests pass should the project consider replacing the
repository's generic Mesa package or loader configuration.

## Reproducibility result

The source-level r0/r1 inconsistency is resolved:

- r0 is SHA-256 `0cd3b2fb24af4b07f2863561e39c78afb41a487c5ae80d97deb0ab6aa56fc9a7`;
- r1 is SHA-256 `f03111c858112c3b3d71717fd5482eb7982e23d018defda8c3335c9ecdfad538`;
- the reference checkout diff shows r1 adds only the KGSL calibrated-timestamp
  patch to the same source and Meson options;
- Gallium, EGL, GLES2, and GBM payload hashes are unchanged; Turnip differs.

The r1 APK and patch remain untracked in the read-only reference checkout.
Its Alpine image digest is pinned, but rolling `apk add` inputs mean the full
compiler/dependency versions cannot be reconstructed from repository evidence.
The Arch package is therefore source-equivalent rather than byte-equivalent.

`packages/mesa-myron-zink-turnip` pins Mesa, its release signature, both patch
semantics, Meson options, reference hashes, and its isolated path. Arch package
versions are captured by the built package metadata and build log. Importing
the musl APK remains forbidden.

### Offline package result (2026-10-24)

The unsigned AArch64 development build completed all 1421 Mesa targets in the
verified Arch Linux ARM container. Source signature/checksums, zero-fuzz patch
application, package tests, assembly, AArch64 ELF checks, runtime dependency
audit, final-byte manifest, and isolated path audit passed. Exact artifact:

```text
mesa-myron-zink-turnip-26.2.2-1-aarch64.pkg.tar.zst
SHA-256 2d384eb7032d21aa0de347023c5407b8a056f8354fe82d84380e2c16fb45fbb7
```

The artifact remains outside the signed repository under a disposable `/tmp`
build directory. It has not been installed or run on the phone. This proves
the glibc package builds; it does not qualify GPU hardware behavior.

### Activation-disabled profile result (2026-10-24)

`packages/omamobile-myron-gpu-profile` records the four proven environment
variables without applying them. It explicitly forbids inherited
`WAYLAND_DISPLAY`, `AQ_BACKEND`, and `EGL_PLATFORM` for a future native
session. `verify-static` opens no device nodes: it verifies the isolated Mesa
payload and searches enumerated standard activation paths for the private
prefix and inert profile. Installing either package remains insufficient to
select the stack; the scan does not claim coverage of arbitrary custom paths.

The standalone package check and an extracted-root test with the Mesa artifact
passed. Exact unsigned development artifact:

```text
omamobile-myron-gpu-profile-0.1.1-1-any.pkg.tar.zst
SHA-256 6f02c0ac292888d6be619c228afdca04d04db64e5ddf644533846d0a00641784
```

## Equivalence test ladder

Each gate rejects llvmpipe and records the selected device:

1. `vulkaninfo` enumerates one Adreno 840 Turnip device through KGSL;
2. EGL initializes GBM and surfaceless with Zink/Turnip;
3. an EGL Wayland client renders under the reference compositor;
4. nested Hyprland starts and maps only the isolated Arch package;
5. a native Wayland client maps and renders;
6. after approval, bounded native Hyprland acquires DSI-1, touch, card0,
   renderD128, and KGSL, then recovers the reference session;
7. browser playback and WebGL/WebGPU soak without KGSL faults;
8. suspend/resume, DP, DMA-BUF, and synchronization receive separate tests.

Success strings include `Adreno (TM) 840 (MESA_TURNIP)`. Any llvmpipe result,
system Gallium mapping, unexpected Vulkan device, GPU fault increment, or
failed recovery is a stop condition.
