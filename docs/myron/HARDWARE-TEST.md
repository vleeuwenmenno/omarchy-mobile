<!-- SPDX-License-Identifier: MIT -->
# Myron temporary Omarchy hardware test

Status: the r4 temporary Arch payload booted and qualified native DSI,
Hyprland, touch, the isolated GPU stack, Wi-Fi, modem registration and a GNSS
fix on 2026-10-25. It exposed a missing DMA-heap device node and an unsafe
audio sequencing assumption. postmarketOS has been restored; r5 fixes are
implemented offline but have not yet been boot-tested.

This is a reversible development test around the existing downstream Myron
kernel and extracted runtime assets. It is not the production installer, does
not authorize a general deployment, and does not change the device
descriptor's `external-android` boot method. Slot B contains the owner's
Android installation and is never part of this test.

## r4 live evidence

The r4 Arch root booted the existing
`6.12.23-android16-5-g5a0e85dd9db0-dirty-4k` kernel and passed these attended
checks:

- Hyprland 0.56.2 acquired native DRM/KMS on `DSI-1`, exposing 1200x2608 at
  60, 90 and 120 Hz.
- Hyprland mapped the isolated Myron `libEGL`, `libgbm`, Gallium and Freedreno
  Vulkan libraries, opened card0, renderD128 and KGSL, and reported Zink on
  `Adreno (TM) 840 (MESA_TURNIP)`. No llvmpipe mapping was present.
- Touch reached Hyprland after Xiaomi THP raw mode was disabled. Omarchy's
  status bar, launcher, app grid and Squeekboard rendered on DSI-1.
- The attended display scale is `2.0` (600x1304 logical pixels), with a
  separate `1.8` portrait keyboard multiplier.
- USB NCM SSH remained available. The independent 15-minute watchdog found
  its disarm marker after the 90-second compositor stability window.

The r4 qualifier recorded:

```text
result=qualified dsi=DSI-1 renderer=isolated-zink-turnip stable_seconds=90 rollback=disarmed
```

Radio qualification then used the disabled, marker-gated reference bridge:

- MSS reached `running`; QRTR and `rmnet_ipa0` appeared without kernel warnings.
- The kernel's `wlan0` was renamed to `wlp1s0` by Arch. Renaming it back and
  restarting NetworkManager allowed a scan of 12 access points, Wi-Fi
  association, IPv4 connectivity and DNS resolution. r5 carries an exact
  systemd link rule for the downstream CNSS PCIe function so the proven
  `wlan0` contract is preserved before NetworkManager starts.
- The packaged patched ModemManager discovered the modem within five seconds.
  It registered on the home network, reported packet attachment, LTE plus 5G
  NR and 55% signal. No bearer, carrier-data, SMS or call action was run.
- The modem advertised raw GPS, NMEA, MSA A-GPS and MSB A-GPS. A bounded GNSS
  test obtained a fix after 60 seconds and logged GGA reports using seven
  satellites. Coordinates were suppressed and GNSS was disabled afterwards.

## r4 application failure and r5 GPU gate

The compositor-only GPU qualifier was insufficient. Nautilus reached Wayland,
but Turnip reported that neither `/dev/dma_heap/system` nor `/dev/ion` could be
opened, then failed `ION_IOC_ALLOC` and swapchain allocation with
`VK_ERROR_OUT_OF_DEVICE_MEMORY`. This explains applications that opened
inconsistently even while Hyprland itself remained accelerated.

r5 creates `/dev/dma_heap/system` and `/dev/dri/dmaheap-sys` from the exact
`/sys/class/dma_heap/system/dev` major/minor pair, with the proven video-group
permissions. The qualifier now verifies both nodes, verifies access as the
Hyprland user, and runs a separate native Wayland `eglinfo -B` client. Rollback
is not disarmed unless that client reports Adreno 840 Turnip and no llvmpipe or
swrast. `mesa-utils`, `vulkan-tools` and `rtkit` are included in the Myron
profile for this qualification and the PipeWire real-time service.

Qt Quick still cannot create usable Wayland EGL surfaces with the isolated
experiment-105 stack in this image. The test session therefore shadows only
the `quickshell` executable with `QT_QUICK_BACKEND=software`; Hyprland and
ordinary applications retain the isolated accelerated stack.

## First boot and mobile shell fixes

The temporary first boot no longer waits on unsupported nftables/UFW setup.
It records that the firewall is deferred instead of claiming protection is
active. It also defers Omarchy's network-only Mise/developer-tool provisioning
until Wi-Fi exists, while still applying the packaged mobile shell profile.
No completion marker is forged, so the full user provisioner can be run later.

The r5 overlay supplies the `omamobile-gnss` command expected by the Location
quick-setting tile. It uses the qualified Qualcomm ModemManager raw, NMEA,
MSA and MSB location sources rather than installing the Pixel-specific
Broadcom GNSS package.

## Audio incident and hard sequencing rule

Audio was incorrectly started after ModemManager and GNSS activity in the r4
boot. Starting the reference AudioReach foundation immediately dropped USB
SSH and rebooted the phone to fastboot before any speaker playback. No pstore
record survived. Repeated boots then exhausted slot A's retry metadata; setting
slot A active again restored its retry count without switching slots. The
known-good postmarketOS `init_boot_a` image was restored and booted. Slot B was
not read or written.

The bridge now refuses audio unless `myron-reference-radio.service` completed
cleanly in the same boot and no ModemManager process exists. Audio must be
qualified on a separate fresh boot, before ModemManager or GNSS, with each
mapper/module/ADSP step observed individually. Speaker output is not part of
the foundation start and remains a separate low-volume safety test.

## Artifact record

The exact r4 pair that produced the evidence above is private and untracked:

```text
09a8127d1febd82c2b9dc04081899a371f07b93a7eb3038f1a415bb4e8c766ff  myron-omarchy-hardware-test-20261025-r4.img
a29dafecfe3236e83fd09141536cc93f1aeafb95cd3daeef1047f4c035c83312  init_boot_a-myron-omarchy-hardware-test-20261025-r4-v1.img
```

The exact known-good postmarketOS rollback image is:

```text
535d8e2fe0db2b35dc003e329fafc2b76dd82705df70cef63dc74accf653ec24  init_boot_a.img
```

The r5 payload and init_boot pair must be rebuilt together after the current
offline tests pass. The initramfs watchdog remains 900 seconds, writes only
`init_boot_a`, checks both candidate and rollback hashes, and never references
a slot-B partition.

## Next attended sequence

1. Boot r5 and qualify DSI, touch, DMA-heap access, Adreno client EGL, shell,
   launcher, Nautilus, brightness, battery reporting and physical buttons.
2. Arm and start only the radio bridge. Verify `wlan0`, Wi-Fi and WLAN SSH.
3. Start patched ModemManager, verify registration, then run one bounded GNSS
   fix. Do not create a cellular bearer or run telephony actions.
4. Restore postmarketOS. On a separate clean r5 boot, qualify audio foundation
   step by step before ModemManager/GNSS, then test microphone and a guarded
   low-volume speaker route.

Bluetooth discovery/audio, sensors and rotation, telephony, fingerprint and
camera capture remain required later phases; none may be inferred from the
successful graphical or radio tests.
