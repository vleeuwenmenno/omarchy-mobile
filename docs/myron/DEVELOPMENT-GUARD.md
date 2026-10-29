<!-- SPDX-License-Identifier: MIT -->
# Myron development timeout policy

On 2026-10-28 the owner explicitly requested removal of the recurring automatic
20-minute reboot during Omarchy development. Both preceding sensor boots
returned to pmOS at uptime 1203 seconds with `reason=guard-timeout`.

## Policy and preserved recovery

The root-owned, mode-0600 file
`/var/lib/omarchy-mobile/main/development-no-timeout` on pmOS contains exactly
the selected rootfs filesystem UUID as 32 lowercase hexadecimal characters
followed by a newline. In Omarchy the same file is beneath `/run/myron-host`.
Only a matching running image disables the guard's wall-clock deadline. The
installed v60 UUID is `a27f454b3ae346698b11ce77dad84b15`.

Absent policy or a different image retains the 1200-second default. Unsafe or
malformed policy fails startup and invokes recovery. Policy is read at guard
startup, not continuously. The guard remains running and watches for a
recovery latch; unit failure recovery, explicit recovery and the next-boot
fallback for an uncommitted attempt are unchanged. This does not qualify or
commit the image. Thermal limits, audio restrictions and one-attempt DSP
rules are unchanged. A silent hang no longer has the general 20-minute
deadline as a fallback; risky hardware tests still need their own finite bound.

The installed initramfs embeds the older control script. The rootfs unit now
runs `myron-main-guard-policy` with the copied initramfs BusyBox before its
existing preflight. Only the matching owner policy selects the new trusted
rootfs control into `/run/myron-main/myron-main-os`. Its original is preserved
as `myron-main-os.embedded`. Replacement is atomic and retains the independent
BusyBox, exact guard entry point and OnFailure recovery. No boot partition or
kernel update is required.

## Targeted deployment

Source files, relative to `device/myron/main-overlay`, are:

- `usr/local/sbin/myron-main-os`
- `usr/local/libexec/myron-main-guard-policy`
- `usr/lib/systemd/system/myron-hardware-watchdog.service`

The targeted installer is retained privately as
`out/private/myron-install-dev-timeout-20261028.sh`; its staged files and hashes
are in `out/private/myron-development-guard-20261028/`. It verifies pmOS,
the installed v60 metadata and size, an unused loop image, the previous control
hash, and staged hashes. It mounts only the Omarchy image file, backs up the
existing control and unit, installs those three files, unmounts, then writes
the image-bound policy. It never invokes a partition writer or reboots.

On-device originals are in
`/var/lib/myron-development-no-timeout-20261028/` on pmOS. The new loader was
previously absent, recorded in `previously-absent`. Metadata is backed up and
unchanged. Resume uses the existing `sudo /usr/local/sbin/myron-main-os resume`
from pmOS; the policy is not a reason to repeat resume on a working Omarchy boot.

## Verification and reversal

`tests/myron-main` passes, including default timeout, simulated passage beyond
1200 seconds with no timeout under the development policy, subsequent failure
latch recovery, commit behavior, different-image isolation, invalid policy
refusal and loader preservation/idempotence. The original AArch64 BusyBox
parser and existing init selection/recovery tests pass. No full rootfs rebuild
or reflash was performed.

Live acceptance requires Omarchy identity, an active/running
`myron-hardware-watchdog.service`, runtime `guard-deadline-seconds` equal to
`0`, current pending token, no latch, and the selected control matching the
repository. A mocked elapsed clock checks deadline behavior without another
20-minute wait. Sensor startup remains manual.

Live verification passed on Omarchy 4.0.6 boot
`e8c0f7d6-ccc2-4fab-a937-fb8b475e52a5`: guard active/running, runtime deadline
`0`, current pending boot/image token and no recovery latch. The runtime control
matches the installed new control (SHA-256
`d413b8ac2e4b46308c48a50ccd8d6c3df92912295913ce0fe54db530cf5c2b3f`);
the preserved embedded original matches the prior hash
`82c9d4a223df47e6f958160b74b1619f887e41d0035c217a495eef62cc7a4a82`.
The live log records `guard-start deadline=0s` at uptime 3 seconds. Audio
experiment and cellular-audio units remain inactive.

The subsequent sensor test failed an immediate capability check after proxy
restart. Its transient test failure hook recovered at uptime 168 seconds with
`reason=unit-failed`, demonstrating that failure recovery was still live; it
was not a deadline expiry. After adding a bounded discovery wait, Omarchy boot
`84e10ba1-3c62-4c09-ad0b-adc353eb2b37` passed sensor startup and all four sensor
capability checks. The guard remains running with deadline zero on that boot.

Manual recovery in Omarchy remains:

```sh
sudo /usr/local/sbin/myron-main-os recover --reason manual
```

To restore the timed profile, remove the policy file from pmOS before the next
resume. The loader then leaves the original embedded guard in place. To undo
the entire rootfs update, while pmOS is running and the image is unmounted,
mount the image, restore the control and unit from the backup paths above,
remove the previously absent loader, then unmount. Do not restart the guard
in a live hardware test merely to change policy.
