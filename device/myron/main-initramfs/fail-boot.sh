# shellcheck shell=sh
# Main-boot failure handling. Replaces the original fail_boot. Before
# switch_root a failure unwinds everything this init created (moved mounts,
# payload mount, loop device, USB gadget, runtime files, compatibility arm
# marker) and hands off to the preserved postmarketOS root with the SAME init:
# no partition is ever written. After switch_root there is no same-boot
# fallback: the guard unit and the persistent latch are the recovery path.
hostroot=/hostroot
hostroot_mounted=0
pmos_ready=0
newroot_mounted=0
host_moved=0
loop_dev=
gadget_made=0
config_mounted=0
armed_written=0
moved_mounts=

# Undo one move from the newest first: /newroot/<where> back to <from>.
main_unmove() {
	for entry in $(printf '%s\n' "$moved_mounts" | /bin/tr ' ' '\n' | /bin/tac); do
		case $entry in
			proc) /bin/mount -o move /newroot/proc /proc || true ;;
			sys) /bin/mount -o move /newroot/sys /sys || true ;;
			config) /bin/mount -o move /newroot/sys/kernel/config /config || true ;;
			run) /bin/mount -o move /newroot/run /run || true ;;
			dev) /bin/mount -o move /newroot/dev /dev || true ;;
		esac
	done
	moved_mounts=
}

main_gadget_teardown() {
	gadget=/config/usb_gadget/g1
	[ "$gadget_made" -eq 1 ] || return 0
	printf '\n' >"$gadget/UDC" 2>/dev/null || true
	/bin/rm -f "$gadget/configs/c.1/ncm.usb0"
	/bin/rmdir "$gadget/configs/c.1/strings/0x409" "$gadget/configs/c.1" \
		"$gadget/functions/ncm.usb0" "$gadget/strings/0x409" "$gadget" 2>/dev/null || true
	gadget_made=0
}

main_unwind() {
	main_unmove
	if [ "$host_moved" -eq 1 ]; then
		/bin/mount -o move /run/myron-host /hostroot || true
		host_moved=0
	fi
	if [ "$armed_written" -eq 1 ]; then
		/bin/rm -f "$hostroot/var/lib/omarchy-mobile/hardware-test.armed" \
			"$hostroot/var/lib/omarchy-mobile/hardware-test.armed.new"
		armed_written=0
	fi
	main_gadget_teardown
	if [ "$config_mounted" -eq 1 ]; then
		/bin/umount /config || true
		config_mounted=0
	fi
	[ "$newroot_mounted" -eq 0 ] || { /bin/umount /newroot || true; newroot_mounted=0; }
	[ -z "$loop_dev" ] || { /bin/losetup -d "$loop_dev" || true; loop_dev=; }
	# Nothing of the Omarchy runtime may be visible to postmarketOS.
	# rmdir only: if the host move-back failed, /run/myron-host is a live mount.
	/bin/rm -rf /run/myron-main
	/bin/rmdir /run/myron-host 2>/dev/null || true
}

# Final step of a pmOS selection or fallback: hostroot becomes the new root.
handoff_pmos() {
	main_unwind
	main_log "handoff-pmos reason=$1"
	/bin/sync
	[ "$logfs_mounted" -eq 0 ] || /bin/umount /mnt/logfs || true
	logfs_mounted=0
	/bin/mount -o move /hostroot /newroot || fail_boot_dead pmos-move-failed
	hostroot_mounted=0
	/bin/mkdir -p /newroot/dev /newroot/proc /newroot/sys /newroot/run /newroot/var/log
	printf 'candidate=main-init-1\nstage=pmos-handoff\nreason=%s\n' "$1" \
		>/newroot/var/log/myron-systemd-initramfs.state
	/bin/mount -o move /dev /newroot/dev || fail_boot_dead dev-move-failed
	/bin/mount -o move /proc /newroot/proc || fail_boot_dead proc-move-failed
	/bin/mount -o move /sys /newroot/sys || fail_boot_dead sys-move-failed
	/bin/mount -o move /run /newroot/run || fail_boot_dead run-move-failed
	/bin/sync
	# shellcheck disable=SC2093
	exec /bin/switch_root /newroot /sbin/init
	fail_boot_dead pmos-switch-root-returned
}

# No operating system can be started: fastboot is the only useful state.
fail_boot_dead() {
	write_marker "$1" || true
	/bin/sync
	[ "$logfs_mounted" -eq 0 ] || /bin/umount /mnt/logfs || true
	/bin/sleep 5
	/bin/reboot-to-bootloader
	while :; do /bin/sleep 60; done
}

fail_boot() {
	write_marker "$1" || true
	if [ "$pmos_ready" -eq 1 ]; then
		main_log "main-failed stage=$1"
		handoff_pmos "failed-$1"
	fi
	fail_boot_dead "$1"
}
