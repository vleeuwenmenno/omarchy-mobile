<!-- SPDX-License-Identifier: MIT -->
# Myron cellular + speaker coexistence experiment

Status: implemented for offline composition and mocked testing only. No image
from this profile has been copied to the phone, booted, or started.

`audio-cellular-speaker` is an attended persistent-MAIN experiment for the
smallest useful radio/audio boundary: one normally admitted ModemManager,
exactly one home-registered LTE/5G modem, no packet-data bearer, no GNSS, no
Bluetooth, then one fixed 250 ms speaker probe. It does not test mobile data,
calls, microphone capture, Bluetooth audio, or GNSS.

The profile uses its own marker,
`/etc/omamobile/myron-cellular-audio-experiment`. The isolated-audio marker is
absent, so `myron-cellular.service` and the one-start ModemManager admission
path can run unchanged. Packet-data operations and both GeoClue and GNSS
mutations refuse the combined marker. The legacy audio services remain masked.

## Boot and start contract

The image enables the existing cellular service and Wi-Fi rescue import. It
does not enable the cellular publisher, graphical qualifier, coexistence
service, or `myron-cellular-audio-experiment.service`. The independent MAIN
guard and uncommitted `pending` token therefore remain armed. The experiment
service is static and must be started explicitly after live inspection.

Before AudioReach mutation, the runner requires:

1. A current, private four-line combined request and uncommitted MAIN pending
   token; it atomically consumes the request before any audio work.
2. A stable, live hardware-watchdog PID and a stable, live ModemManager PID.
3. Exactly one SIM-ready, home-attached LTE/5G modem for 60 seconds, with the
   one-start admission marker from this boot.
4. A pristine IPA guard, no data-state file or `qmapmux0.0`, no GNSS admission,
   and no Bluetooth controller or `btattach` process.
5. Active SSH plus addressed USB and Wi-Fi rescue links, PMIC at or below
   65 C before audio, PMIC at or below 68 C while settling, and every valid
   non-trip temperature below 95 C.
6. At least 720 seconds remain on the independent MAIN guard before the
   registration settle and at least 600 seconds remain before AudioReach arm;
   every later stage keeps a 120-second recovery reserve.

Every audio stage rechecks the guard, registered modem, IPA state, exclusions,
and temperatures. The existing speaker probe keeps its own 70 C PMIC limit and
plays exactly one 250 ms, 440 Hz tone at approximately -45 dBFS. There is no
retry in the same boot.

The runner writes a root-only, atomically replaced and synced stage record at
`/run/myron-host/var/lib/omarchy-mobile/main/cellular-audio-experiment.stage`.
It records fixed aggregate facts only: mode, boot ID, boundary, stable modem
PID, temperatures, exclusions and probe result. It never records modem, SIM,
network or device identifiers. Boundaries include request consumption,
cellular start, stable registration, audio arm, probe start and probe result.

Normal success, refusal, timeout, signal, stage failure or cleanup failure
requests MAIN recovery to preserved postmarketOS. A kernel hard reset can stop
userspace before recovery; stale `pending` plus the independent guard then
select postmarketOS on the next successful boot. The phone previously reset to
fastboot when ModemManager, GNSS and AudioReach were mixed. GNSS is excluded
here, but recurrence remains possible. This kernel exposes no proven pstore
record for that reset, so the synced boundary identifies the last completed
stage but cannot prove the kernel cause.

## Offline composition

Use the same explicit inputs documented in `AUDIO-EXPERIMENT.md`, changing only
the profile and output path:

```fish
tools/myron-dev-image-compose --boot-policy main \
  --profile audio-cellular-speaker \
  --base-image /abs/base.ext4 \
  --module-stage /abs/modules \
  --module-assets-archive /abs/systemd-vt-device-assets.tar.gz \
  --runtime-stage /abs/runtime \
  --runtime-manifest /abs/myron-runtime-assets.tsv \
  --bluetooth-probe /abs/probe.py \
  --speaker-reference-repo /abs/ref \
  --firstboot-conf /abs/firstboot.conf \
  --ssh-key /abs/owner.pub \
  --out /abs/myron-audio-cellular-speaker.ext4
```

Expected result includes `profile=audio-cellular-speaker`,
`effective_profile=cellular`,
`activation=persistent-main-cellular-audio-experiment`, and
`deployment_authorized=false`.

## Approval boundary and stop conditions

Composition and offline tests do not authorize deployment. Before copying an
image, changing `init_boot`, rebooting, or starting the static service, obtain
separate owner approval naming the exact image SHA-256 and accepting one fixed
audible probe plus the known hard-reset risk. Verify the existing read-only
radio backup evidence, rollback image identity, battery, PMIC temperature,
USB SSH and Wi-Fi SSH before the boot.

Stop on any changed/dead PID, missing rescue link, non-home registration,
packet-data or GNSS evidence, dirty IPA guard, temperature refusal, timeout,
unexpected reboot, fastboot entry, or cleanup failure. Do not retry in the
same boot. If registration-only plus speaker passes, packet data plus audio is
a separate later image and approval; it is not silently widened here.
