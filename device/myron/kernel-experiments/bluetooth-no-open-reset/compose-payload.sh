#!/bin/bash
# SPDX-License-Identifier: MIT
# Add the exact no-opening-reset kernel module set to a private coexistence
# hardware-test image. This writes only OUT and never contacts a phone.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../../.."
ROOT=$PWD
source tools/lib/alarm.sh

base= dist= firmware= out=
die() { printf 'error: %s\n' "$*" >&2; exit 1; }
usage() {
  printf '%s\n' 'Usage: compose-payload.sh --base-image FILE --dist DIR --firmware-dir DIR --out FILE'
}
while (($#)); do
  case $1 in
    --base-image) base=${2:?}; shift 2 ;;
    --dist) dist=${2:?}; shift 2 ;;
    --firmware-dir) firmware=${2:?}; shift 2 ;;
    --out) out=${2:?}; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done
for value in base dist firmware out; do [[ -n ${!value} ]] || die "--${value//_/-} is required"; done
base=$(realpath "$base")
dist=$(realpath "$dist")
firmware=$(realpath "$firmware")
out=$(realpath -m "$out")
[[ -f $base && ! -L $base ]] || die 'base image is missing, linked or not regular'
[[ -d $dist && ! -L $dist ]] || die 'kernel dist is missing, linked or not a directory'
[[ -d $firmware && ! -L $firmware ]] || die 'firmware directory is missing, linked or not a directory'
[[ ! -e $out && ! -L $out ]] || die "refusing to replace $out"
[[ -d $(dirname -- "$out") && ! -L $(dirname -- "$out") ]] || die 'output parent is unsafe'

readonly base_sha=744cfdb0f3e16657ddf369c4c6130689c5a25a52ce612dc8dff33fafb438ff3d
readonly notes=0ecd0f4eb2f6ab7c073ef2f2afd94e4185ac404b2b01a04a666188d63f029db8
[[ $(sha256sum "$base" | awk '{print $1}') == "$base_sha" ]] || die 'base is not exact qualified v14b coexistence image'
[[ $(stat -c %s "$base") == 11945377792 ]] || die 'base image size differs'
[[ ! -s $dist/abi_stgdiff/abi.report.plain ]] || die 'candidate has a protected ABI difference'

declare -A firmware_files=(
  [gngbtfw20.mbn]=6631fe3562dbb329e2be19f157c55ae8600e24643de3dd8feb2524e21af77b0a
  [gngbtnv20.bin]=669b8a7e03660fad976b48a58871759a8e5188f2b3b32e73419fd170710af763
)
declare -A firmware_sizes=([gngbtfw20.mbn]=294052 [gngbtnv20.bin]=14377)
for name in "${!firmware_files[@]}"; do
  [[ -f $firmware/$name && ! -L $firmware/$name ]] || die "missing regular private firmware: $name"
  [[ $(stat -c %s "$firmware/$name") == "${firmware_sizes[$name]}" ]] ||
    die "private firmware size differs: $name"
  [[ $(sha256sum "$firmware/$name" | awk '{print $1}') == "${firmware_files[$name]}" ]] ||
    die "private firmware hash differs: $name"
done

declare -A files=(
  [Image]=cd0a641d9290b1287fa4d4260b368c8d147dc8a11ee8d11d32008b7ea6389ff9
  [kernel_aarch64_dot_config]=33b6eaf87b7ca2d0d06dd10dbe2a4ce3d58e50ad804d6b385cd5f953e2fe3b95
  [vmlinux.symvers]=aaf3fa84f4ccbab54327eee5a7fed7903e3f79af9ab53fdffe5165b27f2fa9f1
  [kernel_aarch64_Module.symvers]=d5507f9cfb0ba26541dd7c76e077601da89e0ab650ec69acaf854b62ee247f37
  [bluetooth.ko]=5919b022e564c869fcb8eb9e00f4c6f4a2a88e9d04471396dc4b137a3145e269
  [btbcm.ko]=23b81995ffd03242fb12b35d9cd5d756de5aeb3851d6df27c7550ddc6f4647b6
  [btqca.ko]=9f6e1feeb4b74a0f1b2cbf45c5fa09feabd663d8601999b27627d5807e34e164
  [hci_uart.ko]=676f88f5cdf0f2cddcdc12c3d0b91748c341b74f0f195ca9c40216c8f3e515c5
  [pwrseq-core.ko]=162ca5072e040d0690a12b863eef837f0b74a5f6d9380484f32106b883b37c12
  [rfkill.ko]=e2f17221a319f2234a49b4cf809a84867e3e3ef14e22d9bfd393f547e290c47d
  [rmnet.ko]=d372847d3b1bc7e3089e2c1c0b5ea2bd3848437eb24d15e3788a903eff8912a1
)
for name in "${!files[@]}"; do
  [[ -f $dist/$name && ! -L $dist/$name ]] || die "missing regular candidate artifact: $name"
  [[ $(sha256sum "$dist/$name" | awk '{print $1}') == "${files[$name]}" ]] ||
    die "candidate artifact hash differs: $name"
done
[[ $(modinfo -F vermagic "$dist/hci_uart.ko" | awk '{print $1}') == \
  6.12.23-android16-5-g5a0e85dd9db0-dirty-4k ]] || die 'candidate module release differs'
grep -aFq 'preinitialized controller; skipping opening HCI Reset' "$dist/hci_uart.ko" ||
  die 'candidate hci_uart lacks no-opening-reset diagnostic'

cp --reflink=auto --sparse=always -- "$base" "$out"
chmod 0600 "$out"
image=$(alarm_build_image "$ROOT")
docker run --rm --privileged --platform linux/arm64 \
  -v "$out:/payload.img" \
  -v "$dist:/candidate:ro" \
  -v "$firmware:/firmware:ro" \
  -v "$ROOT/device/myron/kernel-experiments/bluetooth-no-open-reset/module-dir-selector.sh:/selector:ro" \
  -v "$ROOT/device/myron/kernel-experiments/bluetooth-no-open-reset/bluetooth-only-start.sh:/bluetooth-only-start:ro" \
  -v "$ROOT/device/myron/hardware-test-overlay/usr/local/sbin/myron-bluetooth-stage:/bluetooth-stage:ro" \
  -v "$ROOT/device/myron/hardware-test-overlay/usr/local/sbin/myron-omarchy-prepare:/omarchy-prepare:ro" \
  "$image" bash -euo pipefail -c '
    root=/mnt/payload
    mkdir -p "$root"
    loop=
    cleanup() {
      sync
      umount "$root" 2>/dev/null || true
      [[ -z $loop ]] || losetup -d "$loop" 2>/dev/null || true
    }
    trap cleanup EXIT
    loop=$(losetup --find --show /payload.img)
    mount -o rw "$loop" "$root"
    grep -Fxq ID=omarchy "$root/etc/os-release"
    test -L "$root/etc/systemd/system/multi-user.target.wants/myron-coexistence.service"
    target="$root/usr/local/lib/myron-gki-module-sets/'"$notes"'"
    test ! -e "$target"
    install -d -m0755 "$target" "$root/etc/omamobile" \
      "$root/etc/systemd/journald.conf.d" \
      "$root/usr/local/lib/myron-bluetooth-firmware"
    for name in bluetooth btbcm btqca hci_uart pwrseq-core rfkill rmnet; do
      install -m0644 "/candidate/$name.ko" "$target/$name.ko"
    done
    install -m0600 /firmware/gngbtfw20.mbn /firmware/gngbtnv20.bin \
      "$root/usr/local/lib/myron-bluetooth-firmware/"
    install -m0755 /selector "$root/usr/local/sbin/myron-attempt79-module-dir"
    install -m0755 /bluetooth-only-start "$root/usr/local/sbin/myron-coexistence-start"
    install -m0755 /bluetooth-stage "$root/usr/local/sbin/myron-bluetooth-stage"
    install -m0755 /omarchy-prepare "$root/usr/local/sbin/myron-omarchy-prepare"
    printf "%s\n" bluetooth >"$root/etc/omamobile/myron-test-profile"
    ln -sfnT /dev/null "$root/etc/systemd/system/myron-omarchy-qualify.service"
    ln -sfnT /dev/null "$root/etc/systemd/system/myron-reference-radio.service"
    ln -sfnT /dev/null "$root/etc/systemd/system/myron-reference-audio-foundation.service"
    ln -sfnT /dev/null "$root/etc/systemd/system/myron-speaker-bridge.service"
    printf "%s\n" "[Journal]" "Storage=volatile" "RuntimeMaxUse=8M" \
      >"$root/etc/systemd/journald.conf.d/90-myron-bluetooth-volatile.conf"
    chmod 0644 "$root/etc/systemd/journald.conf.d/90-myron-bluetooth-volatile.conf"
    chown 0:0 "$root/etc/systemd/journald.conf.d/90-myron-bluetooth-volatile.conf"
    chown -R 0:0 "$target" "$root/usr/local/lib/myron-bluetooth-firmware" \
      "$root/usr/local/sbin/myron-attempt79-module-dir" \
      "$root/usr/local/sbin/myron-coexistence-start" \
      "$root/usr/local/sbin/myron-bluetooth-stage" \
      "$root/usr/local/sbin/myron-omarchy-prepare" "$root/etc/omamobile/myron-test-profile"
    chmod 0644 "$root/etc/omamobile/myron-test-profile"
    sync
    umount "$root"
    losetup -d "$loop"
    loop=
    trap - EXIT
  '
e2fsck -fn "$out" >/dev/null
hash=$(sha256sum "$out" | awk '{print $1}')
printf 'status=composed\nimage=%s\nsha256=%s\nprofile=bluetooth\nkernel_notes=%s\n' \
  "$out" "$hash" "$notes"
