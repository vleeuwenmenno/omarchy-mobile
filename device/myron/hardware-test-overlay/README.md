<!-- SPDX-License-Identifier: MIT -->
# Myron temporary Omarchy hardware-test overlay

This overlay is only for the reversible development payload described in
`docs/myron/HARDWARE-TEST.md`. It is not installed by the Myron device package
and is not a release configuration.

The overlay activates the isolated Myron Mesa profile for SDDM and the UWSM
session, prepares the already qualified KGSL and touch modules, preserves a
static USB rescue address, and qualifies a native Hyprland session before it
disarms the initramfs rollback watchdog. It never writes a partition.

The qualifier also creates the canonical system DMA-heap node and its DRI
alias from the kernel's exact sysfs device number. It disarms rollback only
after a separate Wayland EGL client, running as the graphical user, reports
Adreno 840 Turnip without llvmpipe or swrast.

First graphical login also runs the idempotent mobile user setup. A
PATH-scoped `quickshell` wrapper selects Qt Quick's software renderer because
experiment 105 currently produces transparent Qt Quick Wayland surfaces. This
does not change Hyprland or application rendering: they remain on isolated
Zink/Turnip.

For this temporary image, first boot records the downstream nftables firewall
as deferred and skips Omarchy's network-only Mise/developer-tool downloads.
The packaged mobile profile still runs; full Omarchy user provisioning remains
unmarked and can be run once Wi-Fi is available.

That setup disables the downstream driver's zero-size `Virtual-1` and
`Virtual-2` outputs. Without this Myron-only rule, squeekboard binds to a 0x0
output and Hyprland rejects its layer surface before it can reach DSI-1.

The native session deliberately does not set `WAYLAND_DISPLAY`, `AQ_BACKEND`,
or `EGL_PLATFORM`. Hyprland must select DRM/KMS itself.

The attended profile uses scale `2.0` on `DSI-1`. Squeekboard keeps a separate
portrait-height multiplier of `1.8`, so the keyboard remains usable while the
rest of the shell gains room.

The composed private image includes the verified radio-base, AudioReach and
battery-authentication runtime asset closures plus their userspace packages.
Modem, remoteproc and audio activation remain disabled; installing those files
alone must not start hardware or ModemManager. The checksum-pinned battery
daemon is enabled only inside the armed temporary test and is ordered after
hardware preparation and before the display manager. `myron-battery-stage`
performs a separate read-only sysfs and UPower qualification while the
independent rollback watchdog remains active.

`myron-peripheral-audit` is another read-only, watchdog-gated probe. It records
only aggregate presence for motion-sensor IIO attributes, haptic force
feedback, camera/media nodes, fingerprint nodes, and already-running
ModemManager Voice/Messaging interfaces. It neither loads modules nor starts a
modem service, and it never records modem or SIM identifiers.

The overlay provides a Myron-specific `omamobile-gnss` command for the shell's
Location tile. It controls the qualified raw/NMEA/MSA/MSB sources through
ModemManager and does not install the Pixel-specific Broadcom GNSS package.

Two disabled, marker-gated units bridge to exact checksum-pinned copies of the
known-good postmarketOS scripts while that root remains mounted:
`myron-reference-radio.service` and
`myron-reference-audio-foundation.service`. Neither unit has an `[Install]`
section. The audio unit stops at ALSA-card/raw-microphone readiness; speaker
routing remains a separate safety gate. These bridges are temporary hardware
qualification tools, not the final standalone Arch implementation.

Audio additionally refuses to start unless the radio bridge completed cleanly
and no ModemManager process exists. Its qualification therefore requires a
fresh, separate boot before modem or GNSS testing.

The image composer therefore has two mutually exclusive profiles. The default
`coexistence` profile starts radio, Bluetooth, AudioReach and the protected
speaker path while keeping ModemManager masked. The `cellular` profile starts
only the radio foundation and ModemManager; Bluetooth and every AudioReach
bridge remain stopped. In either profile the rollback watchdog stays armed
until native DSI/GPU qualification and the selected profile checks succeed.
For `cellular`, qualification requires a published modem with raw and NMEA GPS
capabilities, but it does not enable GNSS, mobile data, SMS or voice calls.
