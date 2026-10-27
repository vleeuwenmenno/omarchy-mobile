# shellcheck shell=sh
# Main init stage, appended after the original init's module and logfs setup.
# Order: mount and prove pmOS, select, durable pending token, then (only for
# omarchy) payload mount and checks, NCM-only rescue gadget, runtime files and
# the final moves. There is deliberately no ACM console: no unauthenticated
# root shell exists in the main boot.
# The original init does not run under set -e, so every operation that the main
# boot depends on is checked explicitly and routes to fail_boot (unwind and
# handoff to pmOS) before anything is moved. Nothing after a failed check may
# reach switch_root into the Omarchy payload.
stage_put() { printf '%s\n' "$1" >"$2"; }
# Same size and a regular, executable result: a truncated copy is a failed copy.
stage_copied() {
	[ -f "$2" ] && [ ! -L "$2" ] && [ -x "$2" ] &&
		[ "$(/bin/stat -c %s "$1" 2>/dev/null)" = "$(/bin/stat -c %s "$2" 2>/dev/null)" ] &&
		[ "$(/bin/stat -c %s "$2")" -gt 0 ]
}
# Critical main units must come from the payload's /usr/lib only, with at most
# the provided main drop-in. A same-named unit or drop-in in a higher-priority
# location would shadow the guard, recovery or qualifier.
stage_unit_shadowed() {
	for unit_name in myron-hardware-watchdog myron-main-recover myron-audio-experiment myron-cellular-audio-experiment myron-omarchy-qualify \
		myron-omarchy-prepare myron-cellular myron-batterysecret; do
		for unit_dir in /newroot/etc/systemd/system /newroot/etc/systemd/system.control \
			/newroot/usr/local/lib/systemd/system /newroot/run/systemd/system \
			/newroot/run/systemd/system.control /newroot/run/systemd/transient; do
			for unit_obj in "$unit_dir/$unit_name.service" "$unit_dir/$unit_name.service.d"; do
				if [ -e "$unit_obj" ] || [ -L "$unit_obj" ]; then return 0; fi
			done
		done
		unit_d=/newroot/usr/lib/systemd/system/$unit_name.service.d
		if [ -e "$unit_d" ] || [ -L "$unit_d" ]; then
			case $unit_name in
				myron-omarchy-qualify | myron-omarchy-prepare | myron-cellular | myron-batterysecret) ;;
				*) return 0 ;;
			esac
			[ -d "$unit_d" ] && [ ! -L "$unit_d" ] || return 0
			for unit_obj in "$unit_d"/* "$unit_d"/.[!.]* "$unit_d"/..?*; do
				[ -e "$unit_obj" ] || [ -L "$unit_obj" ] || continue
				[ "${unit_obj##*/}" = 90-myron-main.conf ] && [ -f "$unit_obj" ] && [ ! -L "$unit_obj" ] || return 0
			done
			[ -f "$unit_d/90-myron-main.conf" ] || return 0
		fi
	done
	# Type- and prefix-wide drop-ins in the high-priority trees apply to every unit.
	for unit_dir in /newroot/etc/systemd/system /newroot/usr/local/lib/systemd/system /newroot/run/systemd/system; do
		for unit_obj in "$unit_dir/service.d" "$unit_dir"/myron-*; do
			if [ -e "$unit_obj" ] || [ -L "$unit_obj" ]; then return 0; fi
		done
	done
	return 1
}
wait_partition pmos_root || fail_boot pmos-root-missing
root_device=$found_device
/bin/mkdir -p /hostroot /newroot || fail_boot main-mountpoints-failed
/bin/mount -t ext4 -o rw,noatime "$root_device" /hostroot || fail_boot pmos-root-mount-failed
hostroot_mounted=1
# The fallback itself must be provably startable before anything is attempted.
[ -x /hostroot/usr/lib/systemd/systemd ] || fail_boot pmos-systemd-pid1-missing
[ "$(/bin/readlink /hostroot/sbin/init 2>/dev/null)" = ../lib/systemd/systemd ] ||
	fail_boot pmos-init-link-invalid
valid_rootfs_identity \
	/hostroot/usr/lib/os-release \
	/hostroot/lib/apk/db/installed \
	/hostroot/var/lib/myron-modules/systemd-core/installed.sha256 ||
	fail_boot pmos-root-identity-invalid
pmos_ready=1

[ -f /main-select.sh ] || fail_boot main-selector-missing
. /main-select.sh
main_select
main_log "selected=$main_choice reason=$main_reason"
write_marker "main-select-$main_choice"
[ "$main_choice" = omarchy ] || handoff_pmos "$main_reason"

main_begin_attempt || fail_boot main-pending-write-failed
main_verify_attempt || fail_boot main-pending-verify-failed
state=/hostroot/var/lib/omarchy-mobile
payload=$main_dir/rootfs.img

for uevent in /sys/class/block/loop*/uevent; do
	[ -r "$uevent" ] || continue
	loop_name=$(/bin/sed -n 's/^DEVNAME=//p' "$uevent")
	major=$(/bin/sed -n 's/^MAJOR=//p' "$uevent")
	minor=$(/bin/sed -n 's/^MINOR=//p' "$uevent")
	[ -n "$loop_name" ] && [ -n "$major" ] && [ -n "$minor" ] || continue
	[ -b "/dev/$loop_name" ] || /bin/mknod "/dev/$loop_name" b "$major" "$minor"
done
payload_loop=$(/bin/losetup -f 2>/dev/null)
[ -n "$payload_loop" ] || fail_boot omarchy-no-free-loop-device
/bin/losetup "$payload_loop" "$payload" || fail_boot omarchy-loop-attach-failed
loop_dev=$payload_loop
/bin/mount -t ext4 -o rw,noatime "$payload_loop" /newroot || fail_boot omarchy-payload-mount-failed
newroot_mounted=1
[ -x /newroot/usr/lib/systemd/systemd ] || fail_boot omarchy-systemd-missing
[ "$(/bin/readlink /newroot/sbin/init 2>/dev/null)" = ../lib/systemd/systemd ] ||
	fail_boot omarchy-systemd-link-invalid
/bin/grep -Fqx 'ID=omarchy' /newroot/etc/os-release || fail_boot omarchy-os-release-mismatch
/bin/grep -Fqx 'development-only: unsigned package repository' \
	/newroot/var/lib/omamobile/repo/aarch64/.omamobile-dev-unsigned ||
	fail_boot omarchy-unsigned-marker-missing
# The effective main-init profile remains cellular. Audio experiment images
# carry a second, exact mode marker; they must not widen this init contract.
[ "$(/bin/cat /newroot/etc/omamobile/myron-test-profile 2>/dev/null)" = cellular ] ||
	fail_boot omarchy-profile-not-cellular
isolated_experiment_mode=$(/bin/cat /newroot/etc/omamobile/myron-audio-experiment 2>/dev/null || true)
cellular_audio_mode=$(/bin/cat /newroot/etc/omamobile/myron-cellular-audio-experiment 2>/dev/null || true)
main_experiment_mode=
audio_request_path=
case $isolated_experiment_mode:$cellular_audio_mode in
	:) ;;
	audio-speaker:|audio-microphone:)
		main_experiment_mode=$isolated_experiment_mode
		audio_request_path=/run/myron-main/audio-experiment.request
		[ -x /newroot/usr/local/sbin/myron-audio-experiment ] ||
			fail_boot omarchy-audio-experiment-runner-missing
		[ -f /newroot/usr/lib/systemd/system/myron-audio-experiment.service ] ||
			fail_boot omarchy-audio-experiment-unit-missing
		[ -L /newroot/etc/systemd/system/multi-user.target.wants/myron-audio-experiment.service ] ||
			fail_boot omarchy-audio-experiment-not-enabled
		;;
	:audio-cellular-speaker)
		main_experiment_mode=$cellular_audio_mode
		audio_request_path=/run/myron-main/cellular-audio-experiment.request
		[ -x /newroot/usr/local/sbin/myron-audio-experiment ] ||
			fail_boot omarchy-audio-experiment-runner-missing
		[ -f /newroot/usr/lib/systemd/system/myron-cellular-audio-experiment.service ] ||
			fail_boot omarchy-cellular-audio-unit-missing
		[ ! -e /newroot/etc/systemd/system/multi-user.target.wants/myron-cellular-audio-experiment.service ] &&
			[ ! -L /newroot/etc/systemd/system/multi-user.target.wants/myron-cellular-audio-experiment.service ] ||
			fail_boot omarchy-cellular-audio-unit-enabled
		[ -L /newroot/etc/systemd/system/multi-user.target.wants/myron-cellular.service ] ||
			fail_boot omarchy-cellular-audio-cellular-not-enabled
		;;
	*) fail_boot omarchy-audio-experiment-mode-invalid ;;
esac
# The payload must carry the main guard unit (same unit name the hardware units
# require) and the main control, never the temporary partition-writing watchdog.
guard_unit=/newroot/usr/lib/systemd/system/myron-hardware-watchdog.service
[ -f "$guard_unit" ] && [ ! -L "$guard_unit" ] ||
	fail_boot omarchy-main-guard-unit-missing
/bin/grep -Fq 'ExecStart=/run/myron-main/bin/busybox sh /run/myron-main/myron-main-os guard' "$guard_unit" ||
	fail_boot omarchy-main-guard-unit-invalid
! /bin/grep -Fq '/run/myron-watchdog' "$guard_unit" || fail_boot omarchy-temporary-watchdog-unit
[ -f /newroot/usr/lib/systemd/system/myron-main-recover.service ] ||
	fail_boot omarchy-main-recover-unit-missing
[ -x /newroot/usr/local/sbin/myron-main-os ] || fail_boot omarchy-main-control-missing
! stage_unit_shadowed || fail_boot omarchy-critical-unit-shadowed

# Runtime for the guard: copied BusyBox plus its musl loader, independent of
# the payload's own shell and libc. The payload root is not trusted to be usable.
/bin/mkdir -p /run/myron-main/bin /newroot/lib /newroot/tmp /newroot/dev /newroot/proc \
	/newroot/sys /newroot/run /newroot/mnt || fail_boot main-runtime-mkdir-failed
/bin/cp /bin/busybox /run/myron-main/bin/busybox || fail_boot main-runtime-busybox-copy-failed
/bin/cp /myron-main-os /run/myron-main/myron-main-os || fail_boot main-runtime-control-copy-failed
/bin/chmod 0755 /run/myron-main/bin/busybox /run/myron-main/myron-main-os ||
	fail_boot main-runtime-chmod-failed
stage_copied /bin/busybox /run/myron-main/bin/busybox || fail_boot main-runtime-busybox-invalid
stage_copied /myron-main-os /run/myron-main/myron-main-os || fail_boot main-runtime-control-invalid
/run/myron-main/bin/busybox true || fail_boot main-runtime-busybox-unusable
/run/myron-main/bin/busybox sh -n /run/myron-main/myron-main-os || fail_boot main-runtime-control-unparsable
/bin/cp /lib/ld-musl-aarch64.so.1 /newroot/lib/ld-musl-aarch64.so.1 || fail_boot main-musl-copy-failed
/bin/chmod 0755 /newroot/lib/ld-musl-aarch64.so.1 || fail_boot main-musl-chmod-failed
/bin/ln -snf ld-musl-aarch64.so.1 /newroot/lib/libc.musl-aarch64.so.1 || fail_boot main-musl-link-failed
stage_copied /lib/ld-musl-aarch64.so.1 /newroot/lib/ld-musl-aarch64.so.1 || fail_boot main-musl-invalid
[ "$(/bin/readlink /newroot/lib/libc.musl-aarch64.so.1 2>/dev/null)" = ld-musl-aarch64.so.1 ] ||
	fail_boot main-musl-link-invalid
/bin/cp /bin/busybox /newroot/tmp/busybox || fail_boot main-probe-copy-failed
/bin/chmod 0755 /newroot/tmp/busybox || fail_boot main-probe-chmod-failed
/bin/chroot /newroot /tmp/busybox true || fail_boot main-runtime-invalid
/bin/rm -f /newroot/tmp/busybox || fail_boot main-probe-remove-failed
/run/myron-main/bin/busybox --install -s /run/myron-main/bin || fail_boot main-runtime-install-failed
# The runtime token files, with readback: the guard and the commit trust them.
stage_put "$main_id" /run/myron-main/boot-id || fail_boot main-runtime-boot-id-failed
stage_put "$main_image_id" /run/myron-main/image-id || fail_boot main-runtime-image-id-failed
/bin/chmod 0600 /run/myron-main/boot-id /run/myron-main/image-id || fail_boot main-runtime-token-chmod-failed
[ "$(/bin/cat /run/myron-main/boot-id 2>/dev/null)" = "$main_id" ] || fail_boot main-runtime-boot-id-mismatch
[ "$(/bin/cat /run/myron-main/image-id 2>/dev/null)" = "$main_image_id" ] || fail_boot main-runtime-image-id-mismatch
if [ -n "$main_experiment_mode" ]; then
	main_kernel=$(/bin/uname -r 2>/dev/null) || fail_boot main-runtime-kernel-failed
	case $main_kernel in ''|*[!A-Za-z0-9._+-]*) fail_boot main-runtime-kernel-failed ;; esac
	stage_put "$main_kernel" /run/myron-main/kernel-release || fail_boot main-runtime-kernel-failed
	/bin/chmod 0600 /run/myron-main/kernel-release || fail_boot main-runtime-token-chmod-failed
	audio_request=$(printf 'mode=%s\nboot_id=%s\nimage_id=%s\nkernel=%s' \
		"$main_experiment_mode" "$main_id" "$main_image_id" "$main_kernel")
	stage_put "$audio_request" "$audio_request_path" ||
		fail_boot main-audio-request-write-failed
	/bin/chmod 0600 "$audio_request_path" ||
		fail_boot main-audio-request-chmod-failed
	[ "$(/bin/cat "$audio_request_path" 2>/dev/null)" = "$audio_request" ] ||
		fail_boot main-audio-request-mismatch
fi

# NCM only: rescue network, no console, no shell on the gadget.
role_path=/sys/class/usb_role/a600000.ssusb-role-switch/role
attempt=0
while [ "$attempt" -lt 30 ] && [ ! -w "$role_path" ]; do
	attempt=$((attempt + 1))
	/bin/sleep 1
done
[ -w "$role_path" ] || fail_boot usb-role-missing
printf '%s\n' device >"$role_path" || fail_boot usb-role-write-failed
udc_name=
attempt=0
while [ "$attempt" -lt 30 ]; do
	for udc in /sys/class/udc/*; do
		[ -e "$udc" ] || continue
		udc_name=${udc##*/}
		break
	done
	[ -n "$udc_name" ] && break
	attempt=$((attempt + 1))
	/bin/sleep 1
done
[ -n "$udc_name" ] || fail_boot usb-udc-missing
/bin/mkdir -p /config || fail_boot configfs-mountpoint-failed
/bin/mount -t configfs configfs /config || fail_boot configfs-mount-failed
config_mounted=1
gadget=/config/usb_gadget/g1
gadget_made=1
/bin/mkdir -p "$gadget/strings/0x409" "$gadget/configs/c.1/strings/0x409" ||
	fail_boot gadget-create-failed
stage_put '0xEF' "$gadget/bDeviceClass" || fail_boot gadget-config-failed
stage_put '0x02' "$gadget/bDeviceSubClass" || fail_boot gadget-config-failed
stage_put '0x01' "$gadget/bDeviceProtocol" || fail_boot gadget-config-failed
stage_put '0x1d6b' "$gadget/idVendor" || fail_boot gadget-config-failed
stage_put '0x0104' "$gadget/idProduct" || fail_boot gadget-config-failed
stage_put 'MyronOmarchy0001' "$gadget/strings/0x409/serialnumber" || fail_boot gadget-config-failed
stage_put 'Omarchy Mobile' "$gadget/strings/0x409/manufacturer" || fail_boot gadget-config-failed
stage_put 'Myron Omarchy main' "$gadget/strings/0x409/product" || fail_boot gadget-config-failed
stage_put 'NCM rescue network' "$gadget/configs/c.1/strings/0x409/configuration" || fail_boot gadget-config-failed
/bin/mkdir "$gadget/functions/ncm.usb0" || fail_boot ncm-create-failed
stage_put 02:00:00:00:00:01 "$gadget/functions/ncm.usb0/dev_addr" || fail_boot ncm-config-failed
stage_put 02:00:00:00:00:02 "$gadget/functions/ncm.usb0/host_addr" || fail_boot ncm-config-failed
/bin/ln -s "$gadget/functions/ncm.usb0" "$gadget/configs/c.1/ncm.usb0" ||
	fail_boot ncm-link-failed
stage_put "$udc_name" "$gadget/UDC" || fail_boot gadget-bind-failed
attempt=0
while [ "$attempt" -lt 30 ] && [ ! -e /sys/class/net/usb0 ]; do
	attempt=$((attempt + 1))
	/bin/sleep 1
done
[ -e /sys/class/net/usb0 ] || fail_boot usb0-missing
/bin/ifconfig usb0 172.16.42.1 netmask 255.255.255.0 up || fail_boot usb0-address-failed

# Compatibility arm for the existing hardware units. They gate on this file and
# on the guard unit above; the old previous-boot arm gate is not used. Without
# it every guard, prepare, cellular and qualify unit skips (ConditionPathExists)
# and nothing would recover an unqualified boot, so any failure here is fatal.
armed=$state/hardware-test.armed
armed_expect=$(printf 'mode=main\nboot_id=%s\nimage_id=%s' "$main_id" "$main_image_id")
/bin/rm -f "$state/hardware-test.disarm" || fail_boot main-disarm-remove-failed
armed_written=1
printf '%s\n' "$armed_expect" >"$armed.new" || fail_boot main-arm-write-failed
/bin/sync || fail_boot main-arm-sync-failed
/bin/mv -f "$armed.new" "$armed" || fail_boot main-arm-rename-failed
/bin/sync || fail_boot main-arm-sync-failed

# Everything the guard and the qualifier will rely on, proven again immediately
# before the first mount move: arm, tokens, pending, no latch, guard runtime.
[ -f "$armed" ] && [ ! -L "$armed" ] && [ ! -e "$armed.new" ] || fail_boot main-arm-invalid
[ "$(/bin/cat "$armed" 2>/dev/null)" = "$armed_expect" ] || fail_boot main-arm-mismatch
main_verify_attempt || fail_boot main-pending-verify-failed
[ ! -e "$main_dir/latch" ] && [ ! -L "$main_dir/latch" ] || fail_boot main-latch-appeared
[ "$(/bin/cat /run/myron-main/boot-id 2>/dev/null)" = "$main_id" ] || fail_boot main-runtime-boot-id-mismatch
[ "$(/bin/cat /run/myron-main/image-id 2>/dev/null)" = "$main_image_id" ] || fail_boot main-runtime-image-id-mismatch
[ -z "$main_experiment_mode" ] ||
	{ [ "$(/bin/cat /run/myron-main/kernel-release 2>/dev/null)" = "$main_kernel" ] &&
	[ "$(/bin/cat "$audio_request_path" 2>/dev/null)" = "$audio_request" ] ||
	fail_boot main-audio-request-mismatch; }
[ -x /run/myron-main/bin/busybox ] && [ -f /run/myron-main/myron-main-os ] || fail_boot main-runtime-missing
[ -f "$guard_unit" ] && [ ! -L "$guard_unit" ] || fail_boot omarchy-main-guard-unit-missing

/bin/mkdir -p /run/myron-host || fail_boot main-host-mountpoint-failed
/bin/mount -o move /hostroot /run/myron-host || fail_boot omarchy-host-move-failed
host_moved=1
write_marker omarchy-switch-root-ready
[ "$logfs_mounted" -eq 0 ] || /bin/umount /mnt/logfs || fail_boot logfs-unmount-failed
logfs_mounted=0
# From here the fallback must first move every mount back (main_unwind).
/bin/mount -o move /proc /newroot/proc || fail_boot proc-move-failed
moved_mounts="proc"
/bin/mount -o move /sys /newroot/sys || fail_boot sys-move-failed
moved_mounts="$moved_mounts sys"
/bin/mkdir -p /newroot/sys/kernel/config || fail_boot config-mountpoint-failed
/bin/mount -o move /config /newroot/sys/kernel/config || fail_boot config-move-failed
moved_mounts="$moved_mounts config"
/bin/mount -o move /run /newroot/run || fail_boot run-move-failed
moved_mounts="$moved_mounts run"
/bin/mount -o move /dev /newroot/dev || fail_boot dev-move-failed
moved_mounts="$moved_mounts dev"
/bin/sync || fail_boot final-sync-failed
# Past this point no same-boot fallback exists: the guard unit and the
# persistent latch recover.
exec /bin/switch_root /newroot /sbin/init
fail_boot omarchy-switch-root-returned
