<!-- SPDX-License-Identifier: MIT -->
# Myron feature-preservation matrix

Snapshot: 2026-10-24. Status describes the postmarketOS reference, not Arch.
Every working row is a regression-protected requirement for the port.

Statuses: `VERIFIED_WORKING`, `PARTIAL`, `EXPERIMENTAL`, `PRESENT_UNTESTED`,
`BROKEN`, `UNKNOWN`.

## Display, input, and graphics

| Feature | Status | Evidence and Arch acceptance |
| --- | --- | --- |
| Internal OLED / DSI | VERIFIED_WORKING | DSI-1 drove Plasma and native Hyprland. Arch must light the internal panel through msm_drm without software rendering. |
| Resolution / refresh | VERIFIED_WORKING | Kernel exposes 1200x2608 at 60/90/120 Hz; 60 Hz native Hyprland and 120 Hz recovered Plasma were observed. |
| Touchscreen | VERIFIED_WORKING | `focaltech_ts` event7; physical touch and bounded native Hyprland input capture passed. |
| Buttons | VERIFIED_WORKING | Power and volume inputs present and used in the reference shell. |
| Brightness | VERIFIED_WORKING | `panel0-backlight`, range 0-16383; Plasma control proven. |
| DisplayPort | PRESENT_UNTESTED | card0-DP-1 exists and was disconnected during audit. |
| Rotation / motion sensors | BROKEN | No accelerometer/gyro integration; only ADC IIO devices appeared live. |
| Haptics | PRESENT_UNTESTED | `qcom-hv-haptics` input device exists; no attended vibration test recorded. |
| Qualcomm DRM/KMS | VERIFIED_WORKING | card0 is msm_drm/qcom SDE; direct native Hyprland modeset passed. |
| KGSL | VERIFIED_WORKING | `/dev/kgsl-3d0`, Adreno840v2; KWin/Hyprland and apps opened it. |
| Turnip / Vulkan | VERIFIED_WORKING | Attempt105 selected Adreno 840 MESA_TURNIP. |
| Zink / OpenGL / GLES | VERIFIED_WORKING | EGL GBM, Wayland, surfaceless, and device paths reported Zink on Turnip. |
| GBM / EGL | VERIFIED_WORKING | Custom libgbm and libEGL were mapped by compositors and validated by eglinfo. |
| DMA-BUF sharing | EXPERIMENTAL | Working compositor/app paths imply basic sharing; KWin needs udmabuf isolation and no standalone matrix is recorded. |
| Explicit / implicit sync | PRESENT_UNTESTED | Calibrated timestamp support is disabled for KGSL; sync correctness needs dedicated soak/probes. |

## Connectivity and location

| Feature | Status | Evidence and Arch acceptance |
| --- | --- | --- |
| Wi-Fi | VERIFIED_WORKING | Connected, DHCP/DNS/IPv4 internet and full NetworkManager connectivity. Preserve stock-extracted modules/firmware and service order. |
| Bluetooth controller | PARTIAL | Exact WCN786x firmware/NVM, hci0 and a powered BlueZ controller pass. A bounded run once counted one anonymous event, but an attended JBL scan found no devices and HCI scan commands timed out. Discovery, pairing and reconnect are not working. |
| USB networking / SSH | VERIFIED_WORKING | USB NCM rescue and key-based SSH proven; WLAN SSH also works. Arch needs an independent rescue link. |
| SIM detection | VERIFIED_WORKING | ModemManager exposes an active registered modem without recording identifiers. |
| LTE / 5G registration | VERIFIED_WORKING | Home registration with LTE and 5G NR observed. |
| Mobile data | VERIFIED_WORKING | One-shot boot activation, IPv4 browsing, streaming, and a 64 MiB transfer passed. Reconnect is unsafe. |
| Mobile reconnect | BROKEN | Reopening stock IPA can panic `ipam.ko`; reboot is the current recovery. |
| SMS | BROKEN | Not implemented. |
| Voice calls | BROKEN | Telephony and call audio are not implemented. |
| GNSS / GPS | VERIFIED_WORKING | Patched ModemManager/GeoClue produced a 31-satellite fix and stopped GPS after client exit. |
| NFC | BROKEN | No live NFC class device and no integration. |

## Audio

| Feature | Status | Evidence and Arch acceptance |
| --- | --- | --- |
| Speaker output | VERIFIED_WORKING | Omarchy opened the physical three-channel TDM graph with the amplifiers off, then completed one 250 ms 440 Hz probe at -45 dBFS. All three TFA amplifiers reached ready state, returned to Powerdown, and stayed below 49 C. |
| Earpiece | UNKNOWN | No verified call/earpiece route. |
| Microphones | PARTIAL | Omarchy AudioReach captured one second at 48 kHz with 41,615 nonzero samples, discarded the recording, and restored mixer state. PipeWire app path and quality remain open. |
| Headphones / USB audio | PRESENT_UNTESTED | No attended route test recorded. |
| Bluetooth audio | PRESENT_UNTESTED | Controller discovery works, but pairing and PipeWire Bluetooth routing remain untested. |
| Audio routing | EXPERIMENTAL | Pulse bridge and speaker graph work on the live reference; transitions, mute, suspend/resume, and clean build remain open. |
| Qualcomm DSP / AudioReach | PARTIAL | Checkpointed Omarchy bring-up passed mapper, transport, ADSP/Q6, codecs, ALSA devnodes and FastRPC. Canoe ACDB system-path packaging was fixed; suspend/restart stability remains open. |
| PipeWire / WirePlumber | PARTIAL | Installed, but SSH `wpctl` showed no sink/source in that remote context; application playback evidence comes from dedicated tests. |

## Power

| Feature | Status | Evidence and Arch acceptance |
| --- | --- | --- |
| Battery percentage | VERIFIED_WORKING | Live battery supply reports capacity, temperature, voltage, and current. UPower may label the battery device discharging from instantaneous current while correctly reporting external power globally. |
| Charging | VERIFIED_WORKING | Battery authentication and about 45 W from a 65 W PD source were proven on the reference system. Exact manifest-pinned authentication and a read-only Omarchy qualification stage are now packaged; Omarchy execution remains pending. |
| USB-C power detection | VERIFIED_WORKING | USB_PD supply online with voltage/current readings. |
| Thermal sensors | VERIFIED_WORKING | GPU qualification gates track named CPU/GPU/battery sensors and enforce limits. |
| CPU/GPU scaling | PRESENT_UNTESTED | Required GPU governor modules exist; no Arch policy or full scaling matrix yet. |
| Screen-off behavior | PARTIAL | DSI can be disabled while locked; current PIN path can hang. |
| Suspend/resume | PRESENT_UNTESTED | Kernel advertises freeze, mem, disk and s2idle/deep; production suspend not validated. |
| Deep sleep | PRESENT_UNTESTED | Advertised but not qualified. |
| Wake sources | UNKNOWN | No systematic wake-source matrix. |

## Other hardware

| Feature | Status | Evidence and Arch acceptance |
| --- | --- | --- |
| Cameras | PARTIAL | Qualcomm request manager/sync and 27 subdevices were proven earlier; current userspace exposes no video/media nodes and no frame capture. |
| Flashlight / torch | VERIFIED_WORKING | Plasma toggle and intensity slider passed after reboot. |
| Fingerprint | BROKEN | Not integrated. |
| Accelerometer | BROKEN | Not integrated. |
| Gyroscope | BROKEN | Not integrated. |
| Proximity | BROKEN | Not integrated. |
| Ambient light | BROKEN | Not integrated. |
| Storage | VERIFIED_WORKING | Persistent ext4 `pmos_root`; current public install path intentionally absent. |
| RTC / time | PARTIAL | PMIC RTC counter exists; counter-offset bootstrap plus Chrony works, writable wall-clock RTC does not. |
| Lock authentication | BROKEN | PIN submission currently waits indefinitely despite compositor stability. |

## Temporary Omarchy r5 delta (2026-10-25)

These results describe the temporary Arch payload, not the postmarketOS
reference statuses above:

- **Verified on Omarchy:** native DSI/Hyprland, isolated Zink/Turnip compositor
  and native Wayland application rendering, touch, both DMA-heap names, USB
  and WLAN SSH, persistent managed `wlan0`, Wi-Fi scan/association/IPv4/DNS,
  modem discovery and home LTE/5G registration, and a bounded six-satellite
  GNSS fix, raw built-in microphone capture, a guarded low-volume physical
  speaker graph, and WCN786x firmware/NVM initialization with a powered BlueZ
  controller. Nautilus and GNOME Maps mapped without
  the r4 swapchain failure.
- **Partially verified on Omarchy:** Bluetooth controller publication but not
  discovery or pairing; battery and USB-PD reporting; backlight
  writes with a broken zero `actual_brightness` readback; low-intensity torch
  activation; power/volume input nodes and shell bindings without attended
  physical key events.
- **Safety constraint on Omarchy:** starting AudioReach after
  ModemManager/GNSS caused an immediate hard reboot. A later separate clean
  boot passed the checkpointed mapper, ADSP, codec, microphone and speaker
  path; mixing those subsystem sequences remains forbidden.
- **Present but unverified on Omarchy:** UPower UI and haptics. Only two ADC
  IIO nodes exist, and no camera/media or fingerprint node is exposed.
- **Not integrated on Omarchy:** SMS, voice calls/call audio, fingerprint and
  camera capture. The current reference boot also exposes no camera/media or
  fingerprint character nodes, and only two ADC IIO devices.

## Evidence sources

- `../myron-postmarketos/README.md`
- `../myron-postmarketos/config/myron-rootfs-feature-matrix.tsv`
- `../myron-postmarketos/docs/STATUS.md`
- `../myron-postmarketos/docs/AUDIO_INPUT_OUTPUT.md`
- `../myron-postmarketos/experiments/systemd-native-hyprland/experiment.md`
- read-only live audit on 2026-10-24

Permanent Arch integration remains unqualified until a reproducible built
rootfs passes each probe. The temporary r5 evidence advances only the features
listed in its delta; a graphical boot cannot advance unrelated hardware rows.
