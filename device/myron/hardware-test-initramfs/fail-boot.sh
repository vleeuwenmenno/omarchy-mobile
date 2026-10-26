# shellcheck shell=sh

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
		boot_rollback=$hostroot/home/menno/myron-boot_a-rollback-20261026.img
		target=
		found_device=
		find_partition init_boot_a && target=$found_device
		expected=$(/bin/cat "$expected_file" 2>/dev/null || true)
		case "$expected" in *[!0-9a-f]*|'') expected= ;; esac
		boot_target=
		boot_needs_restore=0
		boot_ready=1
		if [ @BOOT_ROLLBACK_ENABLED@ -eq 1 ]; then
			found_device=
			find_partition boot_a && boot_target=$found_device
			boot_ready=0
			if [ -n "$boot_target" ] && [ -b "$boot_target" ] &&
				[ "$(/bin/blockdev --getsize64 "$boot_target" 2>/dev/null)" = 100663296 ] &&
				[ "$(/bin/stat -c %s "$boot_rollback" 2>/dev/null)" = 100663296 ] &&
				[ "$(/bin/sha256sum "$boot_rollback" | /bin/awk '{print $1}')" = @ROLLBACK_BOOT_SHA256@ ]; then
				boot_actual=$(/bin/sha256sum "$boot_target" | /bin/awk '{print $1}')
				case "$boot_actual" in
					@CANDIDATE_BOOT_SHA256@) boot_needs_restore=1; boot_ready=1 ;;
					@ROLLBACK_BOOT_SHA256@) boot_ready=1 ;;
				esac
			fi
		fi
		if [ "${#expected}" -eq 64 ] && [ -n "$target" ] && [ -b "$target" ] &&
			[ "$boot_ready" -eq 1 ] &&
			[ "$(/bin/blockdev --getsize64 "$target" 2>/dev/null)" = 8388608 ] &&
			[ "$(/bin/sha256sum "$target" | /bin/awk '{print $1}')" = "$expected" ] &&
			[ "$(/bin/stat -c %s "$rollback" 2>/dev/null)" = 8388608 ] &&
			[ "$(/bin/sha256sum "$rollback" | /bin/awk '{print $1}')" = @ROLLBACK_SHA256@ ]; then
			if [ "$boot_needs_restore" -eq 1 ]; then
				/bin/dd if="$boot_rollback" of="$boot_target" bs=1048576 conv=fsync &&
					/bin/sync &&
					[ "$(/bin/sha256sum "$boot_target" | /bin/awk '{print $1}')" = @ROLLBACK_BOOT_SHA256@ ] ||
					boot_ready=0
			fi
			if [ "$boot_ready" -eq 1 ] &&
				/bin/dd if="$rollback" of="$target" bs=1048576 conv=fsync &&
				/bin/sync &&
				[ "$(/bin/sha256sum "$target" | /bin/awk '{print $1}')" = @ROLLBACK_SHA256@ ]; then
				rollback_state=$hostroot/var/lib/omarchy-mobile
				/bin/mkdir -p "$rollback_state"
				printf 'result=restored\nreason=%s\n' "$stage" \
					>"$rollback_state/hardware-test.rollback-complete.new"
				/bin/chmod 0600 "$rollback_state/hardware-test.rollback-complete.new"
				/bin/mv -f "$rollback_state/hardware-test.rollback-complete.new" \
					"$rollback_state/hardware-test.rollback-complete"
				/bin/rm -f "$rollback_state/hardware-test.armed" \
					"$rollback_state/hardware-test.disarm"
				/bin/sync
				/bin/reboot -f
			fi
		fi
	fi
	/bin/reboot-to-bootloader
	while :; do /bin/sleep 60; done
}
