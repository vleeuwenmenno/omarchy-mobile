#!/run/myron-watchdog/busybox sh
# Rollback watchdog for the temporary Omarchy hardware test.
#
#   watchdog --preflight   check every rollback precondition, then exit.
#                          Writes nothing to a partition and never reboots.
#                          Exit 78 and a fixed "reason=" line on any failure.
#   watchdog               check the same preconditions, arm, sleep, and at the
#                          deadline restore slot A (init_boot_a, and boot_a
#                          only when the boot rollback is enabled) or fall back
#                          to the bootloader.
#
# Partition nodes are never taken from /dev/block/by-name.  Each run derives its
# own node under /run/myron-watchdog from the one sysfs entry whose PARTNAME
# matches exactly, and checks the node's major:minor against that entry.
# Slot B and every other partition are never read or written.  No setrw:
# a partition that reports read-only is refused, never made writable.
set -eu

bb=/run/myron-watchdog/busybox
reboot_bootloader=/run/myron-watchdog/reboot-to-bootloader
node_dir=/run/myron-watchdog
sysfs_block=/sys/class/block
proc_uptime=/proc/uptime
host_log=/run/myron-host/var/log/myron-omarchy-watchdog.log
state=/run/myron-host/var/lib/omarchy-mobile
rollback=/run/myron-host/home/menno/myron-init_boot_a-rollback-20261025.img
boot_rollback=/run/myron-host/home/menno/myron-boot_a-rollback-20261026.img
init_size=8388608
boot_size=100663296
boot_rollback_enabled=@BOOT_ROLLBACK_ENABLED@
rollback_sha=@ROLLBACK_SHA256@
candidate_boot_sha=@CANDIDATE_BOOT_SHA256@
rollback_boot_sha=@ROLLBACK_BOOT_SHA256@
log_cap=262144
event_limit=64

target=$node_dir/init_boot_a.blk
boot_target=$node_dir/boot_a.blk
events=0
boot_needs_restore=0
expected=

say() { printf '%s\n' "$*"; }
sync_log() { "$bb" sync || :; }

# Bounded, timestamped stage line.  Stage events stop at event_limit per run
# and when the persistent log passes log_cap; result lines never stop.
stage() {
	[ "$events" -lt "$event_limit" ] || return 0
	log_size=$("$bb" stat -c %s "$host_log" 2>/dev/null || echo 0)
	[ "$log_size" -lt "$log_cap" ] || return 0
	events=$((events + 1))
	up=unknown
	read -r up _ <"$proc_uptime" 2>/dev/null || up=unknown
	now=$("$bb" date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || echo unknown)
	say "event=$1 mode=$mode ts=$now uptime=$up"
}
# Stage line flushed to storage before something that can fail or reboot.
stage_durable() {
	stage "$1"
	sync_log
}

# Evidence first, then the bootloader.  The sync keeps the reason on disk.
bootloader() {
	say "result=bootloader reason=$1"
	sync_log
	"$reboot_bootloader"
	while :; do "$bb" sleep 60; done
}
# A failed precondition: preflight records and exits, the armed run falls back.
refuse() {
	if [ "$mode" = preflight ]; then
		say "result=preflight-failed reason=$1"
		sync_log
		exit 78
	fi
	bootloader "$1"
}

# Hex digest of file $1; empty when it cannot be read, which never matches.
sha_of() {
	digest_line=$("$bb" sha256sum "$1" 2>/dev/null) || return 0
	printf '%s\n' "${digest_line%% *}"
}

# Make $2 a block node for the one partition whose sysfs PARTNAME is exactly $1.
# An existing node is kept only when it is a block node with that major:minor.
resolve_node() {
	partition_name=$1
	node_path=$2
	reason_prefix=$3
	partition_matches=0
	partition_major=
	partition_minor=
	for uevent in "$sysfs_block"/*/uevent; do
		[ -r "$uevent" ] || continue
		"$bb" grep -q "^PARTNAME=$partition_name\$" "$uevent" || continue
		major=$("$bb" sed -n 's/^MAJOR=//p' "$uevent")
		minor=$("$bb" sed -n 's/^MINOR=//p' "$uevent")
		case "$major$minor" in *[!0-9]*) refuse "$reason_prefix-node-numbers-invalid" ;; esac
		[ -n "$major" ] && [ -n "$minor" ] || refuse "$reason_prefix-node-numbers-invalid"
		partition_matches=$((partition_matches + 1))
		partition_major=$major
		partition_minor=$minor
	done
	[ "$partition_matches" -eq 1 ] || refuse "$reason_prefix-node-count-$partition_matches"
	want_rdev=$(printf '%x:%x' "$partition_major" "$partition_minor")
	if [ -e "$node_path" ] || [ -L "$node_path" ]; then
		if "$bb" test -b "$node_path" &&
			[ "$("$bb" stat -c '%t:%T' "$node_path" 2>/dev/null)" = "$want_rdev" ]; then
			return 0
		fi
		"$bb" rm -f "$node_path" || refuse "$reason_prefix-node-stale-remove-failed"
	fi
	"$bb" mknod "$node_path" b "$partition_major" "$partition_minor" ||
		refuse "$reason_prefix-node-create-failed"
	"$bb" test -b "$node_path" || refuse "$reason_prefix-node-not-block"
	[ "$("$bb" stat -c '%t:%T' "$node_path" 2>/dev/null)" = "$want_rdev" ] ||
		refuse "$reason_prefix-node-rdev-mismatch"
}

# Node, exact size, and not read-only.  blockdev --getro only; never --setrw.
check_target() {
	resolve_node "$1" "$2" "$3"
	[ "$("$bb" blockdev --getsize64 "$2" 2>/dev/null)" = "$4" ] || refuse "$3-size-mismatch"
	ro=$("$bb" blockdev --getro "$2" 2>/dev/null) || refuse "$3-getro-failed"
	[ "$ro" = 0 ] || refuse "$3-read-only"
}

# Rollback image: exact size and hash.
check_image() {
	[ "$("$bb" stat -c %s "$1" 2>/dev/null)" = "$2" ] || refuse "$3-size-mismatch"
	[ "$(sha_of "$1")" = "$4" ] || refuse "$3-hash-mismatch"
}

# Every rollback precondition.  Called before arming and again at the deadline.
check_all() {
	expected="$("$bb" cat "$state/hardware-test-init-boot.sha256" 2>/dev/null || true)"
	case "$expected" in *[!0-9a-f]* | '') refuse expected-hash-invalid ;; esac
	[ "${#expected}" -eq 64 ] || refuse expected-hash-length
	check_target init_boot_a "$target" init-boot "$init_size"
	[ "$(sha_of "$target")" = "$expected" ] || refuse init-boot-current-hash-mismatch
	check_image "$rollback" "$init_size" rollback "$rollback_sha"
	boot_needs_restore=0
	if [ "$boot_rollback_enabled" -eq 1 ]; then
		check_target boot_a "$boot_target" boot "$boot_size"
		boot_actual=$(sha_of "$boot_target")
		case "$boot_actual" in
			"$candidate_boot_sha") boot_needs_restore=1 ;;
			"$rollback_boot_sha") boot_needs_restore=0 ;;
			*) refuse boot-current-hash-mismatch ;;
		esac
		check_image "$boot_rollback" "$boot_size" boot-rollback "$rollback_boot_sha"
	fi
}

# Re-check one target immediately before its write: same node, still writable,
# still holding the hash the earlier check accepted.
recheck_write() {
	check_target "$1" "$2" "$3" "$4"
	[ "$(sha_of "$2")" = "$5" ] || bootloader "$3-pre-write-hash-mismatch"
}

mode=run
case "${1:-}" in
	'') ;;
	--preflight) mode=preflight ;;
	*)
		say "result=usage reason=unknown-argument"
		exit 64
		;;
esac

stage "start"
if [ "$mode" = preflight ]; then
	[ -f "$state/hardware-test.armed" ] || refuse armed-marker-missing
	check_all
	stage_durable "preflight-ok"
	say "result=preflight-ok"
	exit 0
fi

check_all
stage_durable "armed"
say 'state=armed timeout=@WATCHDOG_SECONDS@'
"$bb" sleep @WATCHDOG_SECONDS@
stage "deadline"
if [ -f "$state/hardware-test.disarm" ]; then
	say 'result=disarmed'
	sync_log
	exit 0
fi
[ -f "$state/hardware-test.armed" ] || bootloader armed-marker-missing
check_all
stage_durable "restoring"
say 'state=restoring reason=qualification-timeout'
if [ "$boot_needs_restore" -eq 1 ]; then
	recheck_write boot_a "$boot_target" boot "$boot_size" "$candidate_boot_sha"
	"$bb" dd if="$boot_rollback" of="$boot_target" bs=1048576 conv=fsync ||
		bootloader boot-rollback-write-failed
	"$bb" sync
	[ "$(sha_of "$boot_target")" = "$rollback_boot_sha" ] ||
		bootloader boot-rollback-readback-mismatch
	stage_durable "boot-restored"
fi
recheck_write init_boot_a "$target" init-boot "$init_size" "$expected"
"$bb" dd if="$rollback" of="$target" bs=1048576 conv=fsync ||
	bootloader rollback-write-failed
"$bb" sync
readback="$(sha_of "$target")"
[ "$readback" = "$rollback_sha" ] || bootloader rollback-readback-mismatch
"$bb" printf 'result=restored\nreason=qualification-timeout\n' \
	>"$state/hardware-test.rollback-complete.new"
"$bb" chmod 0600 "$state/hardware-test.rollback-complete.new"
"$bb" mv -f "$state/hardware-test.rollback-complete.new" \
	"$state/hardware-test.rollback-complete"
"$bb" rm -f "$state/hardware-test.armed" "$state/hardware-test.disarm"
stage "init-boot-restored"
say 'result=restored reboot=normal'
sync_log
"$bb" reboot -f
while :; do "$bb" sleep 60; done
