# shellcheck shell=sh
# Persistent main-boot selection. Sourced by the main init after pmos_root is
# mounted at $hostroot and its identity is proven. Nothing here writes a
# partition: it reads and writes only small state files in the main state
# directory, and only after that directory's whole ancestor chain is proven
# root-owned and not group/world writable.
#
# Choice rules, first match wins:
#   no deployed image            -> pmos (not an error)
#   state directory untrusted    -> pmos
#   recovery latch (any object)  -> pmos, sticky until `myron-main-os resume`
#   pending attempt, previous boot never committed or malformed
#                                -> latch (durable) and pmos
#   image link/owner/mode/size/filesystem identity wrong
#                                -> pmos, no latch (deploy problem, not a boot)
#   otherwise                    -> omarchy
# A normal reboot after a qualified (committed) boot has no pending attempt
# and therefore always selects omarchy.
main_root_uid=0
main_root_gid=0
main_log_cap=65536

main_choice=pmos
main_reason=unset
main_id=
main_image_id=

main_log() {
	[ -d "$hostroot/var/log" ] || return 0
	size=$(stat -c %s "$hostroot/var/log/myron-main-boot.log" 2>/dev/null || echo 0)
	[ "$size" -lt "$main_log_cap" ] || return 0
	up=unknown
	read -r up _ </proc/uptime 2>/dev/null || up=unknown
	printf 'uptime=%s %s\n' "$up" "$*" >>"$hostroot/var/log/myron-main-boot.log" 2>/dev/null || return 0
	sync
}

# A directory that is not a link, is owned by root and has no write bit for
# group or others. $2 is the forbidden mode mask (022 ancestors, 077 state).
main_safe_dir() {
	[ -d "$1" ] && [ ! -L "$1" ] || return 1
	dir_info=$(stat -c '%u:%g:%a' "$1" 2>/dev/null) || return 1
	dir_mode=${dir_info##*:}
	dir_owner=${dir_info%:*}
	[ "$dir_owner" = "$main_root_uid:$main_root_gid" ] || return 1
	[ $((0$dir_mode & $2)) -eq 0 ]
}

main_safe_file() {
	[ -f "$1" ] && [ ! -L "$1" ] || return 1
	file_info=$(stat -c '%u:%g:%a:%h' "$1" 2>/dev/null) || return 1
	old_ifs=$IFS
	IFS=:
	# shellcheck disable=SC2086
	set -- $file_info
	IFS=$old_ifs
	[ "$1" = "$main_root_uid" ] && [ "$2" = "$main_root_gid" ] && [ "$4" = 1 ] &&
		[ $((0$3 & 077)) -eq 0 ]
}

main_trust_state() {
	main_safe_dir "$hostroot/var" 022 &&
		main_safe_dir "$hostroot/var/lib" 022 &&
		main_safe_dir "$hostroot/var/lib/omarchy-mobile" 022 &&
		main_safe_dir "$hostroot/var/lib/omarchy-mobile/main" 077
}

# Value of key $2 in file $1: exactly one "key=value" line, else empty.
main_kv() {
	[ "$(grep -c "^$2=" "$1" 2>/dev/null)" = 1 ] || return 0
	sed -n "s/^$2=//p" "$1"
}

main_is_uuid() {
	case $1 in
		????????-????-????-????-????????????) ;;
		*) return 1 ;;
	esac
	case $1 in *[!0-9a-f-]*) return 1 ;; esac
}

main_is_token() {
	case $1 in ''|*[!0-9a-f]*) return 1 ;; esac
	[ "${#1}" -eq "$2" ]
}

main_set_latch() {
	umask 077
	printf 'reason=%s\n' "$1" >"$main_dir/latch.new" &&
		sync &&
		mv -f "$main_dir/latch.new" "$main_dir/latch" &&
		sync
}

# 0 when the image is deployed and exactly what its meta file says.
main_check_image() {
	img=$main_dir/rootfs.img
	meta=$main_dir/rootfs.meta
	main_safe_file "$img" || { main_reason=image-untrusted; return 1; }
	main_safe_file "$meta" || { main_reason=meta-untrusted; return 1; }
	meta_size=$(main_kv "$meta" size)
	meta_uuid=$(main_kv "$meta" fs_uuid)
	case $meta_size in ''|*[!0-9]*) main_reason=meta-size-invalid; return 1 ;; esac
	main_is_token "$meta_uuid" 32 || { main_reason=meta-uuid-invalid; return 1; }
	[ "$(stat -c %s "$img")" = "$meta_size" ] || { main_reason=image-size-mismatch; return 1; }
	# ext4 superblock UUID: 16 bytes at offset 1024 + 104. No whole-image hash:
	# the deploy step proves the exact hash once, the runtime proves identity.
	actual_uuid=$(dd if="$img" bs=1 skip=1128 count=16 2>/dev/null | od -An -tx1 | tr -d ' \n')
	[ "$actual_uuid" = "$meta_uuid" ] || { main_reason=image-identity-mismatch; return 1; }
	main_image_id=$meta_uuid
}

main_select() {
	main_choice=pmos
	main_dir=$hostroot/var/lib/omarchy-mobile/main
	state_dir=$hostroot/var/lib/omarchy-mobile
	if [ ! -e "$main_dir" ] && [ ! -L "$main_dir" ]; then
		main_reason=main-not-deployed
		return 0
	fi
	main_trust_state || { main_reason=state-untrusted; return 0; }
	# Mutating cleanup only inside the proven chain. A leftover compatibility
	# marker from a previous main boot must not reach the temporary
	# hardware-test gate, which would treat it as a failed test.
	if [ -f "$state_dir/hardware-test.armed" ] && [ ! -L "$state_dir/hardware-test.armed" ] &&
		grep -Fxq 'mode=main' "$state_dir/hardware-test.armed"; then
		rm -f "$state_dir/hardware-test.armed"
	fi
	if [ -e "$main_dir/latch" ] || [ -L "$main_dir/latch" ]; then
		main_reason=recovery-latch
		return 0
	fi
	main_check_image || return 0
	if [ -e "$main_dir/pending" ] || [ -L "$main_dir/pending" ]; then
		pending_id=
		pending_image=
		if main_safe_file "$main_dir/pending"; then
			pending_id=$(main_kv "$main_dir/pending" boot_id)
			pending_image=$(main_kv "$main_dir/pending" image_id)
		fi
		committed=0
		if main_is_uuid "$pending_id" && main_safe_file "$main_dir/success" &&
			[ "$(main_kv "$main_dir/success" boot_id)" = "$pending_id" ] &&
			[ "$(main_kv "$main_dir/success" image_id)" = "$pending_image" ]; then
			committed=1
		fi
		if [ "$committed" -eq 1 ]; then
			# Committed, then the pending removal did not finish: still a qualified boot.
			rm -f "$main_dir/pending" && sync
		else
			main_set_latch stale-pending-boot || true
			main_reason=stale-pending-latched
			return 0
		fi
	fi
	main_reason=default-omarchy
	main_choice=omarchy
}

# The current boot's pending token, durable before anything of the payload is
# mounted. A later `commit` only accepts exactly this token.
main_begin_attempt() {
	main_id=$(cat /proc/sys/kernel/random/boot_id 2>/dev/null) || return 1
	main_is_uuid "$main_id" || return 1
	umask 077
	rm -f "$main_dir/pending.new"
	printf 'boot_id=%s\nimage_id=%s\n' "$main_id" "$main_image_id" >"$main_dir/pending.new" &&
		sync &&
		mv -f "$main_dir/pending.new" "$main_dir/pending" &&
		sync
}
