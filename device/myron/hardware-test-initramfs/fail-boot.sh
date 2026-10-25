fail_boot() {
	stage=$1
	write_marker "$stage" || true
	hostroot=/hostroot
	if [ ! -f "$hostroot/home/menno/myron-init_boot_a-rollback-20261025.img" ]; then
		hostroot=/hostroot-rollback
		/bin/mkdir -p "$hostroot"
		found_device=
		find_partition pmos_root || found_device=
		[ -n "$found_device" ] &&
			/bin/mount -t ext4 -o rw,noatime "$found_device" "$hostroot" || hostroot=
	fi
	if [ -n "$hostroot" ]; then
		/bin/mkdir -p "$hostroot/var/log"
		printf 'stage=%s\n' "$stage" >"$hostroot/var/log/myron-omarchy-initramfs-failure.log"
		/bin/sync
		expected_file=$hostroot/var/lib/omarchy-mobile/hardware-test-init-boot.sha256
		rollback=$hostroot/home/menno/myron-init_boot_a-rollback-20261025.img
		target=
		found_device=
		find_partition init_boot_a && target=$found_device
		expected=$(/bin/cat "$expected_file" 2>/dev/null || true)
		case "$expected" in *[!0-9a-f]*|'') expected= ;; esac
		if [ "${#expected}" -eq 64 ] && [ -n "$target" ] && [ -b "$target" ] &&
			[ "$(/bin/blockdev --getsize64 "$target" 2>/dev/null)" = 8388608 ] &&
			[ "$(/bin/sha256sum "$target" | /bin/awk '{print $1}')" = "$expected" ] &&
			[ "$(/bin/stat -c %s "$rollback" 2>/dev/null)" = 8388608 ] &&
			[ "$(/bin/sha256sum "$rollback" | /bin/awk '{print $1}')" = @ROLLBACK_SHA256@ ]; then
			/bin/dd if="$rollback" of="$target" bs=1048576 conv=fsync &&
				/bin/sync &&
				[ "$(/bin/sha256sum "$target" | /bin/awk '{print $1}')" = @ROLLBACK_SHA256@ ] &&
				/bin/reboot -f
		fi
	fi
	/bin/reboot-to-bootloader
	while :; do /bin/sleep 60; done
}
