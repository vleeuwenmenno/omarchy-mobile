# Create NCM before leaving the vendor ramdisk. Arch keeps the gadget and gets
# a static rescue address from systemd-networkd.
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
gadget=/config/usb_gadget/g1
/bin/mkdir -p "$gadget/strings/0x409" "$gadget/configs/c.1/strings/0x409" ||
	fail_boot gadget-create-failed
printf '0xEF\n' >"$gadget/bDeviceClass"
printf '0x02\n' >"$gadget/bDeviceSubClass"
printf '0x01\n' >"$gadget/bDeviceProtocol"
printf '0x1d6b\n' >"$gadget/idVendor"
printf '0x0104\n' >"$gadget/idProduct"
printf 'MyronOmarchy0001\n' >"$gadget/strings/0x409/serialnumber"
printf 'Omarchy Mobile\n' >"$gadget/strings/0x409/manufacturer"
printf 'Myron temporary hardware test\n' >"$gadget/strings/0x409/product"
printf 'ACM console and NCM rescue network\n' >"$gadget/configs/c.1/strings/0x409/configuration"
/bin/mkdir "$gadget/functions/acm.usb0" || fail_boot acm-create-failed
/bin/ln -s "$gadget/functions/acm.usb0" "$gadget/configs/c.1/acm.usb0" ||
	fail_boot acm-link-failed
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
attempt=0
while [ "$attempt" -lt 30 ] && [ ! -r /sys/class/tty/ttyGS0/dev ]; do
	attempt=$((attempt + 1))
	/bin/sleep 1
done
[ -r /sys/class/tty/ttyGS0/dev ] || fail_boot ttygs0-missing
tty_numbers=$(/bin/cat /sys/class/tty/ttyGS0/dev)
tty_major=${tty_numbers%:*}
tty_minor=${tty_numbers#*:}
[ -c /dev/ttyGS0 ] || /bin/mknod /dev/ttyGS0 c "$tty_major" "$tty_minor"

wait_partition pmos_root || fail_boot pmos-root-missing
root_device=$found_device
/bin/mkdir -p /hostroot /newroot
/bin/mount -t ext4 -o rw,noatime "$root_device" /hostroot || fail_boot pmos-root-mount-failed
valid_rootfs_identity \
	/hostroot/usr/lib/os-release \
	/hostroot/lib/apk/db/installed \
	/hostroot/var/lib/myron-modules/systemd-core/installed.sha256 ||
	fail_boot pmos-root-identity-invalid

payload=/hostroot/home/menno/myron-omarchy-hardware-test-20261025.img
[ "$(/bin/stat -c %s "$payload" 2>/dev/null)" = @PAYLOAD_SIZE@ ] ||
	fail_boot omarchy-payload-size-mismatch
[ "$(/bin/sha256sum "$payload" | /bin/awk '{print $1}')" = @PAYLOAD_SHA256@ ] ||
	fail_boot omarchy-payload-hash-mismatch

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
/bin/mount -t ext4 -o rw,noatime "$payload_loop" /newroot || fail_boot omarchy-payload-mount-failed
[ -x /newroot/usr/lib/systemd/systemd ] || fail_boot omarchy-systemd-missing
[ "$(/bin/readlink /newroot/sbin/init 2>/dev/null)" = ../lib/systemd/systemd ] ||
	fail_boot omarchy-systemd-link-invalid
/bin/grep -Fqx 'ID=omarchy' /newroot/etc/os-release || fail_boot omarchy-os-release-mismatch
/bin/grep -Fqx 'development-only: unsigned package repository' \
	/newroot/var/lib/omamobile/repo/aarch64/.omamobile-dev-unsigned ||
	fail_boot omarchy-unsigned-marker-missing

state=/hostroot/var/lib/omarchy-mobile
/bin/mkdir -p "$state" /hostroot/var/log /newroot/dev /newroot/proc /newroot/sys \
	/newroot/run /newroot/mnt/logfs /newroot/lib /newroot/tmp
/bin/rm -f "$state/hardware-test.disarm"
printf 'payload_sha256=@PAYLOAD_SHA256@\nwatchdog_seconds=@WATCHDOG_SECONDS@\n' \
	>"$state/hardware-test.armed.new"
/bin/mv -f "$state/hardware-test.armed.new" "$state/hardware-test.armed"

/bin/mkdir -p /run/myron-watchdog /run/myron-host
/bin/cp /bin/busybox /run/myron-watchdog/busybox
/bin/cp /bin/reboot-to-bootloader /run/myron-watchdog/reboot-to-bootloader
/bin/cp /watchdog /run/myron-watchdog/watchdog
/bin/chmod 0755 /run/myron-watchdog/*
/bin/cp /lib/ld-musl-aarch64.so.1 /newroot/lib/ld-musl-aarch64.so.1
/bin/ln -snf ld-musl-aarch64.so.1 /newroot/lib/libc.musl-aarch64.so.1
/bin/cp /bin/busybox /newroot/tmp/busybox
/bin/chroot /newroot /tmp/busybox true || fail_boot watchdog-runtime-invalid
/bin/rm -f /newroot/tmp/busybox
/bin/mount -o move /hostroot /run/myron-host || fail_boot omarchy-host-move-failed
write_marker omarchy-switch-root-ready
[ "$logfs_mounted" -eq 0 ] || /bin/umount /mnt/logfs || fail_boot logfs-unmount-failed
logfs_mounted=0

/bin/mount -o move /proc /newroot/proc || fail_boot proc-move-failed
/bin/mount -o move /sys /newroot/sys || fail_boot sys-move-failed
/bin/mkdir -p /newroot/sys/kernel/config
/bin/mount -o move /config /newroot/sys/kernel/config || fail_boot config-move-failed
/bin/mount -o move /run /newroot/run || fail_boot run-move-failed
/bin/mount -o move /dev /newroot/dev || fail_boot dev-move-failed

# systemd starts the rollback watchdog before sysinit.target.  Starting it as
# an initramfs child proved unreliable across switch_root: the first native
# Arch boot reached userspace but left an empty watchdog log.  The unit is
# independent of the graphical session and starts before any first-boot work.
/bin/chroot /newroot /run/myron-watchdog/busybox setsid \
	/run/myron-watchdog/busybox sh -c \
	'exec /run/myron-watchdog/busybox sh -i </dev/ttyGS0 >/dev/ttyGS0 2>&1' &
console_pid=$!
printf '%s\n' "$console_pid" >/newroot/run/myron-acm-console.pid
/bin/sync
exec /bin/switch_root /newroot /sbin/init
fail_boot omarchy-switch-root-returned
