#!/bin/sh
# SPDX-License-Identifier: MIT
# Exact one-shot transaction for Bluetooth discovery qualification only.
set -eu
umask 077

runtime=/run/omamobile-myron
ready=/run/myron-bluetooth-only-ready
profile=/etc/omamobile/myron-test-profile
foundation_ready=/run/myron-bluetooth-foundation-ready
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

wait_for_cooldown
/usr/local/sbin/myron-bluetooth-stage arm
/usr/local/sbin/myron-bluetooth-stage start
[ -e /sys/class/bluetooth/hci0 ] && [ -s /run/myron-bluetooth-ready ] ||
	fail 'Bluetooth controller did not remain ready'
! grep -q canoe-mtp-snd-card /proc/asound/cards 2>/dev/null ||
	fail 'AudioReach appeared during Bluetooth-only bring-up'
! systemctl --quiet is-active myron-reference-radio.service ||
	fail 'radio foundation appeared during Bluetooth-only bring-up'
[ ! -e /run/myron-wireless-ready ] ||
	fail 'radio/Wi-Fi readiness appeared during Bluetooth-only bring-up'

printf 'foundation=minimal\nradio=absent\nbluetooth=hci0-powered\naudio=absent\nmodem=absent\n' >"$ready"
chmod 0600 "$ready"
printf '%s\n' 'result=ready profile=bluetooth foundation=minimal radio=absent bluetooth=hci0 audio=absent modem=absent watchdog=armed'
