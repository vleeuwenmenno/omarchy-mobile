<!-- SPDX-License-Identifier: MIT -->
# Myron persistent Omarchy main boot

Status: implemented and tested offline only. Nothing here has run on the
phone. This is the persistent main boot for the existing Myron slot-A
`init_boot` method, not a general installer. It is separate from the temporary
900 s rollback test in [HARDWARE-TEST.md](HARDWARE-TEST.md), which keeps its
own builder, init, watchdog and tests, unchanged in behavior.

## What it does

The main `init_boot_a` init mounts the preserved postmarketOS root
(`pmos_root`), proves it, and then chooses what to boot:

| Condition at init (first match wins) | Boots |
| --- | --- |
| no deployed main image | postmarketOS |
| main state not provably root-only (whole ancestor chain) | postmarketOS |
| recovery latch present (any object, even an empty or odd one) | postmarketOS |
| pending attempt whose boot never committed, or a malformed one | postmarketOS, and the latch is set durably |
| image link, owner, mode, hard-link count, size or filesystem identity wrong | postmarketOS (no latch: a deploy problem, not a boot) |
| otherwise | **Omarchy** (default) |

A normal reboot after a qualified boot has no pending attempt and always
selects Omarchy. A pending attempt only causes recovery after a boot that never
reached `commit` (power loss, hang, crash, early reboot).

Everything lives in `/var/lib/omarchy-mobile/main/` on the pmOS root (root
only, mode 700):

| File | Meaning |
| --- | --- |
| `rootfs.img` | the Omarchy payload, a mutable ext4 image, root, mode 600, one link |
| `rootfs.meta` | `size=<bytes>` and `fs_uuid=<32 hex>` of the deployed image |
| `pending` | `boot_id` of the boot in progress and the image id, written durably before the payload is mounted |
| `success` | `boot_id` and image id of the last qualified boot |
| `latch` | recovery latch; only `resume` removes it |
| `guard.log` | bounded guard and control log |

The runtime does not hash the mutable image: the deploy step proves the exact
hash once, and every boot checks size, ownership, mode, link count and the ext4
superblock UUID against `rootfs.meta`. `/var/lib/omarchy-mobile` must be root
owned, mode 755 or stricter, with no symlink and no group or world write bit
anywhere on the path. Deploy into a fresh inode: write the image next to the
final name, set mode 600 and owner root, `fsync`, then `mv` it into place.

### Order inside the init

1. The original vendor-module and logfs setup.
2. Mount `pmos_root`, require an executable systemd, the `../lib/systemd/systemd`
   init link and the pmOS identity. Without a provable fallback nothing is
   attempted and the init goes to the bootloader, as the original did.
3. Select (above) before the USB gadget exists.
4. Write the pending token (the kernel `boot_id`) durably, then loop-mount the
   payload and check: systemd, `ID=omarchy`, the unsigned development marker,
   profile `cellular`, the main guard unit, the recovery unit and the control.
5. Copy BusyBox and its musl loader to `/run/myron-main/`, create the NCM-only
   USB rescue gadget (no ACM, no console, no shell), write the compatibility arm
   marker `hardware-test.armed` with `mode=main`, and move the mounts.
6. A failure up to step 5's moves unwinds everything (moved mounts, payload,
   loop device, gadget, runtime files, marker) and hands the SAME init to the
   preserved pmOS root. No partition is written. After `switch_root` there is no
   same-boot fallback: the guard unit and the latch are the recovery path.

The init never copies the temporary partition writer into the runtime and does
not use the temporary arm gate.

### In the Omarchy boot

The existing hardware units gate on `hardware-test.armed` and on
`myron-hardware-watchdog.service`. The main-only overlay replaces that unit
with the main guard (same name, different job):

* `guard-preflight` as `ExecStartPre`: the pending token must be this boot's
  `boot_id`, no latch, state trusted; otherwise the unit fails.
* `guard` waits up to 1200 s of uptime. A commit ends it with exit 0 and the
  unit stays active (`RemainAfterExit=yes`), so nothing that requires it is
  stopped and no 900 s timer remains. At the deadline it takes the lock,
  re-checks for a commit, otherwise sets the latch durably and asks systemd for a
  normal reboot (never the bootloader), with a forced plain reboot after 120 s.
* `myron-main-recover.service` is `OnFailure=` of the guard, the qualifier,
  the cellular unit, the preparation unit and the battery-secret unit. It
  latches and reboots once; after a commit it does nothing.
* `myron-omarchy-qualify` keeps every GPU, DSI, touch and cellular-profile check.
  After them, when `/run/myron-main/boot-id` exists, it runs
  `myron-main-os commit`, which verifies: no latch; this boot's pending token;
  the running image id; `sshd.service` active and a listener on port 22; the
  `usb0` rescue address; NetworkManager; the Wi-Fi import service; the
  battery-secret service with a valid capacity and `Good` health. It does not
  require a USB cable, a charger, internet, a nearby access point or cellular
  data. Its unit bound is 1100 s, under the 1200 s guard.

Only the cellular profile is supported. The main boot starts the modem and
Wi-Fi baseline but does not activate cellular data. `myron-cellular-stage`
refuses the main runtime in `require_runtime_gates`: its time gates depend on
the temporary rollback deadline. Audio and Bluetooth stay isolated from the
cellular profile, as before.

### Control

```
myron-main-os status
myron-main-os recover [--reason WORD]
myron-main-os resume
myron-main-os commit
```

`status` reads only. `recover` (root) sets the latch and reboots normally.
`resume` (root, from the preserved postmarketOS only, identity checked) clears
`pending` and `success` while the latch still exists, flushes, removes the
latch last, and reboots normally into Omarchy. Mutations share one `flock`.
After the latch is set, nothing loops: pmOS does not re-enter Omarchy until
`resume`.

## Build

Offline, no device contact. Base must be the exact release-v3 `init_boot`.

```fish
tools/myron-build-main-init-boot \
  --base-init-boot ../myron-postmarketos/artifacts/candidates/init_boot_a-pmos-systemd-release-v3.img \
  --out out/private/init_boot_a-myron-main.img
```

The Omarchy payload is composed with the explicit main policy (the default
stays `temporary`):

```fish
tools/myron-dev-image-compose --boot-policy main --profile cellular \
  --base-image /abs/base.ext4 --module-stage /abs/modules --runtime-stage /abs/runtime \
  --bluetooth-probe /abs/probe.py --speaker-reference-repo /abs/ref \
  --firstboot-conf /abs/firstboot.conf --ssh-key /abs/owner.pub --out /abs/main-rootfs.img
```

## Deploy (attended, parent-run; nothing below is automatic)

1. On pmOS, as root, create `/var/lib/omarchy-mobile` (755) and `main` (700).
2. Copy the composed image to `main/rootfs.img.new`, check its SHA-256 against
   the composer's `.sha256`, `chmod 600`, `fsync`, then `mv` it to `rootfs.img`.
3. Write `main/rootfs.meta` (mode 600) with the exact byte size and
   `fs_uuid` from `dumpe2fs -h`, 32 hex digits without dashes.
4. Install `device/myron/main-overlay/usr/local/sbin/myron-main-os` on pmOS as
   `/usr/local/sbin/myron-main-os` (root, 755). It is the same file as the one
   in the payload.
5. Only then write the main `init_boot_a` (separate, attended step).

The first qualified Omarchy boot is the success criterion; mark the slot good
only after it. Slot-A retries are limited, so avoid extra reboots.

## Run and recover (fish)

```fish
ssh root@172.16.42.1 myron-main-os status
ssh root@172.16.42.1 myron-main-os recover --reason manual   # latch, reboot to pmOS
ssh root@<pmos-address> myron-main-os resume                 # clear latch, reboot to Omarchy
```

A failed or unqualified boot leaves the latch set: the phone comes up in
postmarketOS, and a later `resume` is the only way back.

## Limitations

* Not a release configuration. The payload is the unsigned development image.
* Cellular profile only; no automatic data activation; no audio or Bluetooth
  coexistence.
* No same-boot fallback after `switch_root`; the guard's 1200 s deadline plus a
  normal reboot is the recovery path, and a hang that stops the guard and the
  kernel needs the human's force-restart.
* The latch and pending files are trusted only if the state tree passes the
  ownership checks; otherwise pmOS is chosen.
* Slot-A boot-attempt counters, partition metadata repair and marking a slot
  successful are outside this change.
* The NCM host interface profile is the operator's, as before.
* Tests: `tests/myron-main` (also run by `tests/all`). It uses fixtures and
  mocks, plus the original AArch64 BusyBox under `qemu-aarch64-static` when the
  pinned base image and the tools are present. No device was touched.
