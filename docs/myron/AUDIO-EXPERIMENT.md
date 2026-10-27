<!-- SPDX-License-Identifier: MIT -->
# Myron persistent-main audio experiments

Status: implemented and tested offline only. Neither profile has been composed
into a production image, deployed, booted, or run on the POCO F8 Ultra by this
change.

These are two separate experimental profiles derived from the persistent main
boot:

* `audio-speaker` carries only the reviewed speaker experiment probe.
* `audio-microphone` carries only the bounded microphone experiment probe.

They are not production MAIN and never combine audio with cellular. The
effective init profile remains `cellular` for compatibility with the existing
main-init contract, while `/etc/omamobile/myron-audio-experiment` selects one
exact experiment. The composer disables the normal prepare, qualify, battery,
Wi-Fi-import, coexistence, cellular and cellular-publisher target links, masks
ModemManager and every legacy audio bridge, removes the old non-audible speaker
probe, and enables only the selected audio experiment. The experiment consumes
its request before its explicit radio start pulls hardware preparation in as a
dependency.

The separately gated registered-radio coexistence profile is documented in
[`AUDIO-CELLULAR-EXPERIMENT.md`](AUDIO-CELLULAR-EXPERIMENT.md). It uses a
different marker and approval boundary; neither isolated profile widens into
that experiment.

## Safety contract

Admission requires all of the following in the current boot:

1. A root-owned, private, uncommitted two-line MAIN `pending` token matching
   the kernel boot ID and runtime image ID. The generic `pending` and `success`
   formats stay backward compatible: neither gains a `kernel=` field.
2. An audio-specific four-line request matching mode, boot ID, image ID and
   the running pinned kernel. The init creates it only for an audio image.
3. No `success`, recovery latch, disarm marker, consumed request or prior probe
   marker.
4. `myron-hardware-watchdog.service` is `active/running`, with a live nonzero
   `MainPID` that never changes. This is rechecked before every hardware stage,
   readiness gate and probe.
5. Cellular is disabled, ModemManager is masked and inactive with no invocation
   or process, and neither ModemManager nor GNSS has an admission marker.

The request is atomically moved to `audio-experiment.consumed` before radio,
module, ADSP, ALSA, amplifier or capture mutation. A second service invocation
cannot replay it. Cellular evidence is removed before hardware work, and every
cellular, mobile-data, ModemManager and GNSS entry point refuses while the
audio marker exists.

The r4 mixed ModemManager + GNSS + AudioReach sequence hard-reset the phone to
fastboot. Any evidence that ModemManager or GNSS was admitted is therefore a
hard stop, even if the service is currently inactive. Do not retry in that
boot.

The staged transaction is `arm`, `mapper`, `transport`, `adsp`, `codecs`,
`devnodes`, `fastrpc`; speaker adds `speaker-dsp`. Before an opaque probe, the
runner explicitly requires a running ADSP, Q6-up evidence, the Canoe ALSA card,
physical ALSA/control/DMA nodes, the FastRPC module and a FastRPC device. The
whole service is bounded to 10 minutes, below the 20-minute MAIN guard.

## Probe bounds

Speaker uses the byte-identical public MIT Attempt 78 script vendored at
`device/myron/audio-experiment/attempt78-live-audio-speaker-probe.sh`. The
source commit, URL and SHA-256 are recorded in that directory's `README.md`.
Composition checks the pinned repository checksum and then hashes the script
back out of the image. The runner supplies exactly:

```text
CONFIRM_AUDIO_SPEAKER_PLAYBACK=PLAY-250MS-AT-MINUS-45DBFS
AUDIO_SPEAKER_INTERFACE=TDM-LPAIF-RX-PRIMARY
AUDIO_SPEAKER_AMPLIFIER_MODE=audible
AUDIO_SPEAKER_DEVICEPP_PROFILE=mbdrc
AUDIO_SPEAKER_STREAM_PROFILE=deep-buffer
```

That probe emits one 250 ms, 440 Hz tone at about -45 dBFS. `agmplay` is bounded
to 5 seconds, the outer probe to 15 seconds, PMIC temperature must remain below
70 C, TFA amplifiers are enabled only inside the transaction, and the probe's
trap plus the outer cleanup force TFA Powerdown.

Microphone reuses Attempt 78's physical built-in-mic route and control-save
logic. It captures at most one second, bounds `agmcap` to 5 seconds and the
outer probe to 10 seconds, restores all controls on every exit, and deletes the
temporary `/run` WAV and tool log. Only format, frame count, nonzero-sample
count, discard state and restore state may reach the bounded persistent log.
No recording, raw sample, peak or device-unique calibration is persisted.

Every success, failure, signal, timeout or cleanup failure attempts cleanup and
then calls `myron-main-os recover --reason ...`. That sets the MAIN recovery
latch and requests a normal reboot; the next boot selects preserved
postmarketOS. `OnFailure=myron-main-recover.service` and `ExecStopPost` cover a
runner or service-level failure. There is never a same-boot probe retry.

## Offline composition

Composition itself does not authorize deployment. Inputs are explicit; no
sibling checkout is read implicitly:

```fish
tools/myron-dev-image-compose --boot-policy main --profile audio-speaker \
  --base-image /abs/base.ext4 --module-stage /abs/modules \
  --module-assets-archive /abs/systemd-vt-device-assets.tar.gz \
  --runtime-stage /abs/runtime --runtime-manifest /abs/myron-runtime-assets.tsv \
  --bluetooth-probe /abs/probe.py --speaker-reference-repo /abs/ref \
  --firstboot-conf /abs/firstboot.conf --ssh-key /abs/owner.pub \
  --out /abs/myron-audio-speaker.ext4
```

For microphone, change only `--profile` to `audio-microphone` and the output
name. Never place both profiles in one image or boot.

Expected composer result: `profile` is the requested audio mode,
`effective_profile=cellular`, `activation=persistent-main-audio-experiment`,
and `deployment_authorized=false`. Pass means the selected probe exists in the
image, the other experiment probe is absent, the old speaker probe is absent,
ModemManager is masked, cellular services are disabled, and the main overlay
and experiment unit are present. `tests/myron-audio-experiment` verifies these
contracts with mocks; it does not compose an image or run audio.

## Approval boundary and attended result

Stop after offline composition and checksum review. Building or testing this
source does **not** approve copying an image to the phone, changing `init_boot`,
rebooting, forcing a restart, entering fastboot, flashing, or running either
probe. Before any later radio/audio boot can be approved, the owner must also
review existing read-only backup evidence for `efs`, `efs_backup`,
`modem_userdata`, `persist`, `modem_a` and `modem_b`; this experiment neither
creates nor repairs those backups. Each future boot needs separate owner
approval naming exactly one mode and the reviewed image SHA-256. The speaker
approval must additionally accept the fixed audible 250 ms / -45 dBFS
transaction; its volume and confirmation string must not be changed.

The runtime `radio-backup-verified` file is created by the one-shot runner only
to satisfy the existing radio service's internal staging contract. It is not
operator-supplied evidence and does not replace the approval prerequisite.

Expected speaker observation: exactly one short, quiet 440 Hz tone, followed by
TFA Powerdown and automatic recovery to postmarketOS. Pass only if the exact
probe reports its fixed PASS line, cleanup succeeds, and the next boot is
postmarketOS. Expected microphone result: one aggregate
`mono-s16le-48000` result with 1..48000 frames and at least one nonzero sample,
`capture_discarded=yes`, `controls_restored=yes`, then automatic recovery to
postmarketOS. Hearing audio is never a microphone pass criterion.

Stop immediately on any refusal, missing readiness gate, temperature limit,
timeout, partial stage, changed/dead guard PID, ModemManager/GNSS admission,
unexpected reboot or cleanup failure. Do not retry in the same boot. Preserve
the bounded logs, allow the recovery latch to select postmarketOS, and require
a new reviewed image/boot approval before another attempt.

Rollback is the recovery latch plus normal reboot to the already preserved
postmarketOS root; no partition restoration belongs to the experiment. If a
kernel hard reset prevents userspace recovery, the independent MAIN guard and
stale pending token select postmarketOS on the next successful boot. A hang
that also stops the kernel may still require an attended physical restart.

Residual hardware risks remain: the previously observed mixed radio/audio
hard reset may recur before userspace can log it; opaque AudioReach/TFA loaders
can hang the kernel; amplifier or routing faults can produce unexpected output
or heating; microphone controls may fail to restore after a kernel failure;
and a normal reboot request cannot recover a fully wedged kernel. No live
evidence for these new persistent-main-derived profiles exists yet. The exact
vendored speaker script creates its fixed, non-private sine-wave file under
`/tmp`; its normal and signal traps delete it, but an untrappable `SIGKILL`
could leave that approximately 96 KiB synthesized tone until `/tmp` is cleared.
