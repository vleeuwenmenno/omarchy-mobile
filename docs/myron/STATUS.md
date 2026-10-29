<!-- SPDX-License-Identifier: MIT -->
# Myron hardware status and next-work boundary

Updated 2026-10-28. This is the current handoff and priority record. Read it
before historical experiment notes, whose status headings may describe an
older phase. It summarizes evidence, not a claim that every feature works in
the current Omarchy image.

## Paused checkpoint — 2026-10-29

Development is paused at the owner's request. The phone was switched to stock
Android on slot B for personal use. Do not resume device tests, change slots,
restart services, or deploy pending code until the owner resumes this work.
Omarchy remains on slot A; no images were flashed during the Android visit.

- Owner-accepted working baseline includes sensors/compass, rotation controls,
  pocket protection, adaptive brightness, Strata replacement, and navigation.
  Latest Recents pause is 150 ms; Home/Recents/app-switch feedback uses the
  existing bounded haptic helper. These are development results, not a release.
- Settings and keyboard work is saved in source but not deployed or accepted:
  auto-show preference may be inert in Squeekboard 1.43.1; test and implement
  real behavior before presenting the toggle as functional. Keyboard theme,
  sizing, automatic app-field activation and manual tile need device checks.
- Last drift check had eight differing files from pending Settings work and
  twelve generated/private paths not checked. New missing files are not counted
  by that checker. Do not infer image parity from its count alone.
- One Hyprland texture-upload crash was recovered by restarting SDDM without a
  phone reboot. Its trigger remains unknown; preserve the private crash report.
- Next after keyboard/Settings: keyring provisioning/unlock tied safely to PIN,
  then Myron-specific fingerprint runtime/verification before PAM integration.
  Audio remains parked. True airplane/reconnect remains blocked by stock IPA.

This checkpoint includes unfinished source and accumulated owner changes so
work can resume without losing context. Private captures, credentials and
vendor firmware stay outside published commits.

## Current state and scope

- Device: POCO F8 Ultra, Myron. Kernel:
  `6.12.23-android16-5-g5a0e85dd9db0-dirty-4k`.
- Omarchy v60 was built, deployed and booted. Its original image SHA-256 is
  `3c4c62321d0cf8ea69bd44472594d59c0e178564064f58a2e42fd42623d4c3bd`.
  Mounted images naturally change; that hash identifies the deployment artifact.
- Deployment changed the rootfs file only. `boot_a` and `init_boot_a` remained
  unchanged. The previous rootfs is retained in the private v60 backup directory.
- The 2026-10-28 Omarchy sensor-only test passed, then returned to preserved
  pmOS through the existing guard at 1203 seconds (`guard-timeout`, 1200-second
  deadline). This was verified from the recovery latch and guard log.
  At that time neither the sensor foundation nor rotation started on boot;
  since 2026-10-29 both do when the image carries the private sensor assets
  (see the reproducibility section below).
- The owner subsequently requested removal of the recurring 20-minute reboot.
  An image-bound development policy is installed for v60; it disables only the
  wall-clock deadline. The guard process, failure recovery, manual recovery,
  pending-boot fallback and thermal limits remain. See
  [development timeout policy](DEVELOPMENT-GUARD.md) for deployment and reversal.
  Current verified Omarchy boot `84e10ba1-3c62-4c09-ad0b-adc353eb2b37` has the
  live untimed guard and manually started sensors. The sensor discovery wait
  fix passed fresh-boot staging; all four SensorProxy capabilities are true.
- Sensor widget 1.1.1 is deployed: two-second coarse idle snapshots and a
  top-right fast-mode icon for 60 seconds at 5 updates/second, with activity
  and lock gates. Local/on-device checks, locked refusal and unlocked 5 Hz
  output passed; stop-on-hide testing remains. Next hardware task is physical
  light/proximity response, using the same running Omarchy sensor foundation.
- Speaker output is parked by owner request. The immediate objective is a
  useful, verified non-audio baseline, beginning with sensors and rotation.
- No commit or push is implied. The checkout contains ongoing changes; preserve
  them and do not discard unrelated work.

## Evidence labels

**Working** means demonstrated in the stated environment. **Owner-confirmed**
means observed by the owner; do not invent an image or boot identity for it.
**Partial** means important functionality remains unproven. **Untested** means
presence or code exists without adequate practical evidence. **Missing/broken**
means no usable implementation or a recorded failure.

### Platform, graphics and basic input

| Feature | Evidence and remaining work |
| --- | --- |
| Kernel and Linux boot | Working: custom kernel boots pmOS and Omarchy. This is not an upstream-mainline qualification. |
| Omarchy filesystem and persistent storage | Working: native desktop, applications and large file transfers; experimental image is not a qualified daily-driver release. |
| CPU and RAM | Basic use works; dedicated memory, stress and efficiency qualification remains open. |
| Boot selection and recovery | Repeated automatic pmOS recovery demonstrated. Experimental boots remain uncommitted until their own acceptance conditions pass. |
| USB SSH | Working rescue path. A renamed host USB interface required a host-profile repair. |
| RTC/time | Partial: bootstrap plus network time works; writable wall-clock RTC remains unresolved. |
| Internal OLED / DSI | Working: native Hyprland on DSI-1 at 1200x2608. |
| Refresh rates | 60/90/120 Hz exposed; native Hyprland at 60 Hz and recovered Plasma at 120 Hz observed. Other combinations need qualification. |
| GPU / Vulkan / OpenGL / GLES / EGL | Custom Zink/Turnip Adreno 840 rendering demonstrated. Keep the established custom stack intact. |
| DMA-BUF and synchronization | Tested application/compositor paths work; comprehensive sharing/synchronization qualification is open. |
| Touchscreen | Basic physical touch works. Multitouch, edge gestures and rotated touch alignment need explicit acceptance. |
| Power/volume buttons | Reference input behavior and nodes proven; complete Omarchy action mapping remains partial. |
| Brightness and ambient control | Manual slider owner-confirmed. Bounded 3–55% automatic control deployed on Omarchy; real 6.4-lux reading drove a gradual 3% to 5.6% ramp. Dark-panel ambient claims time out, so wake uses a safe 3% fallback; fresh wake samples cap at 15%. See [display policy](DISPLAY-POWER.md). |
| Screen-off/wake and PIN lock | Owner confirmed dark-screen taps/swipes stay dark and power wakes. Power-only wake policy installed; software wake rejected while dark. Secure PIN lock retained in live tests. Long-duration drain and suspend remain open. |
| Rounded corners/cutout layout | Safe-area changes implemented; final visual acceptance across orientations remains open. |
| External DisplayPort | Connector present; actual display output untested. |

### Sensors, lighting and feedback

| Feature | Evidence and remaining work |
| --- | --- |
| Accelerometer | Omarchy sensor-only startup and stage passed with 324 physical samples. Owner confirmed corrected portrait orientation after the Myron mount-matrix fix. |
| Gyroscope | Physical samples demonstrated on pmOS; Omarchy/application path remains open. |
| Magnetometer/compass | OWNER-ACCEPTED on 2026-10-28 for the current Omarchy development baseline. Dial and turn direction work. Known limits retained: +17° to +30° difference from magnetic-reference iPhone and +8° return difference in the desk comparison. No offset applied. Further accuracy investigation is parked; this is not precision-navigation qualification. |
| Proximity | Omarchy physical test passed on 2026-10-28: owner covered/uncovered the upper front; a bounded proximity-only monitor recorded Far → Near → Far. Application/call behavior is not yet qualified. |
| Ambient light | Real Omarchy readings drive bounded automatic brightness. Pre-wake claims while dark time out; minimum-brightness fallback is active. Physical cover/uncover and both adjustment directions still need observation. |
| Other sensor algorithms / SAR | Configuration exists; no functional qualification. |
| Omarchy sensor foundation | Manual guarded mapper/FastRPC/ADSP startup passed without audio activation. Boot start (bounded 60 s FastRPC wait) is enabled by the composer with the private assets and installed on the phone; first reboot acceptance is pending. |
| SensorProxy startup | Fixed inactive-service startup and Myron's missing SSC accelerometer/proximity udev types; all three capabilities now true on the tested Omarchy boot. |
| Autorotation and rotation lock | Client prepared; display/touch transform and lock behavior require attended Omarchy tests. |
| Torch and intensity slider | Owner reports torch operation and confirms intensity adjustment worked. Do not repeat solely to rediscover that result. |
| Haptics | Owner-confirmed 80 ms low-strength vibration on Omarchy (2026-10-29). Driver power-disable warning and recurring UI integration remain open. |

### Connectivity and location

| Feature | Evidence and remaining work |
| --- | --- |
| Wi-Fi scan/association/internet | Demonstrated; latest association was inconsistent. Correct secret was copied from the host, but causality of failures is not established. |
| Wi-Fi reconnect and persistence | Partial; reproducible automatic connection needs attention. |
| Wi-Fi SSH | Worked earlier; latest office-network attempt failed. An IPv4 address alone does not prove a rescue connection. |
| SIM and LTE/5G registration | Working in repeated tests. A 5G icon is not proof of a usable data bearer. |
| Mobile internet | Bounded real HTTPS/transfers passed previously on Omarchy. |
| Mobile-data toggle/state | Owner reported inconsistent state and failed toggles; final acceptance remains open. |
| Mobile-data reconnect | Known unsafe stock IPA reopen behavior; do not repeatedly cycle the bearer to test a UI. |
| GPS/GNSS | Real satellite fixes demonstrated, including on Omarchy. Map accuracy alone is not the evidence. |
| Location permissions | Off must block applications, On must allow access, In use must reflect activity. Complete acceptance remains open. |
| Location history/details | Implemented in the repository 2026-10-29 (`omamobile-location-usage`, `LocationPanel.qml`), NOT deployed or Omarchy-tested yet. Tile: Off / On / In use / Receiver on; chevron or long-press opens the panel. See the location-use section below. |
| Bluetooth controller | Firmware initialization and powered controller demonstrated. |
| Bluetooth discovery/pairing/reconnect | Broken or unqualified; scans timed out or found no expected devices. |
| Airplane mode / SIM PIN | Untested end to end. |
| SMS/MMS and voice calls | SMS/calls not implemented; MMS not established. Call audio is separate work. |
| Hotspot/tethering | Untested. |
| NFC | No usable device/integration established. |

### Audio (parked)

| Feature | Evidence and remaining work |
| --- | --- |
| Speakers | Earlier attended output was audible. Current Omarchy radio/audio integration has not reproduced it reliably. |
| Application playback | Documented in pmOS; current Omarchy application path unqualified. |
| AudioReach foundation | Earlier checkpoints reached DSP, codecs, ALSA and FastRPC; combined startup and cleanup remain incomplete. |
| v60 FIFO handshake | Local test passed; hardware playback path not reached in the recent thermal-refused attempts. FIFO backpressure is a hypothesis, not a proven root cause. |
| Built-in microphone | Raw nonzero capture demonstrated; intelligible speech and usable levels unproven. |
| Application capture / full duplex | Selectable source, mute, stop/reopen and simultaneous playback/capture remain open. |
| Routing / earpiece / headsets | Incomplete or untested. Bluetooth audio awaits discovery/pairing. |
| Audio with data/GPS | Unqualified; previous combined sequences caused serious failures. |

Recent v60 evidence: the first attempt stopped at a reported maximum 95000 mC
during registration settling. The second reached transport, stopped at 95300 mC,
and reported cleanup failure. Both recovered to pmOS before speaker playback.
The logs did not name the hottest sensor; do not attribute heating to graphics
or audio without additional evidence. The third observed boot had no audio
service invocation before the work was parked. Sensor tests must not silently
resume that experiment.

### Power, USB, cameras and biometrics

| Feature | Evidence and remaining work |
| --- | --- |
| Battery reporting | Capacity, temperature, voltage and current available. |
| Charging / authentication | Working in Omarchy; around 45 W measured on pmOS only. |
| USB-C power detection | USB-PD presence/readings demonstrated. |
| Thermal monitoring | Gates operate; named-source diagnosis and sustained behavior remain open. |
| CPU/GPU scaling | Not comprehensively qualified. |
| Suspend/resume, deep sleep, screen-off drain | Untested; advertised kernel modes do not establish reliability. |
| Wake sources | Power/touch/charger/incoming-event matrix untested. |
| USB dongle | Owner reports basic use appeared to work; type/functions unspecified. Further qualification is lowest priority. |
| USB audio/storage/input, role changes, reconnect | Individual functions and repeated transitions not yet qualified. |
| Camera plumbing | Request/sync and subdevices seen earlier; no working frame capture established. |
| Front/rear photos, video, autofocus | Missing or untested pending a usable capture pipeline. |
| Fingerprint integration/enrollment/unlock | Missing; enrollment is a higher priority than further dongle checks. |

## Priorities and first goal

1. Finish the smallest sensor-readiness fix, then isolate Omarchy ADSP/FastRPC
   startup from speaker activation. Prove physical samples before rotation.
2. Qualify rotation/touch/lock, proximity and light behavior; check haptics when
   a bounded existing driver path is available.
3. Fix data/location state and policy behavior, Wi-Fi reliability, and basic
   lock/power/thermal issues. Keep unsafe bearer reconnect outside routine UI tests.
4. Investigate fingerprint enrollment and cameras as separate larger tasks.
   Bluetooth, telephony and NFC remain explicit backlog items, not assumed wins.
5. Further USB/dongle checks are last. Speaker output and brightness-slider
   polish stay deferred until the owner changes their priority.

The first bounded goal is documentation plus one justified, reversible sensor
integration fix with targeted verification. It does not claim the full hardware
suite is complete or imply unattended work after the agent stops.

### First milestone result (2026-10-28)

- Fixed the sensor stage's inactive-proxy case: `restart` replaces
  `try-restart`, and a failed restart now stops staging with an explicit error.
  Removed the unit's proxy ordering because the stage manages that restart
  synchronously after registry loading.
- Practical check on the existing pmOS boot reproduced the distinction:
  initially inactive, still inactive after `try-restart`, active after
  `restart`. Cleanup exceeded pmOS's existing 3-second stop timeout; systemd
  killed the process. After recording that failure, `reset-failed` restored
  `ActiveState=inactive`, `SubState=dead`, `MainPID=0`. The boot ID was unchanged.
- The active proxy reported all three capabilities false: accelerometer,
  ambient light and proximity. This proves service startup behavior only,
  not working sensors or successful registry staging on this boot.
  The proxy's stop-timeout behavior also needs attention before relying on
  repeated registry/proxy refreshes; it was not retried or hidden by rebooting.
- `tests/myron-sensors` passed, including the HexagonRPC package safety check.
  No reboot, image rebuild, deployment, audio activation or persistent phone
  configuration change was needed. The helper fix is in the repository and
  has not yet been deployed to Omarchy.

The subsequent Omarchy-only attempt established independent ADSP/FastRPC and
passed sensor staging. See [the hardware result](SENSORS.md#omarchy-hardware-result-2026-10-28).
The generic Sensors widget is installed below the home clock. The owner signed
off the compass as acceptable on 2026-10-28 with its measured limits retained.
Light/proximity response and display/touch rotation acceptance remain open.
The sensor foundation remains manual; do not assume it starts on a new boot.
The second Omarchy sensor boot also passed accelerometer staging. A subsequent
proxy refresh exposed all four feeds; the stage's refresh now follows its
hardware sample to address the observed discovery timing. That final ordering
change, together with the bounded discovery wait, subsequently passed the
fresh-boot acceptance recorded above.

## Display power follow-up (2026-10-28)

Owner confirmed automatic brightness is visibly adjusting at wake. After the
faster-response refinement and above-80% red warning, the owner reported
“This is 10x better!” Preserve that tuning as the accepted usability baseline. A follow-up
initially reduced ramp writes to 100 ms steps and refreshed the visible
quick-settings slider every 500 ms. The subsequent adaptive policy uses 20 ms
bounded steps, faster response to large recent light changes, and gentle
response to small changes. Covered-sensor minimum remains unconfirmed; the
latest attempted capture was in manual mode, then panel-off.

Owner-confirmed accidental touch wake is blocked. Only power-button wake is
allowed for now; pocket-safe double-tap wake is deferred behind broader hardware
support. [Display policy and recovery](DISPLAY-POWER.md) records the backed-up
live deployment, bounded automatic brightness, real ramp measurement and the
sensor pre-wake timeout. No reboot or sensor-foundation restart was needed.
Do not equate panel-off with suspend or proven battery savings.

## Rules and explicit barrier

**Acceptance tests must run in Omarchy.** pmOS results are historical reference
or recovery evidence, not proof that the Omarchy implementation works. Confirm
the running OS before testing; a successful pmOS check cannot close an Omarchy
hardware or integration task.

The authoritative workflow rules are [AGENTS.md](../../AGENTS.md#myron-owner-workflow-rules-2026-10-28):
minimize reboots; inspect before reapplying; reuse existing authorization; test
only what changes the next decision; investigate failures before retrying.

Within the current work: read-only inspection, repository fixes, backed-up
targeted updates and bounded non-audio tests are authorized. Announce visible
changes before running them. Preserve the reference GPU stack and existing
working paths. Prefer the current boot when it supports the test.

**Stop before crossing these boundaries:**

- No speaker/audio experiment restart, unsolicited gain changes or mixed
  audio/GNSS/data trial while audio is parked.
- No new partition flash, slot change, calibration/secure-storage write, OS
  upgrade or repository push under this goal. Those require specific scope.
- No thermal-limit increase, removal of required recovery guards, unsafe
  same-boot retry or unreviewed DSP restart/module unload to force a pass.
  The owner's explicit development wall-clock timeout exception above does
  not authorize removing the recovery service or hardware safeguards.
- Sensor registry staging requires an available ADSP/FastRPC foundation. If
  absent, record that prerequisite and implement its independent path; do not
  start the complete speaker/audio stack merely to make sensors appear.
- Do not enable persistent rotation before physical display/touch alignment
  passes. Stop on lost SSH, firmware/kernel errors or a safety refusal; preserve
  evidence and use the existing recovery path where needed.

A checkbox requires the right evidence: real sample for a sensor, physical
observation for a user-visible effect, and a later deliberate boot test for a
persistence claim. Offline tests and capabilities alone do not qualify hardware.

## References

- [Hardware matrix](HARDWARE-MATRIX.md): historical reference and Omarchy deltas.
- [Sensors](SENSORS.md): private asset hashes, package details and test procedure.
- [Cellular/audio experiments](AUDIO-CELLULAR-EXPERIMENT.md): preserved evidence.
- [Main OS](MAIN-OS.md): boot/recovery mechanism.
- [Device notes](../../device/myron/NOTES.md): dated findings and owner reports.

### Current next action: autorotation (2026-10-29)

Pocket protection behavior and its Omarchy-style visual update are accepted.
Continuous proximity, compass and light claims are running; the initial Light
claim now waits for a normally lit panel rather than repeatedly timing out in
the dark. Battery cost and off-screen measurement accuracy remain open.

Autorotation is the next hardware task. The existing service remains disabled.
Prepare a bounded, attended Omarchy test with independent restoration of the
captured monitor and touch configuration. Preserve mode, refresh, position and
scale; do not claim rotation success after failed compositor commands. Enable
persistently only after physical display/touch alignment passes.

### Pocket protection accepted (2026-10-28)

Owner confirmed the requested behavior works as expected on Omarchy. The
capture shows Near while dark, a guarded wake with approximately five-second
automatic blanking, a second guarded wake dismissed by swipe, and an unguarded
Far wake. This supersedes the pending pocket acceptance notes above. Keep the
power-only wake policy and accepted brightness behavior. Do not repeat this
physical qualification without a relevant change or regression. Continuous
sensor battery cost and across-boot foundation startup remain open; retained
claims alone do not prove off-screen measurement accuracy.

Autorotation first bounded trial completed on the existing Omarchy boot:
landscape monitor/touch transform 1 applied while preserving 120 Hz/scale 2,
then independently restored portrait and original touch mapping on timeout.
Physical direction/tap-alignment feedback remains pending. Production service
stays disabled; no persistent autorotation qualification is claimed yet.

Owner accepted basic autorotation direction and touch alignment on 2026-10-29.
Requested refinement: 700 ms settling plus hold orientation while flat or tilt
uncertain. Candidate and focused checks are ready; bounded r3 physical test is
in progress. Production autorotation is still disabled pending refinement
acceptance and normal-session lifecycle integration.

### Rotation controls update (2026-10-29)

Owner accepted basic rotation and touch alignment on Omarchy. Current work adds
700 ms settling, flat-device hold, a current-rotation lock with direction
preferences, and a fading one-shot suggestion. Controls are deployed for a
180-second supervised test; physical acceptance is pending. Permanent
rotation remains disabled, and polling efficiency needs improvement before
activation. See the rotation controls trial in SENSORS.md for backups and stop.

### Reproducibility: repository is the source of truth (2026-10-29)

Owner request: everything working on the phone must come from the repository,
so a newly composed image reproduces it. A read-only comparison of the phone
against the repository found only that session's pending UI and rotation work
outside it, plus user-level overrides. The rest was expected: private
composer inputs, Omarchy patch results and per-device keys.

- `tools/myron-drift-check` hashes the phone's shell tree, our programs and
  units, the Myron overlays' paths and the sensor controller against their
  repository sources and lists user-level overrides (plugin copies, regular
  units in `~/.config/systemd/user`). It is read-only.
- The composer enables `myron-sensor-stage.service` (multi-user) and
  `omamobile-autorotate.service` (graphical session) and writes the enable
  marker only when `--sensor-runtime-archive` supplies the private assets.
  Without them, it verifies that all three are absent. It also verifies the
  rotation plugin files and `SliderRow.qml` against the repository.
- The phone was brought to the same state from repository files with sudo,
  backed up under `/var/lib/myron-repo-sync-before-20261029` (`new-files`
  lists additions). The user-level plugin copies and the trial
  `myron-autorotate.service` were retired to the home trial directories. The
  drift check then reported 0 drifted files and no overrides.
- Pending: one reboot to accept unattended sensor staging and the rotation
  controller at boot. The sensor home widget and its home-screen placement
  are still per-user state in `~/.config/omamobile`, not image defaults.

### Feature completion rule and connectivity audit (2026-10-29)

AGENTS.md now requires repository/package/composer parity and a post-deployment
drift check for every feature, including units and user migrations. Today's
read-only comparison reports zero drifted files and 13 paths without a mapped
repository source; those paths are not verified by that result. The interrupted
background checks finished: myron-hardware-test and myron-main both returned 0.

On the same Omarchy boot, myron-cellular, ModemManager, NetworkManager, the IPA
guard and hardware watchdog are active. The modem is powered on, registered at
home on LTE/5G, packet-service attached, signal quality 54%; Wi-Fi is connected.
No radio restart was needed. Registration is not a mobile-internet result.

Mobile-data and location helpers explicitly refuse activation because the image
still has the audio-cellular-bridge experiment marker. Audio experiment and
speaker bridge services are inactive. Do not silently delete this marker to
bypass the profile safety contract: normal cellular operation additionally
requires a qualified committed main boot and current attended evidence. GeoClue
is inactive; Bluetooth has no controller. These are not all-reactivated results.
Transitioning out of the parked audio profile is the next connectivity task.

Next independent small hardware feature selected: haptic feedback. The current
Omarchy kernel exposes qcom-hv-haptics on event1. Begin with its force-feedback
capabilities and a bounded, announced low-intensity pulse, then owner acceptance;
do not load audio or change calibration for this task.

### Retiring the parked audio profile (2026-10-29)

The repository helper `myron-retire-audio-experiment --check|--apply` verifies
inactive audio services, no consumed experiment, no data mutation and a pristine
IPA guard, then backs up and retires the audio marker/request. It enables the
normal cellular status publisher without restarting ModemManager. Applied on
the existing Omarchy boot; backup: `/var/lib/myron-retired-audio-experiment`.
The mobile-data helper now reports `Needs attended setup`, not audio blocked.
Location permission was enabled through `omamobile-gnss on`; the receiver stays
idle until an application requests it. This is not a new satellite-fix result.

Reproduction uses the existing composer `--profile cellular` with the same
private sensor assets. Normal battery authentication and boot qualification
were restored with `systemctl enable myron-batterysecret.service
myron-omarchy-qualify.service`, then authentication started and qualification
requested. Their previous enablement is recorded in the backup directory.
The current boot was pending, with no saved cellular evidence. Data activation
must use the existing attended operation after qualification; never fabricate
success/evidence or bypass the IPA guard. Audio and Bluetooth remain parked.

Connectivity restoration completed on the same boot (no reboot): normal boot
qualification passed and committed the current main boot. Charging authentication
is active. The first data preflight refused before mutation because the launch
SSH closed before the USB rescue snapshot; holding USB and Wi-Fi rescue sessions
resolved that preflight condition. The next attempt connected once and sealed
with fresh authenticated USB and Wi-Fi proofs. A bounded Wi-Fi-off test, with
an independent 60-second restore timer, proved ordinary DNS and unbound HTTPS
used cellular (HTTP 204, TX +15 / RX +7). Attended evidence was recorded and
validated. Wi-Fi was restored; fresh SSH works over USB and Wi-Fi. The helper
reports data=on, and NetworkManager reports GSM connected. Location permission
is on, receiver idle awaiting an app. Satellite fix not retested. Bluetooth
and audio remain parked. Do not cycle the live data bearer: current policy
requires a reboot after data loss rather than a same-boot reconnect.

### First bounded haptics probe (2026-10-29)

On the existing Omarchy boot, qcom-hv-haptics exposes writable evdev force
feedback. Repository tools `build-myron-haptic-probe` and
`myron-haptic-probe.c` build a fixed 80 ms, 4096/32767 FF_CONSTANT pulse,
validate the device name/capability and stop/erase the effect afterward.
No global gain, calibration, driver loading or production UI change is made.
The isolated executable/source are staged in the user's home for this trial.

Initial FF_RUMBLE upload was rejected with EINVAL / "Only support custom
waveforms"; no pulse was played. After inspecting Qualcomm's reference driver,
FF_CONSTANT upload/play/stop/erase succeeded. Kernel logs show play=1,
automatic stop at 80 ms, then explicit stop/erase and "stopped play completely".
They also show "poll HPWR_DISABLED failed after stopped play" followed by
module disable/enable; this warning needs diagnosis before recurring UI use.
Physical sensation is awaiting owner confirmation. Cellular data remains on.

Reference source (not a claim of an exact match to the running vendor module):
https://android.googlesource.com/kernel/msm.git/+/9671bc00773d7f73172f1cf38a7cd638091d0214/drivers/input/misc/qcom-hv-haptics.c

Haptics physical acceptance: after the owner held the phone and replied ready,
one repeat of the same 80 ms, 4096/32767 FF_CONSTANT probe completed with stop
and erase successful. The owner confirmed feeling it. Basic vibration is now
owner-confirmed on Omarchy; recurring UI feedback remains unqualified pending
the observed power-disable timeout investigation.

### Quick-settings haptic feedback integration (2026-10-29)

Quick-setting tile taps and the brightness Auto/Manual icon now request a short
35 ms pulse at 4096/32767 strength. Expanded quick settings has a persistent
Touch feedback switch. This first integration does not cover application,
keyboard or PIN interactions. It is interaction feedback, not proof that an
asynchronous setting change succeeded.

`omamobile-haptics` discovers qcom-hv-haptics by name rather than event number,
uses the verified FF_CONSTANT ABI, checks panel/lock/pocket state, serializes
pulses, limits them to one per 300 ms and at most six per ten seconds, and
stops/erases effects. Unsupported devices remain unavailable. There is no
background haptic service or polling loop. The generic package installer and
Myron composer install the helper. QML reuses the existing rotation SwitchRow.

Three focused disabled/locked/burst-limit tests passed; QML parsed. On Omarchy,
the deployed 35 ms pulse generated one playback followed by clean stops, with
no HPWR_DISABLED warning in that check. A pulse request while disabled produced
no second playback; feedback was then re-enabled. Shell loaded without reported
QML type/reference errors. Owner acceptance of quick-setting tap feel is pending.
Drift check: zero mapped-file differences, 12 private/generated paths unchecked.
Backup: `/var/lib/myron-ui-haptics-before-20261029/QuickSettings.qml`. To disable,
use the Touch feedback switch or `omamobile-haptics off`; to roll back, restore
that QML, remove the newly added `/usr/bin/omamobile-haptics`, and reload shell
while unlocked. The private user opt-out file is `~/.local/state/omamobile/haptics-disabled`.

### Finger-following quick-settings pull (2026-10-29)

The status-bar pull now shares continuous drag distance through the packaged
omamobile.gestures QML singleton. Quick settings follows that distance without
an animation while dragging, then animates to open on release. The bottom
handle changes sheet height directly using global pointer coordinates; the
handle remains anchored to the moving edge. Release settles to full or compact
according to pull direction, and tapping still toggles. Expansion reveals
clipped full content rather than waiting for a gesture threshold. Upward sheet
dismiss uses global coordinates and animates its offset back when canceled.

QML parsing passed. On Omarchy, a controlled 80-pixel handle displacement
changed sheet height from 403 to 483 pixels; release reached the full 747-pixel
height. No QML reference/type/binding-loop errors were observed. Physical touch
acceptance of the bar-to-panel grab and handle feel is pending. Sources,
composer copies and the existing setup-user link loop include the shared module.
Drift check reports zero differences (12 unmapped private/generated files).
Backups: `/var/lib/myron-qs-drag-before-20261029/{Bar,QuickSettings}.qml`.
Restore those two files and reload while unlocked to roll back; the shared
module can then be removed from the installed tree and user plugin links.

Handle follow-up: owner accepted finger tracking but reported an abrupt content
swap on compact-handle taps and inability to drag the handle upward to dismiss.
The handle now consumes height down to compact, then translates the whole sheet
up; releasing an upward compact pull dismisses through the host. Tap/resize
transitions crossfade a one-shot snapshot of the preceding layout while height
animates (the snapshot is not continuously rendered). Live Omarchy geometry
verified an 80-pixel upward compact pull moved y=93 to y=13, and release set
opened=false with the sheet fully above screen. QML error check was clean;
visual tap-transition acceptance is pending. Zero repo/phone drift remains.

## Touch feedback tile placement (2026-10-29)

Removed the standalone Touch feedback switch from QuickSettings. It is now a
normal editable tile, first on page two in the default layout. Version 1 saved
layouts gain the tile after their first eight entries (short layouts append it,
empty layouts stay empty); version 2 saves preserve hiding and reordering.
The existing haptic helper and pulse safeguards are unchanged.

Focused tile-model checks and QML parsing passed. Removed the obsolete static
handle-threshold assertion: the accepted continuous-drag implementation no
longer uses that threshold gesture. On the existing unlocked Omarchy v60 boot,
the shell reloaded successfully; the tile reported available/On, standard
layout removal/restoration passed, and toggling Off then On passed. Left page
two open, feedback enabled, and the migrated layout saved. No reboot.

Rollback copies of QuickSettings.qml, TilesModel.js and the previous user
quicksettings.json are in /var/lib/myron-touch-tile-before-20261029. Restore
those files to their original paths and reload the shell while unlocked.
The package installer and image composer already include both changed source
files. Drift check: 0 mismatches, 12 private/generated files unchecked; no fresh
boot acceptance claimed. User layout remains per-user state.

## Connectivity acceptance and remaining boundary (2026-10-29)

Owner selected connectivity next, then fingerprint enrollment/verification and
PAM/sudo integration with password fallback. Camera work follows fingerprint.
No fingerprint or PAM changes have been made in this phase.

On the same Omarchy v60 boot, tested the actual quick-settings toggle handlers
while unlocked, not only the helper scripts:

- Mobile data Off activated the existing packet gate and a cellular-interface-
  bound HTTPS request timed out. On removed the gate and the same request
  returned HTTP 204. Independent root timer and an exit trap restored On on
  failure. USB and Wi-Fi remained available; no bearer teardown occurred.
- The isolated helper check also recorded five dropped packets in the egress
  filter, then HTTP 204 after restoration. An earlier invalid run overlapped
  an old restore timer: the journal proved that timer removed the gate during
  the request. That run is not evidence of a filter failure.
- Location Off removed permission, rejected an application GetClient request
  through D-Bus activation, and left GeoClue/GNSS inactive. On restored the
  permission marker. The UI test repeated this successfully. Location and
  mobile data were left On. No new satellite-fix claim is made.
- Direct SSH invocation of the packet gate was denied by the intended
  active-local-session polkit rule; the shell's own UI action succeeded.
  No authorization rules were broadened.

These tests validate packet-level Off/On, not modem power-off or reconnect.
The exact stock IPA lifecycle defect is documented in the sibling repository
`myron-postmarketos/docs/ATTEMPT_69_RADIOS_AND_TIME.md`: `ipa3_wwan_stop`
omits `napi_disable`, and a later `ipa3_wwan_open` panics in `napi_enable`.
Keep true reconnect and airplane mode blocked pending a compatible driver fix;
do not replace the radio shutdown with a misleading packet-only airplane mode.

Location app/process history is still missing. The tile currently infers In use
from enabled GPS sources, which does not cover every GeoClue location source.
GeoClue 2.8.2 protects individual client properties from other callers, and its
Manager.InUse excludes configured system components. Authorization callbacks
also skip some allowed applications. A complete usage view must account for
these contracts instead of labelling permission grants or process presence as
actual use. No coordinates were collected in this investigation.

### Direct ModemManager bypass restricted (2026-10-29)

Live authorization checks against the actual quickshell process confirmed that
stock policy allowed both ModemManager Location and Device.Control. Added
`49-myron-modem-access.rules` to the Myron main overlay: non-root/non-geoclue
callers are denied those two actions. Exact systemd-unit grants for the shell
remain unchanged. NetworkManager and bounded root helpers keep their existing
access; GeoClue keeps its vendor grant. Direct SIM PIN/PUK, register/scan and
other Device.Control operations from user applications now also require a
bounded privileged integration; those are not implemented on Myron today.

Focused runtime-toggle tests and independent review passed. The composer now
includes ownership/mode checks and byte-identical verification of the new rule.
On Omarchy, both quickshell authorization checks changed to denied. Cellular
HTTPS still returned 204. A controlled GeoClue client was accepted, enabled the
GNSS receiver, then stopped normally. No modem restart, bearer reset or reboot.
Drift: zero compared-file differences, 12 private/generated files unchecked.

Rollback: remove /etc/polkit-1/rules.d/49-myron-modem-access.rules (it was absent
before this update); polkit reloads rules automatically. Prior-state record and
unchanged location-unit grant backup are in
/var/lib/myron-location-access-before-20261029. No fresh-image boot test claimed.

The scout's concern about a missing GeoClue agent does not apply to this live
session: the desktop-autostart agent is active. Source-only findings must not
be treated as device evidence. A controlled coarse-accuracy client proved the
real status bug: Active=true while the existing GNSS-based tile would show On.
A separate connection received DesktopId and Active=true/false broadcasts.
An observer needs caller identity and crash cleanup, not only these signals,
to provide accurate private per-user history. Implemented below; not deployed yet.

### Location-use history and panel (implemented 2026-10-29, not deployed)

New package `packages/omamobile-location-usage` (generic: any GeoClue device).
Checks so far are repository tests only (model, daemon on a private bus against
a fake GeoClue, QML parse, JS model). Omarchy acceptance on the phone is open.

- Service `omamobile-location-usage.service` (root, `Before=geoclue.service`,
  enabled by the composer/rootfs, no activation file, no polkit grant, empty
  capability set). Two bus connections: a bus monitor with only four rules
  (GeoClue Client `Start` method calls, method returns sent by GeoClue, and
  the Client and Manager `PropertiesChanged` signals; arg0 rules exclude the
  Location objects) and an ordinary one that owns `org.omamobile.LocationUsage1`,
  reads caller credentials and watches names. It never calls GeoClue except one
  `NO_AUTO_START` `Manager.InUse` read when GeoClue already runs at startup.
  There is no `Stop` rule: `Active=false` is the proof a use ended.
- Use means `Active=true` from the verified GeoClue owner **and** a successful
  `Start`. GeoClue's method wrapper refuses a caller that does not own the
  client path, but the monitor still sees that attempt, so a `Start` call proves
  only who asked. The model keeps each call as an outstanding attempt keyed by
  (sender, serial) and promotes it only when an empty-signature method return
  from GeoClue's current unique owner answers exactly that sender and serial
  (GeoClue answers non-owners with an error, which is never matched). That
  proves the sender owns that path; the owner is then remembered per client
  path (bounded, cleared on GeoClue owner change, owner exit or events lost) so
  `Active=true` is credited to it in either order of reply and signal, and a
  restart GeoClue performs itself (agent policy) keeps its owner. A denied or
  racing `Start` is never promoted, cannot replace the owner and cannot end a
  use. A duplicate (sender, serial) is ambiguous and trusted for neither.
  Client exit without `Active=false`, `Active=false`, GeoClue restart or exit
  close entries.
- Method returns: a bus rule cannot match `reply_serial`, so the monitor
  connection receives every method return GeoClue sends, including responses
  that may carry a body (for example a Location property read). The filter
  reads headers only (type, sender, destination, reply serial, signature),
  never calls `get_body` on them, never stores or logs a message and discards
  everything except an empty-signature reply that answers an outstanding
  `Start`. GDBus decodes messages in memory before the filter runs; the
  service simply never looks at those bodies. No Location subscription, no
  `GetLocation`, no coordinates stored.
- Honest degradation: the event queue is bounded (512); an overflow, an
  unreadable message or a failed dispatch ends open uses as `events-lost`
  (unknown end), forgets attempts in flight and marks coverage `partial`. The
  attempt, owner, awaiting-reply and unclaimed-use tables are bounded; hitting a
  limit, or an `Active=true` that no successful `Start` claimed within 30 s,
  marks coverage `partial` (a sticky warning until GeoClue restarts, with no
  per-user count: `unknown_active` is gone from the API). If either bus
  connection closes the service stops claiming to monitor (`monitoring`
  `stopped`), closes open uses and exits non-zero so `Restart=on-failure`
  restarts it.
- History: `/var/lib/omamobile-location-usage/history.json`, root 0600 in a 0700
  directory; 7 days, 50 per user; no coordinates, command lines or environment.
  Pruning by age is skipped while the clock is before 2026-01-01 (no RTC yet).
- API (system bus, methods without arguments): `GetStatus`, `GetHistory`,
  `ClearHistory`; each answers only for the caller's own UID. CLI
  `omamobile-location status|history|clear` prints JSON.
- Tile: Off = no permission; On = allowed; In use = a known active client or
  GeoClue's `InUse`; Receiver on = receiver runs but the observer is absent or
  partial. Toggling no longer flips the tile first and reports Failed.
- Limits: app names are self-reported labels; process name is `comm` of the
  bus-reported PID only when `/proc` agrees on the UID. Coverage is `partial`
  when GeoClue already ran at monitor start (earlier clients are unseen) until
  GeoClue restarts. Clients that address GeoClue by unique name are handled; a
  client that disappears from the bus before credentials are read is
  unattributed. A client path GeoClue restarts on its own after its owner entry
  was evicted from the bounded owner table (128 paths) is unattributed. An
  attacker flooding the bounded attempt table from many connections can cause
  missed attribution, never misattribution; coverage then reads `partial`.
- Deploy: install the package files (composer lists them; drift-check maps
  them), `systemctl enable --now omamobile-location-usage.service`, restart
  quickshell for the new panel. Rollback: `systemctl disable --now` the unit,
  remove the files; the tile then shows On/Receiver on from permission and
  receiver state only. History file may be deleted at any time.

### Location history deployed: backend accepted, panel reload pending (2026-10-29)

Installed the location-use observer and shell 0.2.23 panel sources on the
existing Omarchy v60 boot. The service is active under its packaged sandbox,
with zero restarts. Starting it did not activate GeoClue. A real coarse
GeoClue request was attributed to the requesting session process only after
successful Start and Active; Stop and process exit without Stop both closed
its entries. A root API request returned no session-user entries. The stored
history is root-owned 0600 inside a root-owned 0700 directory. No coordinates
were requested or recorded. Focused checks: 47 model tests, 27 private-bus
tests, package staging/unit/policy checks, nine UI-model checks and QML parsing.

The three shell files are installed, but the running shell has not been
restarted because the phone is locked. Physical panel acceptance remains
pending an unlocked reload. Two synthetic Firefox-labelled Python client
entries were retained for that check; their process identity distinguishes
them from actual browser use. Do not claim the panel is live yet.

Backup: /var/lib/myron-location-usage-before-20261029. records.json lists
previously present files and newly installed files; files/ holds prior copies.
The old shell version marker is separately saved as shell-version. Rollback:
disable/stop omamobile-location-usage.service, restore recorded prior files,
remove recorded new files and its enable symlink, restore shell-version,
reload systemd and D-Bus policy, then reload the shell while unlocked. Preserve
or explicitly clear private history separately; it is never a repository input.
No reboot, modem restart or bearer reset was performed.

### Location panel loaded and live state verified (2026-10-29)

Resumed after the provider interruption. Confirmed Omarchy, unlocked session,
observer active with zero restarts, then reloaded the shell once. Opened the
Location details page through the quick-settings entry point. A controlled
coarse client changed panel status to In use with one active entry; after Stop,
the panel returned to On, zero active entries, and three recent entries.
The three Firefox-labelled Python diagnostic entries are not actual Firefox
activity. They remain visible for inspection and can be removed using Clear
history. No coordinates were read or recorded by this test.

A private screenshot confirmed the panel renders below the top bar, with
recent entries, process labels, footer and Clear history visible. Screenshot:
`out/private/myron-location-usage-20261029/panel.png` (not a shipping input).
Drift check still reports zero compared-file differences, 12 private/generated
files unchecked. No new deployment or backend restart was needed. The panel
is now live; owner touch/real-app acceptance remains outstanding.

### Location owner acceptance and next work (2026-10-29)

Owner confirmed the live Location panel works. Next authorized order is to
unify the mobile-data helper with the accepted packet-only tile behavior,
then bring up Myron fingerprint enrollment/verification, followed by PAM/sudo
with password fallback. No fingerprint authentication rule is installed yet.

Initial read-only Omarchy fingerprint inventory found device-tree nodes
`fingerprint-screen`, `qcom,qbt_handler`, and `xiaomi_fingerprint`. The Xiaomi
node (`xiaomi,xiaomi-fp`, status=ok) is bound to `xiaomi-fp`, whose module link
points to `mi_fp`. The Qualcomm qbt-handler platform node is unbound.
A broader name check confirmed `/dev/mifp_id` (491:1), `/dev/qbt_ipc`
(491:2), and `/dev/smcinvoke`; `mi_fp` is loaded (53248 bytes, refcount 0).
`xiaomi_fp` is a sysfs class, not a /dev node. The first narrow name search
missed these paths and `mi_fp`. Do not infer that absent names in lsmod mean a built-in driver.
No fprintd/libfprint/fingerprint package is installed. The current sudo PAM
file still includes system-auth. The repository's existing fingerprint package
is explicitly for Pixel 7 Pro and is not evidence of a working Myron stack.
No device node was opened, and no secure-world, enrollment, module-load or
calibration operation was performed. Sensor enrollment remains unproven.

### Mobile-data helper/tile unified and deployed (2026-10-29)

`myron-mobile-data` now owns state and packet-only Off/On semantics. Tile action
and state scripts delegate without their own policy overlay. Gate transition,
failed/unknown service, stale gate, supervisor failure and audio exclusion
remain explicit refusal states. Already-Off/On commands are idempotent. Initial
bearer activation still uses only the existing attended one-shot operation;
no modem/radio/IPA transition was added. True reconnect/airplane mode remains
blocked by the stock IPA lifecycle defect.

Agent focused checks passed: tests/myron-mobile-data, shell test/tile-scripts.sh,
tests/myron-cellular-op and tests/myron-runtime-toggles. Shellcheck was not
available through the local shim. Parent reviewed the changed control paths.
Deployed the helper and two tile scripts with backups under
/var/lib/myron-data-helper-before-20261029. On the existing Omarchy boot,
helper Off twice reported Off and blocked a cellular-bound HTTPS request;
On twice reported On and restored HTTP 204. An independent 35-second timer
and exit trap restored traffic on failure; the timer was canceled after success.
Data is left On. No shell reload, modem restart or reboot was needed.

The package/composer already install these paths. Drift check: zero compared
file differences, 12 private/generated files unchecked. Rollback: restore
myron-mobile-data to /usr/local/bin and tile-action.sh/tile-state.sh to
/usr/share/omamobile/shell/plugins/omamobile.quicksettings from that backup,
retaining executable modes. Fresh-image boot acceptance is not claimed.

### Fingerprint current-stock inventory (2026-10-29)

Read-only inspection on the same Omarchy boot confirms `/dev/xiaomi-fp`
(491:0), in addition to mifp_id/qbt_ipc. The hyphenated path was missed by
previous narrow searches. Current stock uses Xiaomi's fingerprint AIDL V4
service and `fingerprint.goodix_us2.default.so`, not the historical
`mfp-daemon` layout. Goodix links QSEECom; the Pixel Trusty backend is not
applicable. `/dev/ion` is absent, so the HAL's allocation path needs offline
inspection before startup. See [FINGERPRINT-PLAN.md](FINGERPRINT-PLAN.md).

Added a pinned read-only stock inspection tool. Vendor is ext4; corrected
mounts disable journal replay. Seven selected HAL/config files were captured
privately, with hashes and dependencies. All temporary mounts/loop mappings
were removed. No HAL execution, fingerprint-node open, enrollment, calibration,
secure-storage, module, PAM or production configuration change occurred.
Data remains On. Next: exact dependency/property/TA and allocator analysis,
then a bounded Myron-specific runtime design before hardware activation.

### Launcher pull-down and home search gesture (2026-10-29)

Installed repository Launcher.qml and Home.qml on Omarchy with originals in
`/var/lib/myron-launcher-swipe-before-20261029`. The drawer follows downward
pulls from its header or the app grid at its top, then settles closed or back
open on release. Normal grid scrolling remains available away from the top.
A downward home-background swipe opens focused search on release. Widget
areas, edit mode and open sheets are excluded to preserve their interactions.
App taps/holds are suppressed during a drawer pull and briefly afterward.

Both QML files parse with qmlformat. The image composer now explicitly copies
and byte-verifies Home.qml alongside Launcher.qml; package installation already
copies the plugin tree. Composer shell syntax passes. Reloaded the shell once
while unlocked, without reboot. Drift check: zero compared-file differences,
12 private/generated paths unchecked. Physical gesture smoothness, cancellation,
keyboard focus and interaction acceptance still require the owner's touch test.
Rollback: restore the two plugin paths from the backup, then reload unlocked.

### Launcher gesture corrections and keyboard focus (2026-10-29)

Owner confirmed downward drawer tracking works, but home search did not show
its keyboard and widget-origin swipes were excluded. Removed that exclusion
as requested, retaining edit/sheet/pager gates. Added a bounded Hyprland focus
grab followed by OnDemand focus and an explicit OSK visibility request on a
committed drawer open; previews do not request keyboard focus. Closing cancels
timers and releases the grab. Dock and drawer search now share the top bar's
horizontal safe inset. A separate handle above the dock previews drawer opening
with finger movement; recents remains on the bottom strip.

Backed up the preceding two QML files in
`/var/lib/myron-launcher-swipe-before-r2`, installed and reloaded unlocked.
Both files parse. On installed Omarchy, programmatic open now reports OSK
Visible=true; a compositor-injected `a` reaches the search query and filters
41 apps to 32. Closing clears the query and OSK reports false. This confirms
keyboard focus as well as visibility, but does not replace touchscreen typing
or handle/widget gesture acceptance. Zero compared-file drift; 12 private or
generated paths unchecked. Existing explicit composer copy/hash checks cover
both files. No reboot or image rebuild. Physical handle feel remains open.

### Search dock corner clearance (2026-10-29)

Owner accepted the gesture update and requested another 8 logical pixels of
bottom clearance. Raised the dock search pill by adding that bottom inset and
expanding the dock equally, preserving the pill height and handle spacing.
Deployed Launcher.qml, backed up as
`/var/lib/myron-launcher-before-raise8.qml`, and reloaded unlocked. QML parses;
zero compared-file drift, 12 paths unchecked. Composer already copies and
verifies this file. Strata replacement is the next requested task; Nautilus
currently has reverse dependencies from nautilus-python and the GNOME portal,
so removal must preserve portal functionality rather than force dependencies.

### Strata installed; chooser replacement in progress (2026-10-29)

Installed the checksum/provenance-verified upstream aarch64 Strata 1.1.1 as
our pinned pacman package. All required libraries were already installed;
no OS upgrade occurred. The application opens on the current Omarchy boot.
Its D-Bus FileChooser backend exposes version 4 and OpenFile/SaveFile/SaveFiles.
A direct backend OpenFile test rendered the chooser with visible Cancel/Open
controls; Request.Close canceled successfully with response 1 and no files.
Private screenshots: out/private/strata-1.1.1/live.png and chooser.png.
This verifies the backend, not yet routing through the system portal frontend.

Owner explicitly requested full Nautilus removal, including replacing its
file dialogs with Strata. Updating package dependency/portal selection and
reimage integration is in progress. Nautilus, nautilus-python and the GNOME
portal remain installed until the shell's hard dependency is replaced cleanly.
Do not use pacman -Rdd. Strata is installed but defaults/removal are not complete.

### Strata file chooser and Nautilus removal: repository side (2026-10-29)

Packaging only; nothing installed or removed. `omamobile-shell` 0.2.24 no
longer depends on xdg-desktop-portal-gnome (now xdg-desktop-portal and
xdg-desktop-portal-gtk) and moves its Access-only portals file to
`/etc/xdg-desktop-portal/`. `omamobile-apps-myron` 0.2.1 owns
`/etc/xdg/xdg-desktop-portal/hyprland-portals.conf` (read first) with
`FileChooser=strata;gtk`; `omamobile-apps` 0.2.1 (generic) keeps the GNOME
chooser, its dependency and its GDK_BACKEND drop-in. `phone.lua` rebinds
Super+Shift+F and Super+Alt+Shift+F to `xdg-open`. The Myron rootfs skips
nautilus and nautilus-python (`rootfs/packages.omarchy-skip.myron`) and its
closure check forbids them and xdg-desktop-portal-gnome. Live removal,
`tools/myron-drift-check` and a practical chooser test are still to do.

### Strata fully replaces Nautilus on Omarchy (2026-10-29)

Installed strata 1.1.1-1, omamobile-shell 0.2.24-1 and apps-myron 0.2.1-1.
The first upgrade refused 22 previously deployed unowned helper files. Each
was byte-compared to the package and backed up before explicit path-only
adoption; no broad overwrite was used. Pacman's chooser .pacnew was promoted
after backing up the old policy. Removed nautilus, nautilus-python and
xdg-desktop-portal-gnome together with dependency checks enabled. pacman -Dk
reports no database errors. No OS upgrade or reboot.

Strata is inode/directory default and owns org.freedesktop.FileManager1
(`/usr/bin/strata --gapplication-service`). Replaced the one saved Nautilus
home shortcut. A request through org.freedesktop.portal.Desktop mapped
`io.github.lgse.Strata.FileChooser`, proving frontend routing, then canceled
without selecting files. The main Strata window also maps. Portal frontend
was restarted once after policy replacement. No chooser or preview sandbox
was weakened.

System backups: /var/lib/myron-strata-before-20261029 (package versions,
original shell/profile files and adopted unowned files). User backups:
~/.local/state/myron-strata-before-20261029 (home layout and existing defaults).
Rollback requires reinstalling the previous shell/app profile and the removed
Nautilus/portal packages, then restoring the backed-up configuration; do not
restore pacman database directories manually. Previous local build packages
remain available on the host. A user's later preferences should be preserved.

Myron rootfs now skips/forbids Nautilus and the GNOME chooser; package-owned
portal/default files choose Strata. The composer rejects older bases that lack
Strata, retain Nautilus/gnome chooser, or have a different chooser policy.
HomeModel is copied and byte-verified by the composer. Drift check after
installation: zero compared-file differences, 12 private/generated paths
unchecked. Fresh-image boot not tested. Full media-codec/preview coverage and
phone-specific Strata usability remain unqualified.

The phone locked before the guarded shortcut/shell reload, so that reload was
skipped. File-manager and chooser defaults are already live; the new
Super+Shift+F bindings await an unlocked reload. Owner was asked to unlock for
that and the next navigation update. New authorized UI scope: Opus implements
bottom app-switch/recents/home gestures with transient handle and haptics,
including tap-anywhere dismissal for empty recents; next add Settings sections
for General, Keyboard and Quick Settings with keyboard size/bottom clearance.

Owner unlocked after the Strata migration. Applied the pending Hyprland
shortcut reload and shell restart on 2026-10-29; reload returned ok and
Hyprland reported no configuration errors. Navigation implementation remains
in progress with Opus and has not been deployed yet.

### Bottom navigation overlay deployed (2026-10-29)

Opus implemented shared NavState, bottom-strip app switching/recents/home
with animated previews, transient handle, and existing opt-in bounded haptics.
Empty recents now has tap-anywhere dismissal and a hint instead of Home.
The Home button remains when recents contains apps. The gesture layer ignores
input, has no above-lock rule, and actions check lock/pocket state. Parent
bounded the lock-check process to two seconds. Physical safety/gesture behavior
is not established by those static gates alone.

Deployed NavState/qmldir, Launcher, Switcher/manifest and phone.lua with
backups in /var/lib/myron-navigation-before-20261029 (absent lists new files).
Reloaded unlocked on Omarchy; Hyprland reports no config errors. Launcher IPC
responds; recents summon/hide succeeds without captured QML runtime errors.
QML parsing and Lua compilation pass; agent's isolated state test passed.
Drift check: zero compared-file differences, 12 paths unchecked. Composer
copies/checks the new module and rules; package installer includes them.
No reboot. User acceptance remains open for actual drags, app selection,
haptics, hidden-handle recognition, keyboard interaction and empty recents.
Keyboard sizing/Settings integration is being scouted next.

### Home-only search dock (2026-10-29)

Owner requested the search bar belong to Home instead of every app. Launcher
now uses the existing empty-workspace definition of Home: search pill and
pull-up search handle show only there. In apps the panel shrinks to the bottom
navigation strip, preserving app-switch/recents/hold-home gestures. Deployed
with backup /var/lib/myron-launcher-before-home-only.qml and reloaded unlocked.
QML parses and compared-file drift is zero (12 unchecked paths). Composer
already copies/verifies Launcher.qml. No reboot.

### Keyboard navigation clearance restored (2026-10-29)

Opening search used to unmap the entire dock, removing the gesture strip.
Launcher now keeps the dock mapped at navigation height while search is open;
only Home without the drawer shows its search pill/handle. Deployed with
backup /var/lib/myron-launcher-before-keyboard-gap.qml and reloaded unlocked.
Actual Omarchy layer geometry with search and OSK open: dock y=1280 h=24,
OSK y=942 h=338 on the 1304-logical-pixel-high output. The keyboard ends at
1280, leaving the bottom 24 pixels for navigation. Physical gesture acceptance
is pending. Compared-file drift zero, 12 unchecked paths; QML parses. Settings
and Omarchy keyboard styling implementation is delegated and not yet deployed.

### iOS-style swipe home and pause for recents (2026-10-29, not deployed)

Owner requested iOS navigation. The bottom strip's swipe up now follows the
finger and goes Home on release; swipe up and pause (finger within a 12-unit
circle for 200 ms, at least 64 units up, with at least one app open) arms
Recents with a card-spread preview and one bounded haptic, and release then
shows Recents. Arming is position-based, never velocity-based; release speed
only lets a short unarmed flick count as Home. A small drag, or dragging back
down after arming, springs back. Sideways switching and stationary
hold-to-home are unchanged. Home now hides the launcher drawer
(`omarchy-shell shell hide omamobile.launcher`) and the OSK (SetVisible false),
and dispatches the empty-workspace focus only when an app is in front, so it
never activates an app workspace. Recents never stand empty: IPC summon with
no apps, Clear all and closing the last card all go Home. Recents cover the
dock strip, so they carry their own bottom strip (Bottom gap height, no
keyboard focus, no above_lock) where a swipe up goes Home.

Files: `plugins/omamobile.gestures/NavGesture.js` (new, pure classifier),
`plugins/omamobile.switcher/Switcher.qml` and `manifest.json`,
`test/nav-gesture.js` (new) and guards in `test/all`, package README and the
composer's byte-verification list. Launcher.qml and phone.lua are unchanged;
Settings geometry and the persistent dock strip are preserved. The package
installer and the composer's gestures loop already copy the new file. QML
parses and the classifier test passes. Hardware acceptance pending: quick
swipe Home from an app, from Home with drawer and keyboard open; pause arms
with one tick and Recents stay; small drag returns; empty Recents and last-card
close go Home; Recents strip swipe; lock and pocket refusal.

### TODO: keyring provisioning and device-PIN unlock (owner, 2026-10-29)

Owner reports repeated “choose a password for your new keyring” dialogs whose
input cannot be used on the phone. Integrate initial keyring provisioning and
subsequent unlock with the authenticated lock-screen PIN flow, so normal device
use does not require this separate desktop prompt. This is queued work, not
implemented or tested; continue the current keyboard/Settings work first.

Acceptance and design boundary:
- Identify the actual Secret Service/keyring provider and the existing PIN/PAM
  path before choosing an integration. A device PIN and login password must
  not be assumed interchangeable, especially with graphical autologin.
- Provision a missing encrypted keyring through the intended authenticated
  setup/unlock flow; unlock it after successful PIN authentication. Never
  persist/log the PIN, create a blank-password keyring as a workaround, or
  silently replace/delete existing encrypted keyrings or stored secrets.
- Support existing keyrings, PIN changes and failed/canceled unlock safely;
  provide a keyboard-accessible migration/recovery prompt when old credentials
  are genuinely required. Define keyring locking across session lock/logout.
- Verify on Omarchy: first use, reboot/autologin then PIN unlock, relock,
  wrong PIN, PIN change, and an application storing/retrieving a test secret.
  Confirm the unusable new-keyring dialog no longer appears during normal use.
- Ship provider/PAM/session changes and migrations through package/composer
  sources with backups, password fallback and an independent SSH recovery path.

### Keyboard auto-show failure diagnosed (2026-10-29)

Owner reports focused browser/Strata text fields do not open the OSK and the
Quick Settings button appears ineffective. Live read-only diagnosis: Squeekboard
is running and sm.puri.OSK0.SetVisible(true) succeeds, but GNOME accessibility
screen-keyboard-enabled was false. Restored that setting to true, matching the
existing phone setup policy. No screensaver process or stale OSK-off marker
was present at the check; the cause of the disabled setting is not yet proven.
GTK/QT input modules are wayland and fcitx5 is inactive. Chromium currently
has Wayland platform flags, but no explicit Wayland IME flag.

The active keyboard/Settings agent was steered to fix persistent activation,
verify browser IME requirements and order Quick Settings OSK showing after
sheet dismissal. That ordering is a hypothesis until tested. Existing code
requests SetVisible before dismissing the focused sheet. App-by-app physical
auto-show and the tile are still pending acceptance; do not mark fixed from
restoring the GSettings value alone.

### Keyboard tile and automatic activation control requested (2026-10-29)

Owner requested a Quick Settings keyboard trigger with an auto-opening toggle.
Extend the existing Keyboard tile: primary action manually opens/hides the OSK;
chevron or long-press opens the Keyboard settings page. That page must expose
“Automatically show when typing”, backed by the accessibility activation
setting. Manual opening must remain available with automatic opening disabled.
Show visibility and automatic preference separately. Preserve a deliberate
Off across setup/login; do not silently re-enable it as a repair. Request sent
to the active keyboard/Settings implementation task; not yet deployed.

## Navigation deployment blocked by existing compositor crash (2026-10-29)

The iOS-style navigation changes remain repository-only. Before deployment,
Omarchy was reachable over USB SSH but Hyprland was in `--safe-mode --locked`
and no shell was running. The existing crash report for PID 4886 records
SIGSEGV in `memcpy`, custom `libgallium-26.2.2.so`, and
`Render::GL::CGLTexture::update` during a surface commit. The report does not
establish the triggering client; its library symbol labels are not reliable
without proper symbolization. No new navigation or Settings files had been
deployed.

One attempt using the existing `omarchy-restart-shell` recovery helper failed:
Wayland reported `invalid object 88` during lock acquisition, and the launch
helper stopped after six relaunches in under a minute. Do not repeat the same
recovery unchanged. SSH remains available; no reboot, GPU changes, or lock
bypass was performed. Restore a stable compositor/session before deploying
the pending UI changes or claiming hardware acceptance.

Recovery completed in the same boot: the owner confirmed the sad-face locked
crash screen (not the safe-mode dialog). Restarting `sddm.service` recreated
the graphical session through `myron-start-omarchy`, without rebooting or
changing GPU files. The new Hyprland process has no `--safe-mode` flag;
Omarchy lock IPC reports `secure=true`, `sessionLocked=true`, one real screen.
USB SSH, `myron-cellular.service`, and `myron-sensor-stage.service` remained
available/active. Pending UI deployment still requires an unlocked session.

## Swipe Home / pause Recents deployed (2026-10-29)

After recovery and confirmation that the session was unlocked, deployed
`NavGesture.js`, `Switcher.qml`, its manifest and the shared
`SettingsGeometry.js` dependency. Originals and absent-path records are in
`/var/lib/myron-nav-ios-before-20261029`. Transfer verification used SHA-256
(the first attempt stopped because `cmp` is absent; resumed without replacing
original backups). Shell reload succeeded, IPC ping returns `ok`, and no
matching QML load errors appeared in the bounded journal check.

Physical quick-swipe Home, pause-to-Recents, drawer/keyboard dismissal and
empty-Recents behavior remain pending owner acceptance. Drift check reports
eight differing files from the pending Settings/keyboard work, not navigation
files, and twelve paths without repository sources. Missing new Settings files
are not enumerated by that tool; the Settings feature is not deployed.

## Navigation accepted provisionally; Home haptics (2026-10-29)

Owner reports gestures work well enough for now; the earlier Recents failure
is not assigned a proven cause. Read-only gesture state diagnostics were
deployed, with backup `/var/lib/myron-switcher-before-trace-20261029.qml`.

Added the existing bounded haptic pulse to committed swipe-to-Home and the
Recents bottom-strip Home swipe. Recents arming already pulses once (no second
pulse on release); sideways app-switch commitment and stationary hold-to-Home
already pulse. The Recents strip now checks the secure lock before committing.
Pulse strength/duration and the safety/rate limits are unchanged: 35 ms effect,
Touch feedback opt-out, no pulse when locked, pocket-guarded or panel-off,
maximum six per ten seconds and 300 ms separation. Frequent repeated gestures
may intentionally omit feedback under this existing limit.

QML parse and three haptic-policy tests passed. Haptics reports available and
enabled on Omarchy. Targeted deployment and unlocked shell reload succeeded;
backup `/var/lib/myron-switcher-before-haptics-20261029.qml`. Hardware feel of
the new Home pulse awaits owner confirmation. Existing package/composer copies
this file. Pending Settings drift remains separate.

Owner requested quicker Recents arming: reduced `NavGesture.HOLD_MS` from
200 to 150 ms (the existing timer scheduling allowance remains 20 ms).
Movement tolerance and haptic policy are unchanged. All eight gesture tests
passed; deployed and reloaded while unlocked. Backup:
`/var/lib/myron-nav-before-150ms-20261029.js`. Drift remains the same eight
pending Settings files and twelve unchecked paths; the gesture file matches.

## Owner-requested Android visit (2026-10-29)

Owner requested Android temporarily for unrelated Play Store use. Restored
the existing host USB profile `myron-usb-runtime-20261027` on its matching
interface after the connection had lost its address. From verified Omarchy,
requested `systemctl reboot --reboot-argument=bootloader`. Fastboot identified
`product: myron`, current slot A and `slot-unbootable:b: no`. Selected slot B,
read back B, then issued `fastboot reboot`; both operations succeeded. No
images were flashed or filesystems reformatted. Omarchy remains on A; return
requires selecting A again. Android may update its shared secure/radio state;
refresh relevant private backup evidence before later hardware experiments
that require a stock-boot baseline. UI deployment is paused during this visit.

## Publication checkpoint checks (2026-10-29)

The complete shell package `test/all` passed after updating stale assertions
for the optional Settings tile and the shared search safe-area inset. Those
assertions now match the intended UI; runtime behavior was not changed by
this validation cleanup. The repository-level fixture suite is bounded to
180 seconds for this checkpoint; its result is recorded separately below.
A checkpoint branch preserves the local development history without replacing
the fork's newer upstream main. No upstream PR or production release is made.

Repository `tests/all` reached its 180-second checkpoint time limit (exit
124) during `tests/myron-cellular-stage`; checks emitted passing results
through concurrent activation/failure-lock assertions. It did not complete,
so no full-suite pass is claimed. The read-only publication audit found no
actual secrets or proprietary binaries in pending files or local history.
`tools/pr-check` reports identifier-shaped synthetic fixtures in Bluetooth,
cellular and IPA tests; these are not real device values, but that gate is
not green. Resolve those fixture/gate issues before an upstream PR. The
checkpoint is published to the owner's fork only, with no PR or force push.
