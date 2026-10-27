<!-- SPDX-License-Identifier: MIT -->
# Myron cellular + speaker coexistence experiment

Status: hardware-tested on 2026-10-27. Registered LTE/5G and the guarded
speaker path coexisted through one complete probe and automatic pmOS recovery.
Subjective audibility still requires the attended listener's confirmation.

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

## 2026-10-27 hardware result

The exact combined rootfs was
`4ce269728ccd5e9d36cc02a26162c34ae21771db70c89dca94e1101f4a3f83e6`
before its first mount. The first boot failed closed before pivot with
`omarchy-critical-unit-shadowed`: the broad initramfs guard rejected the three
intentional legacy-audio `/dev/null` masks. No radio/audio experiment ran. The
guard was narrowed in commit `73dfe212a6041a8468dc40505ad6658cde6619aa`
to admit only those three exact masks while rejecting every other high-priority
override. The retry used this reviewed `init_boot_a` image:

```
ff7b25339ceb23a00e719b891dfee0ece24f44b3adda99f47fe5d7bdf9f9d5ad
```

On boot `d58d98f4-e9d5-4217-a3ad-f3b8413e9d8e`, live pre-start inspection
showed one registered, SIM-ready, home-attached LTE/5G modem; no data attempt or
state, `qmapmux0.0`, GNSS admission, Bluetooth controller or `btattach`; a
pristine IPA guard; addressed USB and Wi-Fi rescue; active SSH; PMIC 43.274 C;
and hottest valid non-trip sensor 73.7 C. ModemManager PID 4473 and the MAIN
guard remained stable through the 60-second settle and every audio stage.

The durable final boundary was:

```
mode=audio-cellular-speaker
boot_id=d58d98f4-e9d5-4217-a3ad-f3b8413e9d8e
boundary=probe-result
modem_pid=4473 result=pass kind=speaker duration_ms=250 level_dbfs=-45 tfa=Powerdown
```

Logs record exactly one probe after mapper, transport, ADSP, codecs, devnodes,
FastRPC and speaker-DSP readiness. Cleanup stopped streams, restored controls
and powered TFA down. Recovery completed normally into pmOS boot
`002580a8-1c82-4729-8e8e-1958d94a4885` with latch reason
`audio-cellular-speaker-complete`. There was no fastboot entry or hard reset.

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
