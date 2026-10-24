<!-- SPDX-License-Identifier: MIT -->
# Myron reference baseline

Audit date: 2026-10-24. This is a read-only capture of the existing
postmarketOS implementation and live POCO F8 Ultra. No package, service,
session, boot slot, partition, or firmware state was changed.

## Source state

| Source | Revision | State |
| --- | --- | --- |
| Omarchy Mobile | `b7d1080fcae756986636bb3f2ce18968decebe16` | clean before this port work |
| `../myron-postmarketos` | `a19c29b25a5e87d18a8234159694844a485fd497` | heavily modified working reference; treated as read-only |
| Live kernel | `6.12.23-android16-5-g5a0e85dd9db0-dirty-4k` | running on the phone |

The postmarketOS checkout contains substantial staged, unstaged, and untracked
bring-up work newer than its HEAD. Paths cited here refer to that working tree,
not only the commit. It must not be cleaned, reset, or used as a disposable
build directory.

## Device identity

| Item | Evidence |
| --- | --- |
| Device | Xiaomi codename `myron`, sold as POCO F8 Ultra |
| Architecture | aarch64 |
| SoC | Qualcomm SM8850; live DT model says Myron based on SM8850 |
| DT compatible | live DT begins `qcom,canoe-mtp`, followed by canoe-family compatibles |
| GPU | Adreno 840 v2 through `/dev/kgsl-3d0` |
| Panel | internal DSI-1, 1200x2608; 60/90/120 Hz modes exposed |
| Root | ext4 on `pmos_root` |

The live `/etc/os-release` currently reports `Nura edge`. That is the
userspace distribution label, not the phone codename. This port is `myron`.

## Live userspace

The phone runs postmarketOS edge with systemd, Plasma Mobile, KWin Wayland,
NetworkManager, PipeWire/WirePlumber, ModemManager, GeoClue, Chrony, and BlueZ.
The graphical account has UID 10000 and a seat0 tty session. SSH also remains
available over WLAN.

Selected installed versions:

| Component | Version |
| --- | --- |
| device package | `device-xiaomi-myron-1-r7` |
| kernel marker | `linux-xiaomi-myron-android-6.12.23-r0` |
| system Mesa | 26.2.5-r0 |
| Hyprland | 0.54.3-r0 |
| Aquamarine | 0.12.0-r0 |
| Plasma Mobile | 6.8.1-r1 |
| ModemManager | 1.25.95_git20261005-r0 |
| PipeWire / WirePlumber | 1.6.9-r0 / 0.5.18-r2 |

At capture time Plasma, SSH, NetworkManager, Chrony, and the Myron GPU,
cellular, touch, audio, battery-authentication, and KWin RT-time guard services
were active. Four pre-existing failed units remained: nftables, zram swap, an
old serial getty, and a stale session scope. These are baseline defects, not
caused by this port.

## Graphics baseline

KWin maps the isolated Attempt105 EGL, GLES, Gallium, GBM, and Turnip
libraries. The system Mesa package is newer but is not equivalent. The proven
environment is:

```text
LD_LIBRARY_PATH=/var/lib/myron-experiments/attempt105-gpu-wayland/mesa
LIBGL_DRIVERS_PATH=/var/lib/myron-experiments/attempt105-gpu-wayland/mesa/dri
MESA_LOADER_DRIVER_OVERRIDE=zink
VK_DRIVER_FILES=/var/lib/myron-experiments/attempt105-gpu-wayland/freedreno-kgsl.json
```

The renderer was verified as `zink Vulkan 1.4(Adreno (TM) 840
(MESA_TURNIP))`; llvmpipe is not accepted. Exact provenance and the Arch
rebuild boundary are in [GPU-STACK.md](GPU-STACK.md).

## Hyprland result

Two separate milestones are proven in the reference system:

1. Nested Hyprland ran inside KWin with a native Wayland foot client and the
   Attempt105 renderer.
2. A bounded native test acquired card0, renderD128, KGSL, and DSI-1 at
   1200x2608@60, detected `focaltech_ts`, and rendered for 65 seconds. Plasma
   recovered automatically before the independent 90-second rollback timer.

The native result is recorded in
`../myron-postmarketos/experiments/systemd-native-hyprland/experiment.md`.
It proves compositor viability on the current downstream kernel. It does not
prove an Arch boot, suspend, mobile shell completeness, or long-term stability.

## Connectivity baseline

- Wi-Fi is connected with full NetworkManager connectivity.
- The Qualcomm modem is registered at home on LTE and 5G NR, with a live data
  connection. The implementation deliberately uses a one-shot activation
  because reopening stock IPA can panic the kernel.
- GNSS has produced a live fix through patched ModemManager and GeoClue in the
  reference system. No coordinates or device identifiers are captured here.
- Bluetooth reaches an initialized BlueZ controller, but discovery times out;
  pairing and Bluetooth audio are not working.
- Calls and SMS remain unimplemented.

## Current user-visible defect

KWin survived the bounded lock/unlock crash test after the RT-time guard, but
PIN submission can still grey out indefinitely. Treat lock authentication as
BROKEN until the PAM/session path is diagnosed. Do not represent the RT-time
fix as a complete lock-screen fix.

## Boot and recovery boundary

Reference documentation says postmarketOS occupies slot A and Android plus
recovery remain available through slot B. The running Linux command line did
not expose a useful slot suffix, so this arrangement is not independently
revalidated by the live capture.

Omarchy Mobile's current installer assumes Linux on slot B and writes
`userdata`. It is therefore disabled for Myron. The descriptor's
`BOOT_METHOD=external-android` makes rootfs, module-push, kexec, fastboot,
`images`, `flash`, `push`, and both installer modes fail before container or
phone access. No boot image or partition name is encoded in the Myron target.
