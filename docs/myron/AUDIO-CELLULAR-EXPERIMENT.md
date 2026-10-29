<!-- SPDX-License-Identifier: MIT -->
# Myron cellular + speaker coexistence experiment

Status: radio/audio graph coexistence tested on 2026-10-27, but speaker output
failed the attended acceptance check. Registered LTE/5G survived the complete
`-45 dBFS` raw probe and automatic pmOS recovery; the listener heard nothing.
That run is not evidence of working speaker output.

`audio-cellular-speaker` is an attended persistent-MAIN experiment for the
smallest useful radio/audio boundary: one normally admitted ModemManager,
exactly one home-registered LTE/5G modem, no packet-data bearer, no GNSS, no
Bluetooth, then one fixed 250 ms speaker probe. It does not test mobile data,
calls, microphone capture, Bluetooth audio, or GNSS.

`audio-cellular-bridge` is the corrective attended mode. It keeps the same
modem-first, data/GNSS/Bluetooth exclusions and automatic pmOS recovery, but
uses the previously user-confirmed PipeWire FIFO -> OEM MIPLAY -> three-TFA
bridge at its proven `-12 dB` software cap. It plays one bounded 1.5-second
left tone, 0.75 seconds of silence and one 1.5-second right tone. An exit-zero
result is insufficient: the listener must confirm audible output from the top
and bottom speakers.

The profile uses its own marker,
`/etc/omamobile/myron-cellular-audio-experiment`. The isolated-audio marker is
absent, so `myron-cellular.service` and the one-start ModemManager admission
path can run unchanged. Packet-data operations and both GeoClue and GNSS
mutations refuse the combined marker. The legacy foundation and microphone
services remain masked. In corrective bridge mode only the exact
checksum-pinned speaker bridge is available; the runner admits it after
modem-safe AudioReach staging and stops it before recovery.

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
The listener then reported no sound. Therefore the software boundary passed,
but the acoustic acceptance result failed.

The first corrective `audio-cellular-bridge` boot used rootfs SHA-256
`8e50b66abf2bfa5eef548844088c1e80ad3ead4d1f51ead9dcfe9f896cb93051`
and boot ID `c381b09d-d8de-4cab-ae2c-c5b9ac8384fd`. Live inspection again proved
home registration on LTE plus 5G NR, active USB and Wi-Fi rescue, no packet-data
mutation, GNSS or Bluetooth, PMIC 38.709 C and hottest valid non-trip sensor
73.3 C. AudioReach reached `speaker-dsp`, the exact bridge became ready and the
durable boundary reached `probe-started`, but the FIFO producer hit its
10-second cap before completing the 3.75-second waveform. The run failed
closed with `bounded left/right speaker bridge tones failed`, powered the TFA
amplifiers down and recovered normally to pmOS with latch
`audio-experiment-failed`; `boot_a` remained unchanged. This is not an acoustic
pass. The corrective writer now precomputes the complete 720000-byte waveform
before opening the FIFO and gives the already-bounded OEM graph 30 seconds to
consume it.

The second corrective v59 run used that precomputed writer and a 30-second
FIFO limit. It again reached `probe-started` with the registered modem stable,
but the producer still did not complete before the bound. The durable record
was boot ID `73a88eca-9e39-4fef-b1bc-f2c0d67182f0`, modem PID 4456, mode
`audio-cellular-bridge`, 3750 ms, `-12 dB`, left+right. Automatic recovery
returned to pmOS; the current pmOS boot ID is
`ac4ee6db-3c5a-49ac-9f6c-ab290d46719a`. No audible acceptance test occurred.
Therefore v59 also fails and must not be described as restored speaker support.

The v59 failure exposed a protocol bug in the corrective probe, not proof that
the OEM graph itself failed. The bridge reads one 15,360-byte PCM period, then
opens and starts the MIPLAY graph. The producer wrote the remaining 704,640
bytes immediately, so the FIFO could fill while that hardware transaction was
still in progress. Extending the timeout or precomputing samples did not fix
that ordering error.

The next candidate carries an explicit two-phase handshake. It writes exactly
one period, waits for a runtime-only `stream-ready` marker published at the
bridge's post-`pcm_start` `stream_pcm` boundary, then writes the remainder. The
marker is cleared before every service start and on normal, error and cleanup
paths. The whole producer remains bounded to 60 seconds, with only 45 seconds
available for PCM start. The pinned reference bridge remains byte-identical;
an Omarchy wrapper adds the marker around it. The audio-specific behavioral
fault matrix passes, but this candidate has not run on hardware and is not an
acoustic pass.

The offline v60 candidate was composed on 2026-10-28 from the fresh r7
development rootfs with the radio profile, the two-phase speaker handshake and
the inert private-v3 sensor runtime in one image:

```text
out/private/myron-omarchy-main-20261028-v60-audio-cellular-sensors.img
SHA-256 3c4c62321d0cf8ea69bd44472594d59c0e178564064f58a2e42fd42623d4c3bd
```

Offline composition reported `profile=audio-cellular-bridge`,
`effective_profile=cellular`,
`activation=persistent-main-cellular-audio-experiment` and
`deployment_authorized=false`. `e2fsck -fn` passed. The exact handshake files,
packaged `hexagonrpc`/`ssccli`, private sensor registry and manual sensor tools
are present. Sensor staging and autorotation are absent from every enable path.
The image was subsequently deployed and booted. The speaker handshake was not
reached before thermal/registration failures; audible output is still unproven.
Speaker work is now parked by owner request. See [current status](STATUS.md)
for the latest hardware evidence and work boundary.

## Offline composition

Use the same explicit inputs documented in `AUDIO-EXPERIMENT.md`, changing only
the profile and output path:

```fish
tools/myron-dev-image-compose --boot-policy main \
  --profile audio-cellular-bridge \
  --base-image /abs/base.ext4 \
  --module-stage /abs/modules \
  --module-assets-archive /abs/systemd-vt-device-assets.tar.gz \
  --runtime-stage /abs/runtime \
  --runtime-manifest /abs/myron-runtime-assets.tsv \
  --bluetooth-probe /abs/probe.py \
  --speaker-reference-repo /abs/ref \
  --firstboot-conf /abs/firstboot.conf \
  --ssh-key /abs/owner.pub \
  --out /abs/myron-audio-cellular-bridge.ext4
```

Expected result includes `profile=audio-cellular-bridge`,
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

### Retiring the unused experiment for normal cellular use (2026-10-29)

On an Omarchy cellular-base boot where the audio experiment never ran, use the
repository-installed `myron-retire-audio-experiment --check` and then `--apply`.
The helper refuses active audio, consumed experiments, data mutations or a dirty
IPA guard, and backs up the marker/request before retiring them. It does not
reset the modem, forge qualification or change the recovery policy. The backup
is `/var/lib/myron-retired-audio-experiment`; the previous publisher enablement
is saved there. Do not restore the audio marker/request while data/GNSS is in
use: reverting to audio experimentation requires its original isolated startup
preconditions, not merely copying the marker back.

New images for this non-audio development phase use composer `--profile cellular`
with the private sensor archive. Restore the ordinary charging-authentication
and qualification units, let the existing qualifier pass, then use the existing
attended cellular procedure if evidence is absent. That procedure requires held
USB/Wi-Fi rescue sessions, fresh SSH proofs after activation, and a Wi-Fi-off
ordinary DNS/HTTPS proof before evidence can be recorded. Do not substitute a
bound-interface probe for that final proof. Successful execution and current
limits are recorded in STATUS.md.
