# shellcheck shell=sh
# Main init stage, appended after the original init's module and logfs setup.
# Order: mount and prove pmOS, select, durable pending token, then (only for
# omarchy) payload mount and checks, NCM-only rescue gadget, runtime files and
# the final moves. There is deliberately no ACM console: no unauthenticated
# root shell exists in the main boot.
wait_partition pmos_root || fail_boot pmos-root-missing
root_device=$found_device
/bin/mkdir -p /hostroot /newroot
/bin/mount -t ext4 -o rw,noatime "$root_device" /hostroot || fail_boot pmos-root-mount-failed
hostroot_mounted=1
# The fallback itself must be provably startable before anything is attempted.
[ -x /hostroot/usr/lib/systemd/systemd ] || fail_boot pmos-systemd-pid1-missing
[ "$(/bin/readlink /hostroot/sbin/init 2>/dev/null)" = ../lib/systemd/systemd ] ||
	fail_boot pmos-init-link-invalid
valid_rootfs_identity \
	/hostroot/usr/lib/os-release \
	/hostroot/lib/apk/db/installed \
	/hostroot/var/lib/myron-modules/systemd-core/installed.sha256 ||
	fail_boot pmos-root-identity-invalid
pmos_ready=1

. /main-select.sh
main_select
main_log "selected=$main_choice reason=$main_reason"
write_marker "main-select-$main_choice"
[ "$main_choice" = omarchy ] || handoff_pmos "$main_reason"

main_begin_attempt || fail_boot main-pending-write-failed
state=/hostroot/var/lib/omarchy-mobile
payload=$main_dir/rootfs.img

for uevent in /sys/class/block/loop*/uevent; do
	[ -r "$uevent" ] || continue
	loop_name=$(/bin/sed -n 's/^DEVNAME=//p' "$uevent")
	major=$(/bin/sed -n 's/^MAJOR=//p' "$uevent")
	minor=$(/bin/sed -n 's/^MINOR=//p' "$uevent")
	[ -n "$loop_name" ] && [ -n "$major" ] && [ -n "$minor" ] || continue
	[ -b "/dev/$loop_name" ] || /bin/mknod "/dev/$loop_name" b "$major" "$minor"
done
payload_loop=$(/bin/losetup -f 2>/dev/null)
[ -n "$payload_loop" ] || fail_boot omarchy-no-free-loop-device
/bin/losetup "$payload_loop" "$payload" || fail_boot omarchy-loop-attach-failed
loop_dev=$payload_loop
/bin/mount -t ext4 -o rw,noatime "$payload_loop" /newroot || fail_boot omarchy-payload-mount-failed
newroot_mounted=1
[ -x /newroot/usr/lib/systemd/systemd ] || fail_boot omarchy-systemd-missing
[ "$(/bin/readlink /newroot/sbin/init 2>/dev/null)" = ../lib/systemd/systemd ] ||
	fail_boot omarchy-systemd-link-invalid
/bin/grep -Fqx 'ID=omarchy' /newroot/etc/os-release || fail_boot omarchy-os-release-mismatch
/bin/grep -Fqx 'development-only: unsigned package repository' \
	/newroot/var/lib/omamobile/repo/aarch64/.omamobile-dev-unsigned ||
	fail_boot omarchy-unsigned-marker-missing
# Only the cellular profile is supported by the main boot for now.
[ "$(/bin/cat /newroot/etc/omamobile/myron-test-profile 2>/dev/null)" = cellular ] ||
	fail_boot omarchy-profile-not-cellular
# The payload must carry the main guard unit (same unit name the hardware units
# require) and the main control, never the temporary partition-writing watchdog.
guard_unit=/newroot/usr/lib/systemd/system/myron-hardware-watchdog.service
[ -f "$guard_unit" ] && [ ! -L "$guard_unit" ] ||
	fail_boot omarchy-main-guard-unit-missing
/bin/grep -Fq 'ExecStart=/run/myron-main/bin/busybox sh /run/myron-main/myron-main-os guard' "$guard_unit" ||
	fail_boot omarchy-main-guard-unit-invalid
! /bin/grep -Fq '/run/myron-watchdog' "$guard_unit" || fail_boot omarchy-temporary-watchdog-unit
[ -f /newroot/usr/lib/systemd/system/myron-main-recover.service ] ||
	fail_boot omarchy-main-recover-unit-missing
[ -x /newroot/usr/local/sbin/myron-main-os ] || fail_boot omarchy-main-control-missing

# Runtime for the guard: copied BusyBox plus its musl loader, independent of
# the payload's own shell and libc. The payload root is not trusted to be usable.
/bin/mkdir -p /run/myron-main/bin /newroot/lib /newroot/tmp /newroot/dev /newroot/proc \
	/newroot/sys /newroot/run /newroot/mnt
/bin/cp /bin/busybox /run/myron-main/bin/busybox
/bin/cp /myron-main-os /run/myron-main/myron-main-os
/bin/chmod 0755 /run/myron-main/bin/busybox /run/myron-main/myron-main-os
/bin/cp /lib/ld-musl-aarch64.so.1 /newroot/lib/ld-musl-aarch64.so.1
/bin/ln -snf ld-musl-aarch64.so.1 /newroot/lib/libc.musl-aarch64.so.1
/bin/cp /bin/busybox /newroot/tmp/busybox
/bin/chroot /newroot /tmp/busybox true || fail_boot main-runtime-invalid
/bin/rm -f /newroot/tmp/busybox
/run/myron-main/bin/busybox --install -s /run/myron-main/bin || fail_boot main-runtime-install-failed
printf '%s\n' "$main_id" >/run/myron-main/boot-id
printf '%s\n' "$main_image_id" >/run/myron-main/image-id
/bin/chmod 0600 /run/myron-main/boot-id /run/myron-main/image-id

# NCM only: rescue network, no console, no shell on the gadget.
role_path=/sys/class/usb_role/a600000.ssusb-role-switch/role
attempt=0
while [ "$attempt" -lt 30 ] && [ ! -w "$role_path" ]; do
	attempt=$((attempt + 1))
	/bin/sleep 1
done
[ -w "$role_path" ] || fail_boot usb-role-missing
printf '%s\n' device >"$role_path" || fail_boot usb-role-write-failed
udc_name=
attempt=0
while [ "$attempt" -lt 30 ]; do
	for udc in /sys/class/udc/*; do
		[ -e "$udc" ] || continue
		udc_name=${udc##*/}
		break
	done
	[ -n "$udc_name" ] && break
	attempt=$((attempt + 1))
	/bin/sleep 1
done
[ -n "$udc_name" ] || fail_boot usb-udc-missing
/bin/mkdir -p /config
/bin/mount -t configfs configfs /config || fail_boot configfs-mount-failed
config_mounted=1
gadget=/config/usb_gadget/g1
gadget_made=1
/bin/mkdir -p "$gadget/strings/0x409" "$gadget/configs/c.1/strings/0x409" ||
	fail_boot gadget-create-failed
printf '0xEF\n' >"$gadget/bDeviceClass"
printf '0x02\n' >"$gadget/bDeviceSubClass"
printf '0x01\n' >"$gadget/bDeviceProtocol"
printf '0x1d6b\n' >"$gadget/idVendor"
printf '0x0104\n' >"$gadget/idProduct"
printf 'MyronOmarchy0001\n' >"$gadget/strings/0x409/serialnumber"
printf 'Omarchy Mobile\n' >"$gadget/strings/0x409/manufacturer"
printf 'Myron Omarchy main\n' >"$gadget/strings/0x409/product"
printf 'NCM rescue network\n' >"$gadget/configs/c.1/strings/0x409/configuration"
/bin/mkdir "$gadget/functions/ncm.usb0" || fail_boot ncm-create-failed
printf '02:00:00:00:00:01\n' >"$gadget/functions/ncm.usb0/dev_addr"
printf '02:00:00:00:00:02\n' >"$gadget/functions/ncm.usb0/host_addr"
/bin/ln -s "$gadget/functions/ncm.usb0" "$gadget/configs/c.1/ncm.usb0" ||
	fail_boot ncm-link-failed
printf '%s\n' "$udc_name" >"$gadget/UDC" || fail_boot gadget-bind-failed
attempt=0
while [ "$attempt" -lt 30 ] && [ ! -e /sys/class/net/usb0 ]; do
	attempt=$((attempt + 1))
	/bin/sleep 1
done
[ -e /sys/class/net/usb0 ] || fail_boot usb0-missing
/bin/ifconfig usb0 172.16.42.1 netmask 255.255.255.0 up || fail_boot usb0-address-failed

# Compatibility arm for the existing hardware units. They gate on this file and
# on the guard unit above; the old previous-boot arm gate is not used.
/bin/rm -f "$state/hardware-test.disarm"
printf 'mode=main\nboot_id=%s\nimage_id=%s\n' "$main_id" "$main_image_id" \
	>"$state/hardware-test.armed.new"
armed_written=1
/bin/mv -f "$state/hardware-test.armed.new" "$state/hardware-test.armed"
/bin/sync

/bin/mkdir -p /run/myron-host
/bin/mount -o move /hostroot /run/myron-host || fail_boot omarchy-host-move-failed
host_moved=1
write_marker omarchy-switch-root-ready
[ "$logfs_mounted" -eq 0 ] || /bin/umount /mnt/logfs || fail_boot logfs-unmount-failed
logfs_mounted=0
# From here the fallback must first move every mount back (main_unwind).
/bin/mount -o move /proc /newroot/proc || fail_boot proc-move-failed
moved_mounts="proc"
/bin/mount -o move /sys /newroot/sys || fail_boot sys-move-failed
moved_mounts="$moved_mounts sys"
/bin/mkdir -p /newroot/sys/kernel/config
/bin/mount -o move /config /newroot/sys/kernel/config || fail_boot config-move-failed
moved_mounts="$moved_mounts config"
/bin/mount -o move /run /newroot/run || fail_boot run-move-failed
moved_mounts="$moved_mounts run"
/bin/mount -o move /dev /newroot/dev || fail_boot dev-move-failed
moved_mounts="$moved_mounts dev"
/bin/sync
# Past this point no same-boot fallback exists: the guard unit and the
# persistent latch recover.
exec /bin/switch_root /newroot /sbin/init
fail_boot omarchy-switch-root-returned
