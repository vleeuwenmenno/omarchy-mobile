<!-- SPDX-License-Identifier: MIT -->
# Myron temporary Omarchy hardware test

Status: the r5 temporary Arch payload booted and qualified native DSI,
Hyprland, touch, DMA-heap-backed application rendering, the isolated GPU stack,
Wi-Fi, modem registration, a GNSS fix, the built-in microphone and a guarded
low-volume speaker path on 2026-10-25. Audio remains isolated to a separate
clean boot because the r4 mixed radio/audio sequence hard-reset the phone.

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

## r5 live evidence

The r5 payload booted in about 104 seconds and retained USB NCM SSH. It passed
the 90-second Hyprland window on `DSI-1` at 1200x2608 with scale `2.0`; the
touch device and Squeekboard were present. Both DMA-heap names resolved to the
same `248:1` character device with `0660 root:video` permissions. A separate
Wayland EGL client reported Zink on Adreno 840 Turnip. Its complete `eglinfo`
run returned nonzero because unrelated GBM and X11 platform probes failed, so
the qualifier now isolates and evaluates only the bounded `Wayland platform:`
section. It still rejects a timeout, a missing Wayland section, llvmpipe or
swrast before disarming rollback.

Nautilus and GNOME Maps both mapped as native Wayland clients without the r4
DMA-heap, swapchain or `VK_ERROR_OUT_OF_DEVICE_MEMORY` failures. The shell,
app grid and keyboard remained running. The panel backlight accepted bounded
writes and restored its configured value, although the downstream
`actual_brightness` attribute remained zero and needs a visible attended
check. A one-step white flash LED test read back and restored zero. Battery
sysfs reported 100%, charging, good health and USB-PD supplies.

The exact CNSS link rule produced `wlan0` for the managed interface; `wlp1s0`
was correctly the P2P interface. NetworkManager scanned seven access points,
associated through the preserved reference profile, obtained DHCP, resolved
DNS and supported SSH over WLAN. The patched ModemManager discovered the modem,
registered home, attached packet service, reported LTE plus 5G NR and 59%
signal. No bearer, APN, SMS or voice action was performed.

The first Location-tile attempt failed closed because MSA and MSB A-GPS are
mutually exclusive. The helper now follows the proven reference sequence:
enable MSB first, then raw GPS and NMEA, with cleanup on partial failure. The
corrected helper obtained a GGA fix in six seconds using six satellites,
suppressed coordinates from logs, disabled every managed source afterwards,
and left the modem registered.

## First boot and mobile shell fixes

The temporary first boot no longer waits on unsupported nftables/UFW setup.
It records that the firewall is deferred instead of claiming protection is
active. It also defers Omarchy's network-only Mise/developer-tool provisioning
until Wi-Fi exists, while still applying the packaged mobile shell profile.
No completion marker is forged, so the full user provisioner can be run later.

The r5 overlay supplies the `omamobile-gnss` command expected by the Location
quick-setting tile. It uses the qualified Qualcomm ModemManager raw, NMEA and
MSB-assisted location path rather than installing the Pixel-specific Broadcom
GNSS package. The modem still advertises MSA capability, but the helper never
enables mutually exclusive MSA and MSB together.

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
qualified on a separate fresh boot, before ModemManager or GNSS. The
`myron-audio-stage` runner advances only through `arm`, `mapper`, `transport`,
`adsp`, `codecs`, `devnodes`, and `fastrpc`. It syncs the current stage and each
module insertion to the postmarketOS root before acting. `arm` removes the
graphical disarm marker while the original 900-second rollback watchdog is
still active; it never restarts that independent supervisor. It then requires
20 seconds of radio and `wlan0` stability before permitting the mapper stage.
A hard reset therefore restores postmarketOS on the next boot, while the
persistent log identifies the last attempted operation. Do not retry a failed
stage in the same boot. Speaker output is not part of these stages and remains
a separate low-volume safety test.

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

The initial r5 pair that booted and was then live-patched with the qualifier
and GNSS fixes was:

```text
539b328f43b31fa5919c94008cdf974a221c74e6201f0c90c83a2ddd3429c9ee  myron-omarchy-hardware-test-20261025-r5.img
285bbb7598401f56c092c63fedce3b05f284095cefa54d0d69002ec0e73f6bf9  init_boot_a-myron-omarchy-hardware-test-20261025-r5-v1.img
```

This pair is evidence, not the reproducible successor: rebuild both artifacts
after the committed live fixes before another boot. The initramfs watchdog
remains 900 seconds, writes only `init_boot_a`, checks both candidate and
rollback hashes, and never references a slot-B partition. Its successor also
detects a second candidate boot with an armed test and no disarm marker; that
path restores postmarketOS immediately instead of consuming slot retry counts
after a hard reset.

The r5-v4 pair used for the isolated audio qualification was:

```text
cf6183e84dfdf69cb74f780122c40ba105c973b72c265148c801f09ee6f41552  myron-omarchy-hardware-test-20261025-r5-v4.img
2f8819377008ef6bbf4e8543bc831c4a58db955b64825768095310c762691e5a  init_boot_a-myron-omarchy-hardware-test-20261025-r5-v4.img
```

Boot `c4f228e9-0695-4357-9e3e-20a68b90648a` qualified native DSI and
Adreno 840/Turnip again. With ModemManager and GNSS stopped, the checkpointed
audio path passed mapper replacement, ten transport modules, ADSP/Q6 startup,
the codec/amplifier/machine closure, ALSA device nodes, FastRPC, and read-only
`dsp_b` speaker dependency staging. The raw built-in microphone captured
48,128 frames at 48 kHz, including 41,615 nonzero samples, then discarded the
recording and restored its mixer controls. The physical three-channel TDM
speaker graph first passed for 250 ms with TFA in Powerdown, then completed one
250 ms 440 Hz probe at approximately -45 dBFS. PMIC temperature remained below
49 C and all three amplifiers returned to Powerdown.

That run exposed three packaging gaps rather than driver failures: the Canoe
ACDB file and current `backend_conf.xml`/`card-defs.xml` were isolated in the
runtime stage but absent or stale at their canonical `/etc` paths, and the
speaker graph needed `CFCM.so.1` plus `SAPlusCmnModule.so.1` from `dsp_b`.
The composer now publishes the verified configs. The new `speaker-dsp` stage
mounts exactly one size-checked `dsp_b` read-only and copies only those two
hash-pinned files; proprietary bytes remain outside this repository. Rebuild
the payload after these committed fixes before treating the pair as the next
reproducible candidate.

The offline Bluetooth successor is private and untracked:

```text
1cb4c637c788b4c81b25f79b5d969e1fff74d4d030d7269dc8cca54b9f354ccb  myron-omarchy-hardware-test-20261025-r5-v8.img
1a47033951c09f18b32c496b9afc2a3344c60e7a3ddd599a551c234472938240  init_boot_a-myron-omarchy-hardware-test-20261025-r5-v8.img
```

It retained the 900-second slot-A-only rollback image. Earlier v6/v7 builds
were superseded before deployment by stronger
same-boot replay protection, private transient-log permissions and
signal-triggered cleanup. The v8 boot qualified DSI/GPU and radio, then refused
Bluetooth before module insertion when one thermal reading reached 94.6 C.
That run also exposed an unbounded inactive-BlueZ cleanup call; v8 is retired.
The next candidate adds hard cleanup timeouts and records the hottest sensor
name with each reading.

That corrected offline pair is:

```text
bd0294ff8edd36c66b4ae6290e51292f26ebe415dbb99f25edf0ec61d66df570  myron-omarchy-hardware-test-20261025-r5-v9.img
be238f661b6c8f445e90cf544f768110cd8ed39338ee1b2b7e41c3712f3b8d9b  init_boot_a-myron-omarchy-hardware-test-20261025-r5-v9.img
```

## Isolated Bluetooth stage

Bluetooth must use another fresh boot: ModemManager, GNSS and AudioReach are
all forbidden. `myron-bluetooth-stage` uses the still-running independent
rollback watchdog and advances through `arm`, `start`, and `scan`. `arm`
removes the graphical disarm marker, syncs its state to the postmarketOS root,
and requires 20 seconds of stable radio/Wi-Fi operation. `start` consumes its
one-shot marker before loading any module.

The runner selects the exact GKI module set from the running kernel notes,
hash-pins `rfkill`, `pwrseq-core`, `bluetooth`, `btbcm`, `btqca`, patched
`hci_uart`, stock `btpower`, and the reviewed WCN786x userspace probe. It
mounts exactly one `bluetooth_b` partition `ro,nosuid,nodev,noexec`, then
size- and hash-verifies board-ID-00 `gngbtfw20.mbn` and `gngbtnv20.bin`.
Those proprietary files stay on the phone. BlueZ is started with systemd only;
the Alpine reference probe's OpenRC path is not used.

The stock `btpower.ko` deliberately has the complete vermagic
`6.12.23-android16-5-maybe-dirty-4k SMP preempt mod_unload modversions
aarch64`, while the matched candidate kernel reports the same source through
its Git-describe release token. The GKI loader with modversions accepts this
known stock module; the stage therefore pins its full stock vermagic and hash
instead of incorrectly requiring its first token to equal `uname -r`. All
rebuilt GKI Bluetooth modules still require the exact running release token.

`scan` is bounded to eight seconds. Raw output exists only in `/run`, is mode
`0600`, and is deleted after counting discovery events, so nearby addresses
and names never enter persistent logs. Success powers off the controller,
stops BlueZ and `btattach`, unmounts `bluetooth_b`, and recreates the rollback
disarm marker. Any failed start or scan also attempts full power-off cleanup;
the watchdog remains armed if qualification fails.

The successful v10 scan exposed one cleanup race: after the controller was
powered off and `hci0` disappeared, the desktop D-Bus-activated a new
controller-less BlueZ daemon. Cleanup now runtime-masks `bluetooth.service`
before stopping it and verifies that it stays inactive. The mask lives only in
`/run` and vanishes on reboot.

Run only after the normal DSI/GPU qualification and attended radio start:

```text
sudo myron-bluetooth-stage arm
sudo myron-bluetooth-stage start
sudo myron-bluetooth-stage status
sudo myron-bluetooth-stage scan
```

Emergency cleanup is idempotent:

```text
sudo myron-bluetooth-stage stop
```

## Attended physical-key stage

`myron-input-stage` dynamically resolves the unique `gpio-keys`,
`pmic_pwrkey`, and `pmic_resin` devices instead of trusting unstable event
numbers. It takes exclusive evdev grabs for at most 20 seconds, so the
compositor cannot lock, change volume, or interpret a screenshot chord during
the probe. It requires both press and release for Volume Up, Volume Down, and
Power, persists only per-label counts, and releases every grab on success,
failure, interruption, or timeout.

Run from USB SSH while someone is holding the phone, then press and release
each key once when the `READY` line appears:

```text
sudo myron-input-stage
```

The first v9 hardware run reached the Bluetooth start checkpoint at 62.9 C,
loaded the six exact rebuilt GKI modules, then stopped before inserting
`btpower.ko`: an over-strict userspace check compared the stock module's
`maybe-dirty` release token with the candidate kernel's Git-describe token.
Failure cleanup completed, left `hci0` absent and BlueZ inactive, and the exact
postmarketOS `init_boot_a` was restored. This is a staging-guard failure, not a
Bluetooth hardware result.

The corrected v10 run loaded all six rebuilt GKI modules and the exact stock
`btpower.ko`, initialized WCN786x from the hash-pinned board-ID-00 firmware and
NVM, created `hci0`, and reached a powered BlueZ controller. Its bounded scan
recorded one anonymous event while persisting no nearby identity. That count
was not sufficient discovery evidence. A later attended scan with a JBL
speaker in pairing mode listed no devices; LE scan opcodes timed out. Bluetooth
therefore remains partial: controller publication passes, but discovery,
pairing, reconnect and Bluetooth audio do not. Cleanup
removed `hci0`, unmounted `bluetooth_b`, powered the controller off and
disarmed rollback. The exact postmarketOS `init_boot_a` was then restored;
Plasma, Wi-Fi and the cellular interface returned.

The reference raw-UART experiments localize the failure below BlueZ: repeated
HCI commands work before `HCI Reset`, but the first command after Reset times
out even with UART clocks held on and IBS wake acknowledged. The next bounded
candidate sets `HCI_QUIRK_RESET_ON_CLOSE` before controller registration only
for the explicit userspace-preinitialized WCN786x path. This skips the opening
Reset while leaving every default QCA path unchanged. It requires a newly
built, exact-release `hci_uart.ko` and must pass controller initialization,
known-peer discovery, cleanup and a fresh-boot retry before promotion.

## Cellular profile startup transaction

The first v15 cellular boot exposed an ordering race: enabling
`myron-reference-radio.service` directly caused its marker condition to be
evaluated before any service created the marker. ModemManager then started
without the radio foundation. A guarded live recovery created the marker,
started radio, settled udev and started ModemManager; modem publication and
raw/NMEA location capabilities then qualified without a bearer, SMS or call.

`myron-cellular.service` now owns that exact transaction. It requires the
hardware arm and independent watchdog, rejects Bluetooth and AudioReach,
creates the radio marker, starts the radio foundation, settles udev, starts
ModemManager and writes a readiness marker. Neither the radio foundation nor
ModemManager is independently enabled in a cellular image, removing the boot
race while keeping the rollback watchdog authoritative.

## Battery and charging stage

The next private payload adds the exact 20-file `charging` runtime from the
reference manifest. `myron-batterysecret-start` pins the runtime's own manifest
hash, verifies every file before execution, and launches the stock daemon with
the source-built property shim. Its systemd service is gated by the temporary
host-root arm marker, requires successful Myron hardware preparation, and runs
before the display manager. It does not change charge limits or other sysfs
controls.

After the native session qualifies, run the read-only evidence probe over USB
SSH:

```text
sudo myron-battery-stage
```

It requires the independent rollback watchdog and active authentication
process, validates battery capacity/health/temperature plus USB voltage and
current reporting, and confirms that UPower recognizes external power. It
persists only bounded aggregate readings in the postmarketOS host log. UPower
may report the battery device itself as `discharging` from instantaneous
current direction while its daemon correctly reports `on-battery: no`; the
Omarchy bar uses the daemon-wide external-power state.

The same boot can run the presence-only peripheral inventory:

```text
sudo myron-peripheral-audit
```

It never loads camera or fingerprint modules and never starts ModemManager. It
records only counts and boolean interface presence, so it can establish which
gaps still exist without collecting a SIM, modem, camera, or nearby-device
identifier. Telephony interface evidence must therefore come from a separately
authorized radio boot where ModemManager is already running.

## Next attended sequence

1. Promote the qualified controller/scan sequence into a device-owned package
   without copying proprietary firmware.
2. Add attended physical power/volume, visible brightness and haptics probes.
3. Audit sensors, telephony, fingerprint and camera as isolated subsystem
   phases; none is implied by successful Bluetooth or graphical testing.

Bluetooth pairing/audio, sensors and rotation, telephony, fingerprint and
camera capture remain required later phases; none may be inferred from the
successful graphical, controller-scan or radio tests.
