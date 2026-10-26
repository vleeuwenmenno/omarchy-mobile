#!/bin/sh
# SPDX-License-Identifier: MIT
# Exact one-shot transaction for Bluetooth discovery qualification only.
set -eu
umask 077

runtime=/run/omamobile-myron
ready=/run/myron-bluetooth-only-ready
profile=/etc/omamobile/myron-test-profile
foundation_ready=/run/myron-bluetooth-foundation-ready
cpufreq_root=/sys/devices/system/cpu/cpufreq
governor_state=$runtime/bluetooth-cpufreq-governors
governor_state_new=$governor_state.new
governor_restore=$governor_state.restore
governor_restore_new=$governor_restore.new
governors_owed=0
bluetooth_stage=/usr/local/sbin/myron-bluetooth-stage
module_dir=/usr/local/lib/myron-wireless/wlan/lib/modules
smem_mailbox=$module_dir/smem-mailbox.ko
smem_mailbox_sha=c8d2f5abdc2a684ccf5ef68fd70700d6863422734a1e20ca8cc1c94ede111c2c
cnss_utils=$module_dir/cnss_utils.ko
cnss_utils_sha=8ddcf0912a9c852a3c33397b004b260b083328091ae1bbf0ef435ba595450267
stock_vermagic='6.12.23-android16-5-maybe-dirty-4k SMP preempt mod_unload modversions aarch64'
cooldown_target_mc=75000
cooldown_timeout_seconds=180
cooldown_stable_samples=4

fail() {
	printf 'ERROR: Myron Bluetooth-only bring-up: %s\n' "$*" >&2
	exit 1
}

load_exact_module() {
	path=$1 name=$2 expected_sha=$3
	[ -f "$path" ] && [ ! -L "$path" ] && [ -s "$path" ] ||
		fail "missing regular prerequisite module: $path"
	[ "$(sha256sum "$path" | awk '{print $1}')" = "$expected_sha" ] ||
		fail "prerequisite module checksum mismatch: $path"
	[ "$(modinfo -F name "$path")" = "$name" ] ||
		fail "prerequisite module name mismatch: $path"
	[ "$(modinfo -F vermagic "$path")" = "$stock_vermagic" ] ||
		fail "prerequisite module metadata mismatch: $path"
	[ ! -d "/sys/module/$name" ] ||
		fail "prerequisite module was already loaded: $name"
	insmod "$path" || fail "prerequisite module insertion failed: $name"
	[ -d "/sys/module/$name" ] || fail "prerequisite module did not remain loaded: $name"
}

hottest_temperature() {
	hottest=0
	hottest_type=unknown
	valid_sensors=0
	for file in /sys/class/thermal/thermal_zone*/temp; do
		[ -r "$file" ] || continue
		type=$(timeout -k 1 2 cat "${file%/temp}/type" 2>/dev/null) || continue
		[ -n "$type" ] || continue
		case "$type" in *-trip-*) continue ;; esac
		value=$(timeout -k 1 2 cat "$file" 2>/dev/null) || continue
		case "$value" in ''|*[!0-9]*) continue ;; esac
		[ "$value" -gt 0 ] && [ "$value" -lt 200000 ] || continue
		valid_sensors=$((valid_sensors + 1))
		[ "$value" -le "$hottest" ] || {
			hottest=$value
			hottest_type=$type
		}
	done
	[ "$valid_sensors" -gt 0 ] || return 1
	printf '%s %s %s\n' "$hottest" "$hottest_type" "$valid_sensors"
}

wait_for_cooldown() {
	deadline=$(( $(awk '{print int($1)}' /proc/uptime) + cooldown_timeout_seconds ))
	stable=0
	while [ "$(awk '{print int($1)}' /proc/uptime)" -lt "$deadline" ]; do
		if ! reading=$(hottest_temperature); then
			stable=0
			printf 'stage=cooldown result=waiting reason=temperature-unavailable stable_samples=0/%s\n' \
				"$cooldown_stable_samples"
			sleep 5
			continue
		fi
		value=${reading%% *}
		reading=${reading#* }
		sensor=${reading%% *}
		valid_sensors=${reading#* }
		if [ "$value" -lt "$cooldown_target_mc" ]; then
			stable=$((stable + 1))
		else
			stable=0
		fi
		printf 'stage=cooldown maximum_mc=%s sensor=%s valid_sensors=%s stable_samples=%s/%s\n' \
			"$value" "$sensor" "$valid_sensors" "$stable" "$cooldown_stable_samples"
		[ "$stable" -lt "$cooldown_stable_samples" ] || {
			printf 'stage=cooldown result=ready target_mc=%s stable_seconds=15\n' \
				"$cooldown_target_mc"
			return 0
		}
		sleep 5
	done
	fail "Bluetooth cooldown did not reach $cooldown_target_mc mC for 15 seconds"
}

governor_path_is_safe() {
	root=$1 policy_id=$2
	case "$policy_id" in ''|*[!0-9]*) return 1 ;; esac
	case "$policy_id" in 0|[1-9]|[1-9][0-9]*) ;; *) return 1 ;; esac
	policy=$root/policy$policy_id
	governor=$policy/scaling_governor
	[ -d "$root" ] && [ ! -L "$root" ] &&
		[ -d "$policy" ] && [ ! -L "$policy" ] &&
		[ -e "$governor" ] && [ ! -L "$governor" ] || return 1
	canonical_root=$(readlink -f -- "$root" 2>/dev/null) || return 1
	canonical_governor=$(readlink -f -- "$governor" 2>/dev/null) || return 1
	[ "$canonical_root" = "$root" ] &&
		[ "$canonical_governor" = "$root/policy$policy_id/scaling_governor" ]
}

validate_governor_file() {
	root=$1 journal=$2
	[ "$governors_owed" -eq 1 ] || return 1
	[ -f "$journal" ] && [ ! -L "$journal" ] && [ -s "$journal" ] || return 1
	last_byte=$(tail -c 1 "$journal" 2>/dev/null | od -An -tu1 | tr -d ' ') || return 1
	[ "$last_byte" = 10 ] || return 1
	line_number=0
	records=0
	declared_records=
	trailer_seen=0
	seen_ids=' '
	while IFS=' ' read -r first second third; do
		line_number=$((line_number + 1))
		if [ "$line_number" -eq 1 ]; then
			[ "$first" = MYRON_CPUFREQ_V1 ] && [ -z "$second$third" ] || return 1
			continue
		fi
		[ "$trailer_seen" -eq 0 ] || return 1
		if [ "$first" = END ]; then
			case "$second" in ''|*[!0-9]*) return 1 ;; esac
			[ -z "$third" ] || return 1
			declared_records=$second
			trailer_seen=1
			continue
		fi
		policy_id=$first
		original=$second
		[ -z "$third" ] || return 1
		case "$original" in ''|*[!A-Za-z0-9_-]*) return 1 ;; esac
		governor_path_is_safe "$root" "$policy_id" || return 1
		case "$seen_ids" in *" $policy_id "*) return 1 ;; esac
		seen_ids="$seen_ids$policy_id "
		records=$((records + 1))
	done <"$journal"
	[ "$line_number" -ge 3 ] && [ "$trailer_seen" -eq 1 ] &&
		[ "$records" -gt 0 ] && [ "$declared_records" = "$records" ]
}

governor_files_match() {
	left_file=$1
	right_file=$2
	match=1
	command exec 3<"$left_file" || return 1
	command exec 4<"$right_file" || {
		command exec 3<&-
		return 1
	}
	while :; do
		left_line=
		right_line=
		if IFS= read -r left_line <&3; then left_status=0; else left_status=$?; fi
		if IFS= read -r right_line <&4; then right_status=0; else right_status=$?; fi
		[ "$left_status" -eq "$right_status" ] || {
			match=0
			break
		}
		[ "$left_status" -eq 0 ] || break
		[ "$left_line" = "$right_line" ] || {
			match=0
			break
		}
	done
	command exec 3<&- || match=0
	command exec 4<&- || match=0
	[ "$match" -eq 1 ]
}

prepare_governor_restore_snapshot() {
	root=$1
	validate_governor_file "$root" "$governor_state" || return 1
	[ ! -e "$governor_restore_new" ] && [ ! -L "$governor_restore_new" ] || return 1
	if [ -e "$governor_restore" ] || [ -L "$governor_restore" ]; then
		validate_governor_file "$root" "$governor_restore" || return 1
	else
		[ ! -e "$governor_restore_new" ] && [ ! -L "$governor_restore_new" ] || return 1
		cp -- "$governor_state" "$governor_restore_new" || return 1
		chmod 0600 "$governor_restore_new" || return 1
		mv -- "$governor_restore_new" "$governor_restore" || return 1
		validate_governor_file "$root" "$governor_restore" || return 1
	fi
	governor_files_match "$governor_state" "$governor_restore"
}

write_governor() {
	printf '%s' "$2" >"$1"
}

read_governor() {
	timeout -k 1 2 cat "$1" 2>/dev/null
}

governor_matches() {
	current_governor=$(read_governor "$1") || return 1
	[ "$current_governor" = "$2" ]
}

restore_governors() {
	root=$1
	prepare_governor_restore_snapshot "$root" || return 1
	restore_ok=1
	restore_records=0
	restore_declared=
	restore_end=0
	command exec 3<"$governor_restore" || return 1
	while IFS=' ' read -r policy_id original extra <&3; do
		[ "$policy_id" = MYRON_CPUFREQ_V1 ] && continue
		if [ "$policy_id" = END ]; then
			restore_declared=$original
			restore_end=1
			break
		fi
		governor=$root/policy$policy_id/scaling_governor
		[ -r "$governor" ] && [ -w "$governor" ] &&
			write_governor "$governor" "$original" &&
			governor_matches "$governor" "$original" || restore_ok=0
		restore_records=$((restore_records + 1))
	done
	command exec 3<&- || return 1
	[ "$restore_end" -eq 1 ] && [ "$restore_records" -gt 0 ] &&
		[ "$restore_declared" = "$restore_records" ] || restore_ok=0
	[ "$restore_ok" -eq 1 ] || return 1
	rm -f -- "$governor_restore" || return 1
	[ ! -e "$governor_restore" ] || return 1
	rm -f -- "$governor_state" || return 1
	[ ! -e "$governor_state" ] || return 1
	governors_owed=0
}

enter_powersave() {
	root=$1
	[ ! -e "$governor_state" ] && [ ! -L "$governor_state" ] ||
		fail 'stale CPU frequency governor journal exists'
	[ ! -e "$governor_state_new" ] && [ ! -L "$governor_state_new" ] ||
		fail 'stale CPU frequency governor journal draft exists'
	[ ! -e "$governor_restore" ] && [ ! -L "$governor_restore" ] &&
		[ ! -e "$governor_restore_new" ] && [ ! -L "$governor_restore_new" ] ||
		fail 'stale CPU frequency governor restore snapshot exists'
	canonical_root=$(readlink -f -- "$root" 2>/dev/null) ||
		fail 'CPU frequency root cannot be resolved'
	[ "$canonical_root" = "$root" ] && [ -d "$root" ] && [ ! -L "$root" ] ||
		fail 'CPU frequency root is unsafe'
	printf '%s\n' MYRON_CPUFREQ_V1 >"$governor_state_new"
	chmod 0600 "$governor_state_new"
	count=0
	for governor in "$root"/policy*/scaling_governor; do
		[ -r "$governor" ] && [ -w "$governor" ] || continue
		policy=${governor%/scaling_governor}
		policy=${policy##*/}
		case "$policy" in policy*) policy_id=${policy#policy} ;; *) continue ;; esac
		governor_path_is_safe "$root" "$policy_id" ||
			fail 'unsafe CPU frequency governor path'
		original=$(timeout -k 1 2 cat "$governor" 2>/dev/null) ||
			fail 'could not read CPU frequency governor'
		case "$original" in ''|*[!A-Za-z0-9_-]*) fail 'invalid CPU frequency governor value' ;; esac
		printf '%s %s\n' "$policy_id" "$original" >>"$governor_state_new"
		count=$((count + 1))
	done
	[ "$count" -gt 0 ] || fail 'no writable CPU frequency governor was available'
	printf 'END %s\n' "$count" >>"$governor_state_new"
	mv -- "$governor_state_new" "$governor_state"
	governors_owed=1
	validate_governor_file "$root" "$governor_state" || fail 'CPU frequency governor journal is invalid'
	while IFS=' ' read -r policy_id original extra; do
		[ "$policy_id" = MYRON_CPUFREQ_V1 ] && continue
		[ "$policy_id" = END ] && break
		governor=$root/policy$policy_id/scaling_governor
		write_governor "$governor" powersave || fail 'could not select temporary powersave governor'
		governor_matches "$governor" powersave ||
			fail 'CPU frequency governor did not enter powersave'
	done <"$governor_state"
	printf 'stage=cooldown governors=powersave count=%s\n' "$count"
}

restore_governors_on_exit() {
	status=$?
	trap - 0 HUP INT TERM
	if [ "$governors_owed" -eq 1 ] && ! restore_governors "$cpufreq_root"; then
		"$bluetooth_stage" stop >/dev/null 2>&1 || true
		printf '%s\n' 'ERROR: Myron Bluetooth-only bring-up: CPU frequency governor restoration failed' >&2
		[ "$status" -ne 0 ] || status=1
	fi
	exit "$status"
}

complete_governor_window() {
	if ! restore_governors "$cpufreq_root"; then
		"$bluetooth_stage" stop >/dev/null 2>&1 || true
		fail 'CPU frequency governor restoration failed; Bluetooth was stopped'
	fi
	printf '%s\n' 'stage=cooldown governors=restored'
	trap - 0 HUP INT TERM
}

[ "$(id -u)" = 0 ] || fail 'must run as root'
[ "$(cat "$profile" 2>/dev/null || true)" = bluetooth ] ||
	fail 'Bluetooth-only profile is not selected'
[ -f /run/myron-host/var/lib/omarchy-mobile/hardware-test.armed ] ||
	fail 'temporary hardware-test arm is absent'
systemctl --quiet is-active myron-hardware-watchdog.service ||
	fail 'independent rollback watchdog is not active'
! pgrep -x ModemManager >/dev/null || fail 'ModemManager must remain stopped'
! grep -q canoe-mtp-snd-card /proc/asound/cards 2>/dev/null ||
	fail 'AudioReach must remain stopped'
[ ! -e "$ready" ] || exit 0
[ ! -e "$foundation_ready" ] || fail 'stale Bluetooth foundation marker exists'
! systemctl --quiet is-active myron-reference-radio.service ||
	fail 'radio foundation must remain stopped'
[ ! -e /run/myron-wireless-ready ] || fail 'radio/Wi-Fi readiness marker must remain absent'
[ ! -d /sys/class/net/wlan0 ] || fail 'wlan0 must remain absent in the Bluetooth-only boot'
[ -d /sys/module/smem ] || fail 'built-in Qualcomm SMEM support is absent'

install -d -m0700 "$runtime"
load_exact_module "$smem_mailbox" smem_mailbox "$smem_mailbox_sha"
load_exact_module "$cnss_utils" cnss_utils "$cnss_utils_sha"
printf '%s\n' minimal-bluetooth-prerequisites >"$foundation_ready"
chmod 0600 "$foundation_ready"

trap restore_governors_on_exit 0
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
enter_powersave "$cpufreq_root"
wait_for_cooldown
"$bluetooth_stage" arm
"$bluetooth_stage" start
[ -e /sys/class/bluetooth/hci0 ] && [ -s /run/myron-bluetooth-ready ] ||
	fail 'Bluetooth controller did not remain ready'
! grep -q canoe-mtp-snd-card /proc/asound/cards 2>/dev/null ||
	fail 'AudioReach appeared during Bluetooth-only bring-up'
! systemctl --quiet is-active myron-reference-radio.service ||
	fail 'radio foundation appeared during Bluetooth-only bring-up'
[ ! -e /run/myron-wireless-ready ] ||
	fail 'radio/Wi-Fi readiness appeared during Bluetooth-only bring-up'
complete_governor_window

printf 'foundation=minimal\nradio=absent\nbluetooth=hci0-powered\naudio=absent\nmodem=absent\n' >"$ready"
chmod 0600 "$ready"
printf '%s\n' 'result=ready profile=bluetooth foundation=minimal radio=absent bluetooth=hci0 audio=absent modem=absent watchdog=armed'
