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
