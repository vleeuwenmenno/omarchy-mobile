<!-- SPDX-License-Identifier: MIT -->
# Myron temporary Omarchy hardware-test overlay

This overlay is only for the reversible development payload described in
`docs/myron/HARDWARE-TEST.md`. It is not installed by the Myron device package
and is not a release configuration.

The overlay activates the isolated Myron Mesa profile for SDDM and the UWSM
session, prepares the already qualified KGSL and touch modules, preserves a
static USB rescue address, and qualifies a native Hyprland session before it
disarms the initramfs rollback watchdog. It never writes a partition.

First graphical login also runs the idempotent mobile user setup. A
PATH-scoped `quickshell` wrapper selects Qt Quick's software renderer because
experiment 105 currently produces transparent Qt Quick Wayland surfaces. This
does not change Hyprland or application rendering: they remain on isolated
Zink/Turnip.

That setup disables the downstream driver's zero-size `Virtual-1` and
`Virtual-2` outputs. Without this Myron-only rule, squeekboard binds to a 0x0
output and Hyprland rejects its layer surface before it can reach DSI-1.

The native session deliberately does not set `WAYLAND_DISPLAY`, `AQ_BACKEND`,
or `EGL_PLATFORM`. Hyprland must select DRM/KMS itself.

The attended profile uses scale `2.0` on `DSI-1`. Squeekboard keeps a separate
portrait-height multiplier of `1.8`, so the keyboard remains usable while the
rest of the shell gains room.

The composed private image includes the verified radio-base and AudioReach
runtime asset closure plus their userspace packages. Modem, remoteproc and
audio activation remain disabled; installing the files alone must not start
hardware or ModemManager.

Two disabled, marker-gated units bridge to exact checksum-pinned copies of the
known-good postmarketOS scripts while that root remains mounted:
`myron-reference-radio.service` and
`myron-reference-audio-foundation.service`. Neither unit has an `[Install]`
section. The audio unit stops at ALSA-card/raw-microphone readiness; speaker
routing remains a separate safety gate. These bridges are temporary hardware
qualification tools, not the final standalone Arch implementation.
