# SPDX-License-Identifier: MIT
# Mocked radio-path tools for the Myron cellular stage tests. Each tool is a
# bash function reading scenario variables (m_*, work, ...). tests/myron-cellular-stage
# sources this file for in-process runs; for /bin/sh runs it also writes tiny
# executables that source the same scenario and call the same functions.
# shellcheck shell=bash disable=SC2154

mock_time() { echo "$(( $(cut -d. -f1 "$uptime_file") + $1 )).00 0.00" >"$uptime_file"; }

id() { printf '%s\n' "$uid"; }
uname() { printf '%s\n' "$kernel"; }
sleep() { [[ $sleep_advance == 0 ]] || mock_time "${1%.*}"; }
pgrep() { return "$conflict"; }
systemctl() {
  if [[ $1 == --quiet && $2 == is-active ]]; then [[ $active_units == *" $3 "* ]]; return; fi
  if [[ $1 == show ]]; then printf '%s\n' "$wd_enter"; return 0; fi
  echo "systemctl $*" >>"$calls"
  return 0
}
timeout() {
  while [[ $1 == -k ]]; do shift 2; done
  shift
  if [[ -d ${mutation_marker:-/nonexistent} && ${timeout_advance_after_marker:-0} -gt 0 ]]; then mock_time "$timeout_advance_after_marker"; fi
  if [[ -e ${work:-/nonexistent}/activated && ${timeout_advance_after_activation:-0} -gt 0 ]]; then mock_time "$timeout_advance_after_activation"; fi
  if [[ -e ${work:-/nonexistent}/activated && ${heat_after_activation:-0} == 1 ]]; then
    echo 99000 >"$thermal_root/thermal_zone0/temp"
  fi
  "$@"
}
stat() { printf '%s\n' "$stat_reply"; }
leak() { [[ $noisy == 1 ]] && printf 'raw %s %s %s %s\n' "$secret_imei" "$secret_iccid" "$secret_ip" "$secret_apn" >&2 || true; }
mmcli() {
  if [[ $1 == -L ]]; then
    leak
    for ((i = 0; i < modems; i++)); do echo "/org/freedesktop/ModemManager1/Modem/$i [Qualcomm] myron"; done
  elif [[ $1 == -m && $3 == -K ]]; then
    leak
    cat <<EOT
modem.generic.state                         : $state
modem.generic.power-state                   : $power
modem.generic.unlock-required               : $unlock
modem.generic.sim                           : /org/freedesktop/ModemManager1/SIM/0
modem.generic.bearers.length                : $bearers
modem.generic.bearers                       : ${bearers_scalar:-}
modem.generic.access-technologies.length    : $access_len
modem.generic.access-technologies.value[1]  : $access1
modem.generic.access-technologies.value[2]  : $access2
modem.generic.equipment-identifier          : $secret_imei
modem.generic.own-numbers.length            : 1
modem.generic.own-numbers.value[1]          : $secret_number
modem.3gpp.registration-state               : $reg
modem.3gpp.packet-service-state             : $packet
modem.3gpp.imei                             : $secret_imei
sim.properties.iccid                        : $secret_iccid
EOT
  else
    echo "mmcli $*" >>"$calls"
  fi
}
nmcli() {
  case "$*" in
  'general status') return "$nm_ok" ;;
  '-t -f DEVICE,TYPE,STATE device status')
    if [[ -e $work/activated ]]; then echo "wlan0:wifi:$m_wifi_after"; else echo "wlan0:wifi:$m_wifi"; fi
    echo "usb0:ethernet:unmanaged"
    for ((i = 0; i < gsm_devices; i++)); do
      if [[ -e $work/managed ]]; then echo "ttyMODEM$i:gsm:$managed_state_after"; else echo "ttyMODEM$i:gsm:$gsm_boot"; fi
    done
    return 0 ;;
  '-t -f UUID,NAME,TYPE,STATE connection show')
    echo 'aaaaaaaa-0000-4000-8000-000000000001:home-wifi:802-11-wireless:activated'
    if [[ -e $work/activated ]]; then echo "$secret_uuid:myron-cellular:gsm:activated"
    elif [[ $m_profile_exists == 1 || -e $work/profile-created ]]; then echo "$secret_uuid:myron-cellular:gsm:"; fi
    for ((i = 0; i < m_active_gsm; i++)); do echo "bbbbbbbb-0000-4000-8000-00000000000$i:other$i:gsm:$m_busy_state"; done
    [[ ! -e $work/activated ]] || for ((i = 0; i < m_active_after; i++)); do echo "cccccccc-0000-4000-8000-00000000000$i:late$i:gsm:activated"; done
    [[ -z $m_rows ]] || printf '%b\n' "$m_rows"
    return 0 ;;
  '-t -f UUID,TYPE,AUTOCONNECT connection show')
    echo 'aaaaaaaa-0000-4000-8000-000000000001:802-11-wireless:yes'
    [[ $m_profile_exists == 0 && ! -e $work/profile-created ]] || echo "$secret_uuid:gsm:$m_own_auto"
    [[ -z $m_auto ]] || printf '%b\n' "$m_auto"
    [[ ! -e $work/late-autoconnect ]] || echo "eeeeeeee-0000-4000-8000-000000000001:gsm:yes"
    return 0 ;;
  "-g connection.autoconnect connection show uuid $secret_uuid") echo "$autoconnect_reply"; return ;;
  "-g gsm.home-only connection show uuid $secret_uuid") echo "$m_homeonly"; return ;;
  "-g gsm.initial-eps-bearer-configure connection show uuid $secret_uuid") echo "$m_initial_eps"; return ;;
  "-g ipv4.routes connection show uuid $secret_uuid") echo "$m_profile_routes"; return ;;
  "-g ipv4.addresses connection show uuid $secret_uuid") echo "$m_profile_addresses"; return ;;
  "-g ipv4.gateway connection show uuid $secret_uuid") echo "$m_profile_gateway"; return ;;
  "-g connection.secondaries connection show uuid $secret_uuid") echo "$m_secondaries"; return ;;
  "-g ipv4.route-metric connection show uuid $secret_uuid") echo "$m_profile_metric"; return ;;
  "-g ipv4.routing-rules connection show uuid $secret_uuid") echo "$m_profile_rules"; return ;;
  "-g ipv4.route-table connection show uuid $secret_uuid") echo "$m_profile_table"; return ;;
  "-g ipv4.never-default connection show uuid $secret_uuid") echo "$m_profile_never"; return ;;
  "-g connection.id connection show uuid $secret_uuid") echo "$m_id_reply"; return ;;
  '-g connection.uuid connection show id myron-cellular') echo "$m_uuid_by_name"; return ;;
  "-g GENERAL.DEVICES connection show uuid $secret_uuid") echo "$m_bound"; return ;;
  '-g GENERAL.IP-IFACE device show ttyMODEM0') echo rmnet_data0; return ;;
  '-g GENERAL.AUTOCONNECT device show ttyMODEM0')
    if [[ -e $work/device-autoconnect-off ]]; then echo no; else echo "$m_device_auto"; fi
    return ;;
  '-t -f IP4.DNS device show ttyMODEM0')
    for ((i = 0; i < dns_lines; i++)); do echo "IP4.DNS[$((i + 1))]:$secret_dns"; done
    return 0 ;;
  esac
  local marker=no
  [[ -d $mutation_marker ]] && marker=yes
  echo "nmcli marker=$marker $*" >>"$calls"
  leak
  case "$*" in
  'connection add '*) : >"$work/profile-created" ;;
  'connection modify '*) : >"$work/profile-modified" ;;
  'device set ttyMODEM0 autoconnect no')
    [[ $device_autoconnect_set_ok == 1 ]] || return 1
    : >"$work/device-autoconnect-off" ;;
  'device set ttyMODEM0 managed yes')
    : >"$work/managed"
    # What NetworkManager would do to a managed device with an autoconnect profile.
    if [[ ! -e $work/device-autoconnect-off && ( $autoactivate == 1 || -n $m_auto || $m_own_auto == yes ) ]]; then : >"$work/auto-activated"; fi ;;
  "connection up uuid $secret_uuid ifname ttyMODEM0")
    [[ $up_delay == 0 ]] || mock_time "$up_delay"
    [[ $up_activates == 0 ]] || : >"$work/activated"
    return "$up_rc" ;;
  esac
  return 0
}
mock_ip_addr() { # iface
  case $1 in
  rmnet_data0) for ((i = 0; i < addr_lines; i++)); do echo "3: rmnet_data0    inet $secret_ip/30 scope global rmnet_data0"; done ;;
  usb0) [[ $m_usb == 1 ]] || return 0
    [[ -e $work/activated && $m_usb_addr_after == lost ]] && return 0
    [[ -e $work/activated && $m_usb_addr_after == other ]] && { echo "5: usb0    inet 172.16.43.1/24 scope global usb0"; return 0; }
    echo "5: usb0    inet 172.16.42.1/24 scope global usb0" ;;
  wlan0) [[ -e $work/activated && $m_wifi_addr_after == lost ]] && return 0
    if [[ -e $work/activated && $m_wifi_addr_after == other ]]; then echo "4: wlan0    inet 192.168.77.9/24 brd 192.168.77.255 scope global wlan0"; return 0; fi
    echo "4: wlan0    inet $m_wifi_addr/24 brd 192.168.50.255 scope global wlan0" ;;
  esac
}
ip() {
  case "$*" in
  '-4 -o addr show dev rmnet_data0 scope global') mock_ip_addr rmnet_data0 ;;
  '-4 -o addr show dev usb0 scope global') mock_ip_addr usb0 ;;
  '-4 -o addr show dev wlan0 scope global') mock_ip_addr wlan0 ;;
  '-4 route show table main dev usb0')
    [[ $m_usb_route_lost == 1 && -e $work/activated ]] || echo "172.16.42.0/24 proto kernel scope link src 172.16.42.1" ;;
  '-4 route show table main dev wlan0')
    echo "default via 192.168.1.1 proto dhcp src $m_wifi_addr metric 600"
    echo "192.168.50.0/24 proto kernel scope link src $m_wifi_addr metric 600" ;;
  '-4 route show table all default dev rmnet_data0')
    for ((i = 0; i < m_default_lines; i++)); do
      if [[ $m_route_table == main ]]; then echo "default via 10.0.0.1 dev rmnet_data0 metric 700"
      else echo "default via 10.0.0.1 dev rmnet_data0 table $m_route_table metric 700"; fi
    done ;;
  '-4 route show table main default') [[ -z $m_main_default ]] || printf '%b\n' "$m_main_default" ;;
  '-4 -o route get 172.16.42.2 from 172.16.42.1')
    echo usb >>"$work/peer-route-calls"
    if [[ -e $work/activated ]]; then
      echo "172.16.42.2 from 172.16.42.1 dev $m_peer_dev_after src $m_peer_src_after ${m_peer_via_after:+via $m_peer_via_after }${m_peer_table_after:+table $m_peer_table_after }uid 0"
    else
      echo "172.16.42.2 from 172.16.42.1 dev $m_peer_dev src $m_peer_src ${m_peer_via:+via $m_peer_via }${m_peer_table:+table $m_peer_table }uid 0"
    fi ;;
  "-4 -o route get 192.168.50.9 from $secret_wifi_ip")
    echo wifi >>"$work/peer-route-calls"
    if [[ -e $work/activated ]]; then
      echo "192.168.50.9 from $secret_wifi_ip dev $m_wifi_peer_dev_after src $m_wifi_peer_src_after ${m_wifi_peer_via_after:+via $m_wifi_peer_via_after }${m_wifi_peer_table_after:+table $m_wifi_peer_table_after }uid 0"
    else
      echo "192.168.50.9 from $secret_wifi_ip dev $m_wifi_peer_dev src $m_wifi_peer_src ${m_wifi_peer_via:+via $m_wifi_peer_via }${m_wifi_peer_table:+table $m_wifi_peer_table }uid 0"
    fi ;;
  '-4 rule show')
    printf '0:\tfrom all lookup local\n'
    [[ -z $m_pre_rule ]] || printf '%b\n' "$m_pre_rule"
    if [[ -e $work/activated ]]; then [[ -z $rule_line ]] || printf '%s\n' "$rule_line"; [[ -z $m_post_rule ]] || printf '%b\n' "$m_post_rule"; fi
    printf '32766:\tfrom all lookup main\n' ;;
  "-4 route get $secret_dns oif rmnet_data0") echo "$secret_dns dev $route_get_dev table 1430 src $secret_ip" ;;
  *) echo "ip $*" >>"$calls" ;;
  esac
}
resolvectl() {
  case "$*" in
  'dns rmnet_data0') [[ -z $m_link_dns_data ]] || echo "Link 7 (rmnet_data0): $m_link_dns_data" ;;
  'dns ttyMODEM0') [[ -z $m_link_dns_control ]] || echo "Link 8 (ttyMODEM0): $m_link_dns_control" ;;
  'query '*)
    echo "resolvectl $*" >>"$calls"
    # A link-scoped query uses only that link's servers; Wi-Fi's DNS is never consulted for it.
    if [[ $* == *' -i rmnet_data0 '* ]]; then
      [[ $cell_dns_ok == 1 ]] || return 1
      printf 'connectivitycheck.gstatic.com: %s    -- link: rmnet_data0\n' "$cell_dns_ip"
    else
      [[ $wifi_dns_ok == 1 ]] || return 1
      printf 'connectivitycheck.gstatic.com: 203.0.113.99    -- link: wlan0\n'
    fi ;;
  *) return 1 ;;
  esac
}
ss() {
  case "$*" in
  '-H -ltn sport = :22')
    if [[ -e $work/activated ]]; then printf '%b' "$m_listeners_after"; else printf '%b' "$m_listeners"; fi ;;
  '-H -tn state established sport = :22')
    if [[ -e $work/activated ]]; then printf '%b' "$m_sessions_after"; else printf '%b' "$m_sessions"; fi ;;
  *) return 1 ;;
  esac
}
curl() {
  echo "curl $*" >>"$calls"
  leak
  # A curl that loads a hostile config because -q was not first prints garbage.
  if [[ $1 != -q ]]; then printf '999 %s' "$secret_ip"; return 0; fi
  local dir=$net_root/rmnet_data0/statistics
  [[ -z ${m_usb_ifindex_after:-} ]] || echo "$m_usb_ifindex_after" >"$net_root/usb0/ifindex"
  case "$m_counter_move" in
  both|tx) echo $(( $(cat "$dir/tx_packets") + 5 )) >"$dir/tx_packets" ;;
  esac
  case "$m_counter_move" in
  both|rx) echo $(( $(cat "$dir/rx_packets") + 5 )) >"$dir/rx_packets" ;;
  esac
  printf '%s %s' "$curl_code" "$curl_local"
}
