<!-- SPDX-License-Identifier: MIT -->
# Myron temporary Omarchy hardware test

Status: live hardware qualified on 2026-10-25; clean rebuilt artifacts are
offline-only and have not yet been reboot-tested.

This is a reversible development test around the existing downstream Myron
kernel and extracted runtime assets. It is not the production installer, does
not authorize deployment, and does not change the device descriptor's
`external-android` boot method.

## Live evidence

The temporary Arch root booted the existing
`6.12.23-android16-5-g5a0e85dd9db0-dirty-4k` kernel and passed these attended
checks:

- Hyprland 0.56.2 acquired native DRM/KMS on `DSI-1`, exposing
  1200x2608 at 60, 90 and 120 Hz.
- Hyprland mapped the isolated Myron `libEGL`, `libgbm`, Gallium and Freedreno
  Vulkan libraries, opened card0, renderD128 and KGSL, and reported Zink on
  `Adreno (TM) 840 (MESA_TURNIP)`. No llvmpipe mapping was present.
- Touch events reached Hyprland after Xiaomi THP raw mode was disabled.
- Omarchy's mobile status bar, launcher and app grid rendered on DSI-1.
  Touch input entered text into the launcher's search field.
- Squeekboard mapped on DSI-1 after the downstream driver's zero-size
  `Virtual-1` and `Virtual-2` outputs were disabled.
- The attended display scale is now `2.0` (600x1304 logical pixels). The
  portrait Squeekboard height uses an independent `1.8` multiplier.
- `pmic_pwrkey` and `pmic_resin` are explicitly classified as input keyboards,
  so Hyprland now registers the power and Volume Down devices alongside the
  already visible gpio-keys device.
- USB NCM SSH remained available throughout qualification.
- The independent 15-minute rollback watchdog found its disarm marker and
  exited successfully without rebooting.

The qualifier recorded:

```text
result=qualified dsi=DSI-1 renderer=isolated-zink-turnip stable_seconds=90 rollback=disarmed
```

## Findings incorporated into the overlay

The full first-run provisioner can block on network-dependent Mise work after
it has created the user. The hardware-test image bounds that unit, and the
user-level `omamobile-setup-user` service is allowed to seed the idempotent
phone profile on the first graphical login.

Qt Quick cannot create usable Wayland EGL surfaces with the isolated
experiment-105 stack in this image: Quickshell's layers are present but
transparent and its log reports `Failed to create the decorations EGLContext`.
The hardware-test session therefore shadows only the `quickshell` executable
with a wrapper that sets `QT_QUICK_BACKEND=software`. Hyprland and ordinary
applications retain the isolated accelerated stack.

Squeekboard initially selected the first advertised output, `Virtual-1`, whose
mode is 0x0. Hyprland rejected its layer surface with
`y == 0 but anchor doesn't have top and bottom`. The Myron user-setup wrapper
adds explicit disabled monitor rules for both zero-size virtual outputs.

The Arch stage now packages QRTR, RMTFS, TQFTP, TinyALSA, AudioReach graph
services/configuration/manager and FastRPC. The private composer requires the
verified `radio-base` and `audio-microphone` runtime closures. Package install
does not start a remote processor or service.

For this temporary test only, two disabled units bridge to exact
checksum-pinned copies of the known-good scripts in the mounted postmarketOS
root. The radio bridge consumes a per-boot marker asserting that a fresh
read-only calibration backup was verified. The audio bridge has a separate
one-shot marker and stops at ALSA-card/raw-microphone readiness. It never
opens speaker playback. Neither unit has an install target, and ModemManager
stays masked in the composed image.

## Rebuilt offline artifacts

Private, untracked artifacts produced after those fixes:

```text
8d9c8f5c583204ba0e8ea68cc1a3f7817e79e7b48e8e12cecc95a485cdfe73a1  myron-omarchy-hardware-test-20261025.img
7a107847f72f08dc8e2825260fb2b258228679fc795b33fde93694a064e862c5  init_boot_a-myron-omarchy-hardware-test-20261025.img
6f0d8512147096294688ddecd56a928fdc3ebf887355f795f43aee749fc0044c  myron-omarchy-hardware-test-20261025-r3.img
```

The `r3` image was composed from the real unsigned Arch stage after all new
Qualcomm userspace packages resolved. `e2fsck`, image-content checks,
`tests/all`, and every package suite passed; the one package suite requiring
ShellCheck was rerun with a temporary pinned `shellcheck@0.11.0`. The current
init_boot candidate is hash-bound to the earlier payload, so `r3` cannot be
substituted without rebuilding init_boot through the existing guarded tool.

The init_boot candidate embeds a 900-second watchdog and the exact known-good
postmarketOS rollback image hash
`535d8e2fe0db2b35dc003e329fafc2b76dd82705df70cef63dc74accf653ec24`.
Slot B is the owner's Android/recovery installation and is outside this test.

`tests/myron-hardware-test` and the complete `tests/all` suite passed after the
fixes. The rebuilt pair still needs one clean attended boot before the live
hotfixes can be called reproducible.

## Current hardware-test boundary

The live temporary Arch root has the userspace foundations and private audio
closure staged, but ADSP and modem MSS remain offline. ModemManager is
inactive. Therefore audio, modem and GNSS are still unverified in Omarchy.

Before the first radio start, stream the kernel log to the laptop and arm an
independent recovery timer. Start only `myron-reference-radio.service`, then
verify `wlan0`, MSS, QRTR and USB SSH before touching ModemManager. The audio
foundation is a later, separate boot change. Speaker routing, carrier data,
SMS, calls and GNSS fixes remain separate approval gates.
