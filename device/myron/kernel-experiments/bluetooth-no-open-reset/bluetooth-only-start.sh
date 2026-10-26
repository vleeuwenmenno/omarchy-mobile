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
