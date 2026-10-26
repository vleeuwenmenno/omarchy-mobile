#!/bin/sh
# SPDX-License-Identifier: MIT
# tile-state.sh: one read-only pass over the backends of the quick-settings
# tiles that have no Quickshell service, printed as key=value lines for
# TilesModel.parseProbe. "none" means the tile has no backend on this device.
# Nothing here writes; each probe is bounded by timeout so a hung daemon
# cannot hold the sheet's refresh.
#
#   airplane      on when every Wi-Fi, Bluetooth and WWAN rfkill switch is
#                 soft-blocked (none without such a switch)
#   hotspot       on while NetworkManager's "Hotspot" connection is up
#   powerprofile  power-profiles-daemon's active profile
#   theme_mode    light or dark, as Omarchy resolves the current theme
#   theme_name    the current theme's directory name
#   nightlight    on while hyprsunset runs warmer than identity
#   stayawake     on while Omarchy's stay-awake indicator exists
#   record        on while omamobile-screenrecord (wf-recorder) records
#   data          on while omamobile-sit-data.service is active; none
#                 without omamobile-sitd running. Where myron-mobile-data
#                 exists (the Myron main boot) that helper answers instead and
#                 the Pixel SIT path is never consulted
#   data_status   the operator and technology, when registered (Myron: the
#                 honest state in words)
#   data_enable   Myron only: 1 when a tap may start data
#   data_busy     Myron only: 1 when a tap does nothing now

t() { timeout 3 "$@" 2>/dev/null; }
have() { command -v "$1" >/dev/null 2>&1; }

# airplane. Myron cannot safely turn its modem radio off and back on in one
# boot, so a partial Wi-Fi/Bluetooth-only action would lie: publish unavailable.
if have myron-mobile-data; then
  echo "airplane=none"
elif have rfkill; then
  t rfkill -rn -o TYPE,SOFT | awk '
    $1 == "wlan" || $1 == "bluetooth" || $1 == "wwan" { n++; if ($2 == "blocked") b++ }
    END { print "airplane=" (n == 0 ? "none" : (b == n ? "on" : "off")) }'
else
  echo "airplane=none"
fi

# hotspot
if have nmcli; then
  if t nmcli -t -f NAME connection show --active | grep -cx Hotspot >/dev/null; then
    echo "hotspot=on"
  else
    echo "hotspot=off"
  fi
else
  echo "hotspot=none"
fi

# powerprofile
profile=$(have powerprofilesctl && t powerprofilesctl get)
echo "powerprofile=${profile:-none}"

# theme
if have omarchy-theme-color; then
  echo "theme_mode=$(t omarchy-theme-color mode)"
fi
name_file="$HOME/.local/state/omarchy/current/theme.name"
[ -r "$name_file" ] && echo "theme_name=$(head -n1 "$name_file")"

# nightlight
if have hyprsunset && have omarchy-toggle-nightlight; then
  case $(t omarchy-toggle-nightlight --status) in
    *'"enabled":true'*) echo "nightlight=on" ;;
    *) echo "nightlight=off" ;;
  esac
else
  echo "nightlight=none"
fi

# stayawake
if [ -e "$HOME/.local/state/omarchy/indicators/stay-awake" ]; then
  echo "stayawake=on"
else
  echo "stayawake=off"
fi

# record
if have omamobile-screenrecord && have wf-recorder; then
  echo "record=$(t omamobile-screenrecord status || echo off)"
else
  echo "record=none"
fi

# data: the daemon's public state is world-readable; the bearer service's
# state is what "data on|off" switches.
state=/run/omamobile-sit/state.json
if have myron-mobile-data; then
  # The Myron backend alone: when it cannot answer the tile says so, and a
  # missing or stale answer is never read as the Pixel's SIT state.
  out=$(timeout 6 myron-mobile-data state 2>/dev/null) || out=
  if [ -n "$out" ]; then
    printf '%s\n' "$out"
  else
    printf 'data=off\ndata_status=Status unavailable\ndata_enable=0\ndata_busy=1\n'
  fi
elif have omamobile-sit && [ -r "$state" ] && have python3; then
  if systemctl is-active --quiet omamobile-sit-data.service 2>/dev/null; then echo "data=on"; else echo "data=off"; fi
  python3 -I -c '
import json, sys
try:
    m = json.load(open(sys.argv[1])).get("modem") or {}
except (OSError, ValueError):
    sys.exit(0)
words = [str(m.get(k)) for k in ("operator", "tech") if m.get(k)]
print("data_status=" + " ".join(words))
' "$state"
else
  echo "data=none"
fi

# Optional device bridge for a built-in microphone that PipeWire cannot open
# through its generic ALSA profile. The command is a privacy switch: the raw
# capture graph exists only while it reports on.
if have omamobile-microphone; then
  echo "mic_bridge=$(t omamobile-microphone status || echo off)"
else
  echo "mic_bridge=none"
fi
