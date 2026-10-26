#!/bin/bash
# SPDX-License-Identifier: MIT
# Tests for the quick-settings tile scripts (tile-state.sh, tile-action.sh)
# against fake commands. PATH holds only the fakes and a few basic tools, so
# no real rfkill, nmcli or theme switch can run on the build machine.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
dir=plugins/omamobile.quicksettings
fail() { printf 'not ok - %s\n' "$1" >&2; exit 1; }
pass() { printf 'ok - %s\n' "$1"; }

tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
fake=$tmp/bin; basic=$tmp/basic; log=$tmp/log
mkdir -p "$fake" "$basic" "$tmp/home/.local/state/omarchy/current" "$tmp/state"
for tool in sh awk sort cat head grep mkdir rm timeout printf; do
  ln -s "$(command -v "$tool")" "$basic/$tool"
done
: >"$log"

stub() { # name body
  printf '#!/bin/sh\n%s\n' "$2" >"$fake/$1"; chmod +x "$fake/$1"
}
# rfkill: TYPE SOFT lines from a file; block/unblock rewrite it.
stub rfkill '
f='"$tmp"'/state/rfkill
case $1 in
  -rn) cat "$f" ;;
  block|unblock) echo "rfkill $*" >>'"$log"'
    new=$([ "$1" = block ] && echo blocked || echo unblocked)
    awk -v t="$2" -v s="$new" '"'"'$1 == t { $2 = s } { print }'"'"' "$f" >"$f.new" && cat "$f.new" >"$f" ;;
esac'
stub nmcli 'echo "nmcli $*" >>'"$log"'; [ "$1" = -t ] && cat '"$tmp"'/state/active 2>/dev/null; exit 0'
stub powerprofilesctl 'echo balanced'
stub omarchy-theme-color 'cat '"$tmp"'/state/mode'
stub omarchy-theme-set 'echo "theme-set $*" >>'"$log"
stub omarchy-toggle-nightlight '[ "$1" = --status ] && { cat '"$tmp"'/state/night; exit 0; }; echo nightlight-toggle >>'"$log"
stub hyprsunset 'exit 0'
stub omarchy-toggle-idle 'echo "idle $*" >>'"$log"
stub omarchy-powerprofiles-set 'echo "powerprofiles $*" >>'"$log"
stub omamobile-sit 'echo "sit $*" >>'"$log"
stub pgrep 'exit 1'

run() { env -i HOME="$tmp/home" PATH="$fake:$basic" sh "$@"; }

printf 'wlan unblocked\nbluetooth blocked\nnfc unblocked\n' >"$tmp/state/rfkill"
echo dark >"$tmp/state/mode"
echo tokyo-night >"$tmp/home/.local/state/omarchy/current/theme.name"
echo '{"enabled":false,"temperature":6500}' >"$tmp/state/night"

out=$(run "$dir/tile-state.sh")
for line in airplane=off hotspot=off powerprofile=balanced theme_mode=dark theme_name=tokyo-night \
            nightlight=off stayawake=off record=none data=none mic_bridge=none; do
  grep -cx "$line" <<<"$out" >/dev/null || fail "tile-state.sh prints $line (got: $(tr '\n' ' ' <<<"$out"))"
done
pass "tile-state.sh reads every probed tile"

# Airplane on blocks the radios, remembers which were on, leaves NFC alone;
# off unblocks only those.
run "$dir/tile-action.sh" airplane on
grep -cx "wlan blocked" "$tmp/state/rfkill" >/dev/null || fail "airplane on blocks Wi-Fi"
grep -cx "nfc unblocked" "$tmp/state/rfkill" >/dev/null || fail "airplane mode leaves NFC alone"
grep -cx "airplane=on" <<<"$(run "$dir/tile-state.sh")" >/dev/null || fail "tile-state.sh sees airplane mode on"
run "$dir/tile-action.sh" airplane off
grep -cx "wlan unblocked" "$tmp/state/rfkill" >/dev/null || fail "airplane off unblocks Wi-Fi"
grep -cx "bluetooth blocked" "$tmp/state/rfkill" >/dev/null || fail "airplane off keeps Bluetooth off when it was off before"
pass "airplane mode restores the radios it found on"

# Dark theme: the theme being left is remembered for its mode.
run "$dir/tile-action.sh" dark-theme off
grep -cx "theme-set catppuccin-latte" "$log" >/dev/null || fail "light theme defaults to catppuccin-latte"
[[ $(cat "$tmp/home/.local/state/omamobile/theme-dark") == tokyo-night ]] || fail "the dark theme is remembered"
echo light >"$tmp/state/mode"; echo flexoki-light >"$tmp/home/.local/state/omarchy/current/theme.name"
run "$dir/tile-action.sh" dark-theme on
grep -cx "theme-set tokyo-night" "$log" >/dev/null || fail "dark theme returns to the remembered theme"
[[ $(cat "$tmp/home/.local/state/omamobile/theme-light") == flexoki-light ]] || fail "the light theme is remembered"
pass "dark theme swaps between the remembered themes"

# Night light toggles only when the state differs.
run "$dir/tile-action.sh" night-light off
[[ $(grep -c nightlight-toggle "$log") == 0 ]] || fail "night light off when already off does nothing"
run "$dir/tile-action.sh" night-light on
[[ $(grep -c nightlight-toggle "$log") == 1 ]] || fail "night light on toggles once"
pass "night light follows the asked direction"

run "$dir/tile-action.sh" battery-saver on
run "$dir/tile-action.sh" stay-awake off
run "$dir/tile-action.sh" mobile-data on
run "$dir/tile-action.sh" hotspot on
for line in "powerprofiles autodetect power-saver" "idle allow-idle" "sit data on" \
            "nmcli device wifi hotspot con-name Hotspot"; do
  grep -cxF "$line" "$log" >/dev/null || fail "tile-action.sh runs: $line"
done
pass "tile-action.sh drives battery saver, stay awake, mobile data and hotspot"

# Myron never falls through to Pixel SIT. Mobile data may only ask its helper
# for the supported start, while airplane mode is unavailable because a
# partial Wi-Fi/Bluetooth-only action would leave cellular transmitting.
stub myron-mobile-data '
[ ! -e '"$tmp"'/state/myron-helper-fail ] || exit 1
case $1 in
  state) printf "data=off\ndata_status=Off ·5G\ndata_enable=1\ndata_busy=0\n" ;;
  on) echo "myron-data on" >>'"$log"' ;;
  off) echo "myron-data off-refused" >>'"$log"'; exit 1 ;;
  *) exit 2 ;;
esac'
out=$(run "$dir/tile-state.sh")
grep -cx 'airplane=none' <<<"$out" >/dev/null || fail "Myron airplane mode is not unavailable"
for line in data=off 'data_status=Off ·5G' data_enable=1 data_busy=0; do
  grep -cxF "$line" <<<"$out" >/dev/null || fail "Myron tile state lacks: $line"
done
touch "$tmp/state/myron-helper-fail"
out=$(run "$dir/tile-state.sh")
for line in data=none 'data_status=Status unavailable' data_enable=0 data_busy=1; do
  grep -cxF "$line" <<<"$out" >/dev/null || fail "failed Myron helper is not honestly unavailable: $line"
done
rm -f "$tmp/state/myron-helper-fail"
: >"$log"
run "$dir/tile-action.sh" mobile-data on
grep -cxF 'myron-data on' "$log" >/dev/null || fail "Myron mobile-data start did not use its helper"
! grep -q '^sit ' "$log" || fail "Myron mobile data fell through to Pixel SIT"
before=$(cat "$tmp/state/rfkill")
if run "$dir/tile-action.sh" airplane on 2>/dev/null; then fail "Myron airplane mode was accepted"; fi
[[ $(cat "$tmp/state/rfkill") == "$before" ]] || fail "Myron airplane refusal changed rfkill state"
if run "$dir/tile-action.sh" mobile-data off 2>/dev/null; then fail "Myron mobile data off was accepted"; fi
grep -cxF 'myron-data off-refused' "$log" >/dev/null || fail "Myron mobile-data off did not reach the refusing helper"
! grep -q '^sit ' "$log" || fail "Myron refusal fell through to Pixel SIT"
pass "Myron tile uses only its one-shot helper, reports helper failure unavailable, and refuses airplane/off"

stub omamobile-microphone 'echo "microphone $*" >>'"$log"'; if [ "$1" = status ]; then echo off; fi; exit 0'
grep -cx 'mic_bridge=off' <<<"$(run "$dir/tile-state.sh")" >/dev/null ||
  fail "tile-state.sh reads the optional microphone bridge"
run "$dir/tile-action.sh" mic on
grep -cxF 'microphone on' "$log" >/dev/null || fail "microphone tile starts its privacy-gated bridge"
pass "microphone tile controls the optional device bridge"

if run "$dir/tile-action.sh" wifi on 2>/dev/null; then fail "unknown tiles are refused"; fi
if run "$dir/tile-action.sh" airplane maybe 2>/dev/null; then fail "only on and off are accepted"; fi
pass "tile-action.sh refuses unknown tiles and states"
