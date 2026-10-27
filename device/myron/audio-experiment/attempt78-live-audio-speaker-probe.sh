#!/bin/sh
set -eu

readonly audible_confirmation=PLAY-250MS-AT-MINUS-45DBFS
readonly muted_confirmation=OPEN-250MS-SPEAKER-GRAPH-WITH-AMPS-OFF
readonly silent_confirmation=OPEN-250MS-SPEAKER-GRAPH-WITH-DIGITAL-SILENCE
readonly mixer_card=0
readonly card=100
readonly pcm=100
readonly maximum_safe_temperature_mC=70000
readonly devicepp_profile="${AUDIO_SPEAKER_DEVICEPP_PROFILE:-mbdrc}"
readonly stream_profile="${AUDIO_SPEAKER_STREAM_PROFILE:-deep-buffer}"
readonly amplifier_mode="${AUDIO_SPEAKER_AMPLIFIER_MODE:-audible}"
readonly speaker_interface="${AUDIO_SPEAKER_INTERFACE:-TDM-LPAIF-RX-PRIMARY}"
wave=
play_log=
backend_backup=
backend_overlay=

fail() {
	printf 'ERROR: %s\n' "$*" >&2
	exit 1
}

get_value() {
	amixer -c "$mixer_card" cget "name=$1" | sed -n 's/^  : values=//p' | tail -n 1
}

set_value() {
	amixer -q -c "$mixer_card" cset "name=$1" "$2"
}

read_safety_temperature() {
	temperature_mC=
	temperature_type=pmih010x_lite_tz
	for temperature_file in /sys/class/thermal/thermal_zone*/temp; do
		[ -r "$temperature_file" ] || continue
		zone_type=$(cat "${temperature_file%/temp}/type" 2>/dev/null || echo unknown)
		[ "$zone_type" = "$temperature_type" ] || continue
		temperature=$(cat "$temperature_file" 2>/dev/null || echo 0)
		case "$temperature" in *[!0-9]*|'') fail 'invalid PMIC safety temperature' ;; esac
		temperature_mC=$temperature
		break
	done
	[ -n "$temperature_mC" ] || fail 'PMIC safety temperature is unavailable'
}

cleanup() {
	# Power down all TFA profiles even when AGM fails or this shell is interrupted.
	set_value 'TFA Profile' Powerdown 2>/dev/null || true
	if [ -n "$backend_backup" ] && [ -f "$backend_backup" ]; then
		cp -p -- "$backend_backup" /etc/backend_conf.xml || true
	fi
	rm -f "$wave" "$play_log" "$backend_overlay"
	[ -z "$backend_backup" ] || rm -f -- "$backend_backup"
}
trap cleanup EXIT INT TERM

[ "$(id -u)" = 0 ] || fail 'run this probe as root'
case "$amplifier_mode" in
	audible)
		[ "${CONFIRM_AUDIO_SPEAKER_PLAYBACK:-}" = "$audible_confirmation" ] ||
			fail 'set CONFIRM_AUDIO_SPEAKER_PLAYBACK=PLAY-250MS-AT-MINUS-45DBFS'
		;;
	powerdown)
		[ "${CONFIRM_AUDIO_SPEAKER_PLAYBACK:-}" = "$muted_confirmation" ] ||
			fail 'set CONFIRM_AUDIO_SPEAKER_PLAYBACK=OPEN-250MS-SPEAKER-GRAPH-WITH-AMPS-OFF'
		;;
	silent)
		[ "${CONFIRM_AUDIO_SPEAKER_PLAYBACK:-}" = "$silent_confirmation" ] ||
			fail 'set CONFIRM_AUDIO_SPEAKER_PLAYBACK=OPEN-250MS-SPEAKER-GRAPH-WITH-DIGITAL-SILENCE'
		;;
	*) fail 'AUDIO_SPEAKER_AMPLIFIER_MODE must be audible, silent, or powerdown' ;;
esac
case "$devicepp_profile" in
	mbdrc) devicepp_kv=0xAC000002 ;;
	default) devicepp_kv=0xAC000001 ;;
	*) fail 'AUDIO_SPEAKER_DEVICEPP_PROFILE must be mbdrc or default' ;;
esac
case "$stream_profile" in
	deep-buffer) stream_kv=0xA1000001 ;;
	low-latency) stream_kv=0xA100000E ;;
	*) fail 'AUDIO_SPEAKER_STREAM_PROFILE must be deep-buffer or low-latency' ;;
esac
case "$speaker_interface" in
	TDM-LPAIF-RX-PRIMARY|TDM-LPAIF-RX-PRIMARY-VIRT-0|TDM-LPAIF-RX-PRIMARY-VIRT-2) ;;
	*) fail 'AUDIO_SPEAKER_INTERFACE must be the stock TDM-LPAIF-RX-PRIMARY endpoint or a guarded VIRT diagnostic endpoint' ;;
esac
if [ ! -r /proc/asound/cards ] || ! grep -q 'canoe-mtp-snd-card' /proc/asound/cards; then
	fail 'Canoe ALSA card is not registered'
fi
[ -c /dev/snd/controlC0 ] || fail 'missing physical ALSA control device'
command -v agmplay >/dev/null || fail 'agmplay is not installed'
command -v python3 >/dev/null || fail 'python3 is required to generate the bounded waveform'
command -v timeout >/dev/null || fail 'timeout is required for the playback watchdog'
[ -r /etc/backend_conf.xml ] || fail 'missing /etc/backend_conf.xml'
[ -r /etc/acdbdata/acdb_cal.acdb ] || fail 'missing Canoe ACDB calibration'
pgrep -x agmplay >/dev/null 2>&1 && fail 'another AGM playback process is active'

read_safety_temperature
printf 'maximum_temperature_before_mC=%s\n' "$temperature_mC"
printf 'temperature_type=%s\n' "$temperature_type"
[ "$temperature_mC" -lt "$maximum_safe_temperature_mC" ] ||
	fail 'temperature safety limit reached before speaker probe'

printf 'previous_tfa_profile=%s\n' "$(get_value 'TFA Profile')"
printf 'previous_tfa_stop=%s\n' "$(get_value 'TFA Stop')"
printf 'previous_speaker_switch=%s\n' "$(get_value 'tfa98xx_spksw_gpio_switch')"

# Canoe has three TFA amplifiers, including the subwoofer.  Xiaomi's stock PAL
# and backend_conf.xml both select the physical TDM-LPAIF-RX-PRIMARY endpoint,
# already configured as three-channel, 32-bit TDM.  Do not replace that stock
# entry.  Only synthesize group data when explicitly diagnosing a VIRT route.
if [ "$speaker_interface" != TDM-LPAIF-RX-PRIMARY ]; then
	backend_backup=$(mktemp /tmp/attempt78-backend-conf.XXXXXX)
	backend_overlay=$(mktemp /tmp/attempt78-backend-overlay.XXXXXX)
	cp -p -- /etc/backend_conf.xml "$backend_backup"
	awk '
	/<config>/ && !added {
		print
		print "    <group_device name=\"TDM-LPAIF-RX-PRIMARY\" rate=\"48000\" ch=\"3\" bits=\"32\" slot_mask=\"7\"/>"
		print "    <device name=\"TDM-LPAIF-RX-PRIMARY-VIRT-0\" rate=\"48000\" ch=\"2\" bits=\"24\" format=\"PCM_FORMAT_S24_LE\" />"
		print "    <device name=\"TDM-LPAIF-RX-PRIMARY-VIRT-2\" rate=\"48000\" ch=\"2\" bits=\"24\" format=\"PCM_FORMAT_S24_LE\" />"
		added=1
		next
	}
	{ print }
	END { if (!added) exit 1 }
' /etc/backend_conf.xml > "$backend_overlay" || fail 'could not create temporary speaker backend configuration'
	install -m 0644 "$backend_overlay" /etc/backend_conf.xml
fi

wave=$(mktemp /tmp/attempt78-speaker-wave.XXXXXX)
play_log=$(mktemp /tmp/attempt78-speaker-log.XXXXXX)
python3 - "$wave" "$amplifier_mode" <<'PY'
import math
import struct
import sys
import wave

rate = 48000
frames = 12000
if sys.argv[2] == "silent":
    amplitude = 0
else:
    amplitude = 47186
frequency = 440.0
fade_frames = 960

with wave.open(sys.argv[1], "wb") as output:
    output.setnchannels(2)
    output.setsampwidth(4)
    output.setframerate(rate)
    payload = bytearray()
    for frame in range(frames):
        envelope = min(1.0, frame / fade_frames, (frames - 1 - frame) / fade_frames)
        sample = round(amplitude * envelope * math.sin(2.0 * math.pi * frequency * frame / rate))
        payload.extend(struct.pack("<ii", sample, sample))
    output.writeframes(payload)
PY

[ "$(wc -c < "$wave" | tr -d ' ')" -eq 96044 ] || fail 'generated waveform has an unexpected size'
printf '%s\n' 'duration_ms=250'
if [ "$amplifier_mode" = silent ]; then
	printf '%s\n' 'peak_input_sample=0/8388607'
	printf '%s\n' 'input_level=digital-silence'
else
	printf '%s\n' 'peak_input_sample=47186/8388607'
	printf '%s\n' 'input_level_dbfs=-45.0'
fi
printf 'speaker_route=%s input_container_bits=32 input_valid_bits=24 endpoint_bits=24 group_bits=32 group_channels=3 slot_mask=7 stereo-input\n' "$speaker_interface"
printf 'speaker_devicepp_profile=%s kv=%s\n' "$devicepp_profile" "$devicepp_kv"
printf 'speaker_stream_profile=%s kv=%s\n' "$stream_profile" "$stream_kv"
printf 'speaker_amplifier_mode=%s\n' "$amplifier_mode"

# Start from the container's standby profile, open exactly one quiet stream,
# and let the EXIT trap force Powerdown regardless of the result.
set_value 'TFA Profile' Powerdown
sleep 1
case "$amplifier_mode" in
	silent|audible)
	set_value 'TFA Profile' stereo
		;;
esac
dmesg_lines_before=$(dmesg | wc -l | tr -d ' ')
if ! timeout -s TERM 5 agmplay "$wave" \
	-D "$card" \
	-d "$pcm" \
	-c 2 \
	-r 48000 \
	-b 24 \
	-is_24_LE 1 \
	-num_intf 1 \
	-i "$speaker_interface" \
	-skv "$stream_kv" \
	-dkv 0xA2000001 \
	-dppkv "$devicepp_kv" \
	-ikv 1 >"$play_log" 2>&1; then
	cat "$play_log" >&2
	fail 'bounded AudioReach speaker playback failed or exceeded five seconds'
fi
cat "$play_log"
grep -Fq 'Playing sample: 2 ch, 48000 hz, 32 bit' "$play_log" ||
	fail 'AGM did not reach the playback state'
if grep -Eq 'Failed|Unable|Invalid input|start error' "$play_log"; then
	fail 'AGM reported a speaker graph error'
fi

set_value 'TFA Profile' Powerdown
[ "$(get_value 'TFA Profile')" = 6 ] || fail 'TFA amplifiers did not return to Powerdown'
printf '%s\n' 'post_test_tfa_profile=Powerdown'
printf '%s\n' '=== new relevant kernel messages ==='
dmesg | tail -n "+$((dmesg_lines_before + 1))" |
	grep -Ei 'audio|agm|gpr|tfa|speaker|snd|adsp|error|fail' || true

read_safety_temperature
printf 'maximum_temperature_after_mC=%s\n' "$temperature_mC"
printf 'temperature_type_after=%s\n' "$temperature_type"
[ "$temperature_mC" -lt "$maximum_safe_temperature_mC" ] ||
	fail 'temperature safety limit reached after speaker probe'
if [ "$amplifier_mode" = audible ]; then
	printf '%s\n' 'PASS: one 250 ms stereo speaker probe completed at approximately -45 dBFS; TFA returned to Powerdown'
elif [ "$amplifier_mode" = silent ]; then
	printf '%s\n' 'PASS: speaker playback graph ran for 250 ms with the stock TFA stereo route and digital silence; TFA returned to Powerdown'
else
	printf '%s\n' 'PASS: speaker playback graph ran for 250 ms while TFA remained in Powerdown'
fi
