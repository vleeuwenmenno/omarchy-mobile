#!/run/myron-watchdog/busybox sh
set -eu

state=/run/myron-host/var/lib/omarchy-mobile
target=/dev/block/by-name/init_boot_a
rollback=/run/myron-host/home/menno/myron-init_boot_a-rollback-20261025.img
boot_rollback_enabled=@BOOT_ROLLBACK_ENABLED@
boot_rollback=/run/myron-host/home/menno/myron-boot_a-rollback-20261026.img

say() { printf '%s\n' "$*"; }
bootloader() {
	say "result=bootloader reason=$1"
	/run/myron-watchdog/reboot-to-bootloader
	while :; do /run/myron-watchdog/busybox sleep 60; done
}

make_unique_partition_node() {
	partition_name=$1
	node_path=$2
	reason_prefix=$3
	partition_matches=0
	partition_major=
	partition_minor=
	for uevent in /sys/class/block/*/uevent; do
		[ -r "$uevent" ] || continue
		/run/myron-watchdog/busybox grep -q "^PARTNAME=$partition_name\$" "$uevent" || continue
		major=$(/run/myron-watchdog/busybox sed -n 's/^MAJOR=//p' "$uevent")
		minor=$(/run/myron-watchdog/busybox sed -n 's/^MINOR=//p' "$uevent")
		[ -n "$major" ] && [ -n "$minor" ] || bootloader "$reason_prefix-node-numbers-invalid"
		partition_matches=$((partition_matches + 1))
		partition_major=$major
		partition_minor=$minor
	done
	[ "$partition_matches" -eq 1 ] || bootloader "$reason_prefix-node-count-$partition_matches"
	/run/myron-watchdog/busybox mknod "$node_path" b "$partition_major" "$partition_minor" ||
		bootloader "$reason_prefix-node-create-failed"
}

if [ ! -b "$target" ]; then
	target=/run/myron-watchdog/init_boot_a
	make_unique_partition_node init_boot_a "$target" init-boot
fi

boot_target=
if [ "$boot_rollback_enabled" -eq 1 ]; then
	boot_target=/dev/block/by-name/boot_a
	if [ ! -b "$boot_target" ]; then
		boot_target=/run/myron-watchdog/boot_a
		make_unique_partition_node boot_a "$boot_target" boot
	fi
fi

say 'state=armed timeout=@WATCHDOG_SECONDS@'
/run/myron-watchdog/busybox sleep @WATCHDOG_SECONDS@
if [ -f "$state/hardware-test.disarm" ]; then
	say 'result=disarmed'
	exit 0
fi
[ -f "$state/hardware-test.armed" ] || bootloader armed-marker-missing
expected="$(/run/myron-watchdog/busybox cat "$state/hardware-test-init-boot.sha256" 2>/dev/null || true)"
case "$expected" in *[!0-9a-f]*|'') bootloader expected-hash-invalid ;; esac
[ "${#expected}" -eq 64 ] || bootloader expected-hash-length
[ -b "$target" ] || bootloader init-boot-node-missing
[ "$(/run/myron-watchdog/busybox blockdev --getsize64 "$target")" = 8388608 ] ||
	bootloader init-boot-size-mismatch
actual="$(/run/myron-watchdog/busybox sha256sum "$target" | /run/myron-watchdog/busybox awk '{print $1}')"
[ "$actual" = "$expected" ] || bootloader init-boot-current-hash-mismatch
[ "$(/run/myron-watchdog/busybox stat -c %s "$rollback" 2>/dev/null)" = 8388608 ] ||
	bootloader rollback-size-mismatch
rollback_hash="$(/run/myron-watchdog/busybox sha256sum "$rollback" | /run/myron-watchdog/busybox awk '{print $1}')"
[ "$rollback_hash" = @ROLLBACK_SHA256@ ] || bootloader rollback-hash-mismatch
boot_needs_restore=0
if [ "$boot_rollback_enabled" -eq 1 ]; then
	[ -b "$boot_target" ] || bootloader boot-node-missing
	[ "$(/run/myron-watchdog/busybox blockdev --getsize64 "$boot_target")" = 100663296 ] ||
		bootloader boot-size-mismatch
	boot_actual="$(/run/myron-watchdog/busybox sha256sum "$boot_target" | /run/myron-watchdog/busybox awk '{print $1}')"
	case "$boot_actual" in
		@CANDIDATE_BOOT_SHA256@) boot_needs_restore=1 ;;
		@ROLLBACK_BOOT_SHA256@) boot_needs_restore=0 ;;
		*) bootloader boot-current-hash-mismatch ;;
	esac
	[ "$(/run/myron-watchdog/busybox stat -c %s "$boot_rollback" 2>/dev/null)" = 100663296 ] ||
		bootloader boot-rollback-size-mismatch
	[ "$(/run/myron-watchdog/busybox sha256sum "$boot_rollback" | /run/myron-watchdog/busybox awk '{print $1}')" = @ROLLBACK_BOOT_SHA256@ ] ||
		bootloader boot-rollback-hash-mismatch
fi
say 'state=restoring reason=qualification-timeout'
if [ "$boot_needs_restore" -eq 1 ]; then
	/run/myron-watchdog/busybox dd if="$boot_rollback" of="$boot_target" bs=1048576 conv=fsync ||
		bootloader boot-rollback-write-failed
	/run/myron-watchdog/busybox sync
	[ "$(/run/myron-watchdog/busybox sha256sum "$boot_target" | /run/myron-watchdog/busybox awk '{print $1}')" = @ROLLBACK_BOOT_SHA256@ ] ||
		bootloader boot-rollback-readback-mismatch
fi
/run/myron-watchdog/busybox dd if="$rollback" of="$target" bs=1048576 conv=fsync ||
	bootloader rollback-write-failed
/run/myron-watchdog/busybox sync
readback="$(/run/myron-watchdog/busybox sha256sum "$target" | /run/myron-watchdog/busybox awk '{print $1}')"
[ "$readback" = @ROLLBACK_SHA256@ ] || bootloader rollback-readback-mismatch
/run/myron-watchdog/busybox printf 'result=restored\nreason=qualification-timeout\n' \
	>"$state/hardware-test.rollback-complete.new"
/run/myron-watchdog/busybox chmod 0600 "$state/hardware-test.rollback-complete.new"
/run/myron-watchdog/busybox mv -f "$state/hardware-test.rollback-complete.new" \
	"$state/hardware-test.rollback-complete"
/run/myron-watchdog/busybox rm -f "$state/hardware-test.armed" "$state/hardware-test.disarm"
/run/myron-watchdog/busybox sync
say 'result=restored reboot=normal'
/run/myron-watchdog/busybox reboot -f
while :; do /run/myron-watchdog/busybox sleep 60; done
