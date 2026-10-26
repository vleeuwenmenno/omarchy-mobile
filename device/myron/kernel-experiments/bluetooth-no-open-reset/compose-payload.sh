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
readonly notes=1e4a036d6f8bcc2602567ec5e0ff7aaa871564af18c9c7c8dee426b110834eea
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
  [Image]=672808b1277b583fdc398986bfe8d100b2ebbf1c2cfbb9d14dd257366d1a5937
  [kernel_aarch64_dot_config]=33b6eaf87b7ca2d0d06dd10dbe2a4ce3d58e50ad804d6b385cd5f953e2fe3b95
  [vmlinux.symvers]=aaf3fa84f4ccbab54327eee5a7fed7903e3f79af9ab53fdffe5165b27f2fa9f1
  [kernel_aarch64_Module.symvers]=d5507f9cfb0ba26541dd7c76e077601da89e0ab650ec69acaf854b62ee247f37
  [bluetooth.ko]=c69bd2a120843f33983bcd53e93f12eecfe53c8d6c65e1952111f352bf0d6ca2
  [btbcm.ko]=9042c46a7b350ee70bcb49cfb12c9111f6a47dfcf3f9ca176533875b8483970c
  [btqca.ko]=395a40611e6510910d8a069b32eef631cf7cf56a1f2ff526a03c8e0772b166ef
  [hci_uart.ko]=8a032d5ebb174ff81c0aa01d6ecc34fd9718723ffa432c0ae56416918a6772a9
  [pwrseq-core.ko]=93ee7bc34a78303d569944d177832e3519ba7fb8f283a32fa6baea7f97c11104
  [rfkill.ko]=7e3caceca204611bf88495b5554e7ff9de693d2551fcb25cfb83356cbe134f34
  [rmnet.ko]=3b3f75d3738e77a3afd572a83f8cdce8aab9022409b3c9b2830860304a2990a0
)
for name in "${!files[@]}"; do
  [[ -f $dist/$name && ! -L $dist/$name ]] || die "missing regular candidate artifact: $name"
  [[ $(sha256sum "$dist/$name" | awk '{print $1}') == "${files[$name]}" ]] ||
    die "candidate artifact hash differs: $name"
done
readonly expected_release=6.12.23-android16-5-g5a0e85dd9db0-dirty-4k
for name in hci_uart bluetooth; do
  [[ $(modinfo -F vermagic "$dist/$name.ko" | awk '{print $1}') == "$expected_release" ]] ||
    die "candidate module release differs: $name"
done
grep -aFq 'preinitialized controller; skipping opening HCI Reset' "$dist/hci_uart.ko" ||
  die 'candidate hci_uart lacks no-opening-reset diagnostic'
grep -aFq 'recovering discovery stop on Inquiry Complete' "$dist/bluetooth.ko" ||
  die 'candidate bluetooth module lacks inquiry-stop recovery diagnostic'

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
    free_loop=$(losetup -f)
    free_minor=${free_loop#/dev/loop}
    case $free_minor in ""|*[!0-9]*)
      printf "error: unsafe free loop device: %s\n" "$free_loop" >&2; exit 1 ;;
    esac
    [[ $free_loop == /dev/loop$free_minor ]] || {
      printf "error: unsafe free loop device: %s\n" "$free_loop" >&2; exit 1;
    }
    rm -f -- "$free_loop"
    mknod -m 0600 "$free_loop" b 7 "$free_minor"
    losetup "$free_loop" /payload.img
    loop=$free_loop
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
