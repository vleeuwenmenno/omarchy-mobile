#!/run/myron-watchdog/busybox sh
set -eu

state=/run/myron-host/var/lib/omarchy-mobile
target=/dev/block/by-name/init_boot_a
rollback=/run/myron-host/home/menno/myron-init_boot_a-rollback-20261025.img

say() { printf '%s\n' "$*"; }
bootloader() {
	say "result=bootloader reason=$1"
	/run/myron-watchdog/reboot-to-bootloader
	while :; do /run/myron-watchdog/busybox sleep 60; done
}

if [ ! -b "$target" ]; then
	target=/run/myron-watchdog/init_boot_a
	for uevent in /sys/class/block/*/uevent; do
		[ -r "$uevent" ] || continue
		/run/myron-watchdog/busybox grep -q '^PARTNAME=init_boot_a$' "$uevent" || continue
		major=$(/run/myron-watchdog/busybox sed -n 's/^MAJOR=//p' "$uevent")
		minor=$(/run/myron-watchdog/busybox sed -n 's/^MINOR=//p' "$uevent")
		[ -n "$major" ] && [ -n "$minor" ] || continue
		/run/myron-watchdog/busybox mknod "$target" b "$major" "$minor" ||
			bootloader init-boot-node-create-failed
		break
	done
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
say 'state=restoring reason=qualification-timeout'
/run/myron-watchdog/busybox dd if="$rollback" of="$target" bs=1048576 conv=fsync ||
	bootloader rollback-write-failed
/run/myron-watchdog/busybox sync
readback="$(/run/myron-watchdog/busybox sha256sum "$target" | /run/myron-watchdog/busybox awk '{print $1}')"
[ "$readback" = @ROLLBACK_SHA256@ ] || bootloader rollback-readback-mismatch
say 'result=restored reboot=normal'
/run/myron-watchdog/busybox reboot -f
while :; do /run/myron-watchdog/busybox sleep 60; done
