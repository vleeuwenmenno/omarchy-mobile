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
   `/opt/omamobile/myron-gpu`, ICD and DRI paths included, no global loader
   configuration;
2. `omamobile-myron-gpu-profile`: systemd environment/drop-ins and a probe
   wrapper that opt the compositor/session into that exact prefix.

The device package must not carry firmware or modules. A private provisioner
places verified vendor assets under a separate versioned path and writes a
manifest. The GPU service fails closed when kernel notes, module, firmware, or
Mesa hashes differ.

Only after equivalence tests pass should the project consider replacing the
repository's generic Mesa package or loader configuration.

## Reproducibility gates

Before creating the Arch Mesa package, resolve these reference inconsistencies:

- Attempt104 documentation records an older combined APK hash;
- the promoted installer expects the r1 APK with a different hash;
- the r1 APK and calibrated-timestamp patch are untracked in the reference
  checkout;
- accepted compiler and dependency versions are not recorded as a complete
  build manifest.

The Arch PKGBUILD must pin Mesa source, both patches, toolchain inputs, Meson
options, and source hashes. It must build aarch64 output from source; importing
the APK is forbidden.

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
