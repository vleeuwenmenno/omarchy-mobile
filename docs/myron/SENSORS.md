<!-- SPDX-License-Identifier: MIT -->
# Myron sensors

Status: Omarchy sensor-only ADSP/FastRPC startup and accelerometer staging passed
on 2026-10-28. The owner confirmed corrected portrait orientation through the
home-screen Sensors widget. The owner accepted the compass for the current
development baseline on 2026-10-28, with the measured accuracy limits below.
Further compass accuracy investigation is parked. Light response and proximity
cover/uncover still need physical acceptance. Auto-rotation
is not enabled or accepted. Historical reference: SSC sensors were tested on postmarketOS on
2026-10-27. Accelerometer, gyroscope, magnetometer/compass and proximity
returned live samples. SensorProxy advertised accelerometer, ambient-light and
proximity support. Ambient-light presence is proven, but no light measurement
arrived during the short unattended window. Omarchy integration and physical
auto-rotation were untested at that earlier checkpoint.

## Omarchy hardware result, 2026-10-28

### Widget sampling update, 2026-10-28

The owner requested low-power idle readings and a faster mode on tap after
accepting compass accuracy. Widget version 1.1.0 is installed:

- Low mode takes one bounded snapshot every 30 seconds while the placement is
  active, with 5-degree compass steps and a simpler dial. Claims are released
  between snapshots.
- Tapping the dial/button selects at most 60 seconds of 5 Hz JSON updates from
  one connection holding the sensor claims. Display precision becomes 0.1°;
  this is formatting, not improved physical accuracy.
- Home page changes, covering applications, editing, sheets and panel-off state
  stop sampling through the new generic `host.active` hint. Lock checks use
  logind plus Omarchy's public lock IPC; lock stops fast mode without automatic
  resumption. Process timeouts and D-Bus disconnect also bound claim lifetime.

Local and on-device widget checks passed. The widget-tool suite passed after
its example inventory was updated to include the previously added sensor
widget. The changed home QML parses. Focused review found no material issues.
On the current Omarchy boot, a requested four-second fast diagnostic while
locked emitted only `suspended`; no sensor sampler remained running afterward.
The panel reported off and the shell lock reported secure. Omarchy's logind
LockedHint remained false, confirming the need for the shell IPC check.

Unlocked hardware sampling subsequently produced 18 frames over 3402 ms, with
a median interval of 200 ms (5 Hz). All four rows were available. The owner
reported that fast updates appeared somewhat smooth and clarified that idle
readings do update but the 30-second interval was too slow.

At the owner's request, version 1.1.1 changes idle snapshots to every two
seconds and moves the fast-mode toggle to a speedometer icon at the top right.
The previous Widget.qml and manifest are backed up in
`~/.config/omamobile/sensors.before-2s-20261028/`. Coarse 5-degree formatting,
the 60-second fast limit, single-sampler rule and activity/lock stops remain.
The shorter idle interval increases sampling duty compared with version 1.1.0;
do not describe it as equivalent battery consumption.
Local and installed widget checks passed for 1.1.1. During the seven-second
idle-cadence observation the screensaver covered the home screen, and no idle
samplers appeared. Dismissing that specific screensaver window invoked the
existing lock-on-wake policy; the lock then reported secure and sampling stayed
stopped. The two-second cadence and new icon still need unlocked visual/runtime
confirmation. Do not count either inactive observation as an idle-rate test.

**Pending:** termination of an already-running stream when hidden/locked and
physical light/proximity cover/uncover response.
Do not call these passed based on source review. No whole-device battery-life
measurement has been made. No compass calibration or hardware driver changed.

Original widget backup on the phone:
`~/.config/omamobile/sensors.before-power-20261028/`. Original Home.qml and
WidgetHost.qml are in `/var/lib/myron-widget-power-20261028/`; they were updated
under `/usr/share/omamobile/shell/plugins/omamobile.home/`. The private staged
files, hashes and installer are retained in the repository's `out/private/`
under the `myron-widget-power-20261028` name. Restore the widget and both home
files together if reverting. The supported shell restart reported a transient
re-lock verification failure, but a subsequent live status confirmed
`locked=true`, `sessionLocked=true`, `secure=true`; do not restart again merely
because of that earlier message.

Next hardware task: observe ambient-light decrease/increase and proximity
Near/Far while covering/uncovering the front sensor area, using the new fast
mode. Existing SensorProxy capabilities are true; physical transitions remain
unqualified. No DSP restart, registry reload or reboot is needed.

The test ran Omarchy 4.0.6, kernel
`6.12.23-android16-5-g5a0e85dd9db0-dirty-4k`, boot
`c8d0cf8d-7572-4169-aa13-e2e8a7760bc6`. The main recovery guard stayed active.
No audio transport, codec, amplifier or speaker helper was started.

1. `tools/myron-sensor-foundation` replaced the unbound, zero-reference PD
   mapper with the pinned Canoe mapper, loaded pinned FastRPC, and started
   ADSP once. It completed in 2.472 seconds with secure FastRPC major/minor
   verified. Hottest temperature was 56000 mC before and 53460 mC after.
   An early preflight refusal was corrected: the boot log's `powering up`
   message preceded `adsp.mdt` lookup failure (-2), not an actual DSP boot.
   That refusal had made no hardware changes.
2. Registry staging yielded real accelerometer measurements, but initially
   failed its SensorProxy gate. Omarchy's installed 3.9 udev rule advertised
   only `ssc-light ssc-compass`. The Myron overlay now adds `ssc-accel` and
   `ssc-proximity` for the secure ADSP device only.
3. After that targeted rule update, the complete sensor stage passed with
   324 accelerometer measurements. `HasAccelerometer`, `HasAmbientLight` and
   `HasProximity` all returned true. No registry reload or DSP restart was
   needed for the second stage invocation.
4. The generic home widget displayed orientation, 142.8 lux, Far and 93.3°
   in a captured frame. These are reported readings, not an accuracy test.
   The owner found upright portrait reported as bottom-up; the Myron rule
   now sets `ACCEL_MOUNT_MATRIX=-1,0,0;0,-1,0;0,0,1`. The owner confirmed
   orientation looked correct after the update. Full display/touch rotation
   and all four orientations remain separate acceptance checks.

The kernel reported an unresolved `msm/adsp/ois_pd:tms/servreg` lookup (-6).
Do not infer OIS or camera support from the successful SSC test. HexagonRPC
still reports unsupported method 31 after registry loading, as in the earlier
reference test; it is not suitable as an always-running daemon yet.

The foundation helper is manual and guarded, not a boot service. Do not start
audio later in the same sensor-only boot: the audio notifier did not observe
ADSP's initial UP event. Do not unload or restart the DSP to work around that.
No persistent rotation or automatic sensor foundation has been enabled.

The first successful sensor boot returned to pmOS at uptime 1203 seconds.
The recovery latch and persistent guard log both recorded `guard-timeout`
against the existing 1200-second deadline. No guard was disabled or extended.
The widget's first compass-dial upload overlapped recovery and failed. It was
subsequently deployed in a second Omarchy test, boot
`fe3113ba-0ba1-4085-accd-7782e7540eff`, and passed the on-device widget check.
The same sensor-only foundation and accelerometer stage passed in that boot.
Light/proximity initially remained undiscovered; a proxy restart after the
completed hardware sample exposed accelerometer, light, proximity and compass.
This supports a discovery-timing issue. The stage now refreshes SensorProxy
after its actual sample instead of immediately after registry loading. This
ordering change is deployed and passes the focused gate; its full fresh-boot
acceptance remains pending rather than forcing another reboot for reassurance.

During boot `e8c0f7d6-ccc2-4fab-a937-fb8b475e52a5`, the owner-selected
untimed development guard started correctly. Manual sensor foundation passed
in 2.535 seconds (58700 mC before, 57500 mC after; audio inactive). Registry
staging reached its actual accelerometer sample but immediately rejected
`HasAccelerometer` after restarting SensorProxy. The transient test's failure
hook caused recovery at uptime 168 seconds (`unit-failed`, not timeout).
Persistent journals confirmed that SensorProxy restart and the failed check
occurred in the same second. The stage now allows up to five one-second waits
for asynchronous discovery within its unchanged 45-second service bound.
The previous file is backed up as `sensor-stage.before-discovery-wait` in the
pmOS development-policy backup directory. No DSP retry or unload occurred.

Fresh Omarchy boot `84e10ba1-3c62-4c09-ad0b-adc353eb2b37` then passed foundation
and the corrected stage. The stage finished in approximately six seconds with
a real accelerometer sample; accelerometer, light, proximity and compass
capabilities all returned true. The compass capability is queried on
`/net/hadess/SensorProxy/Compass`, not the parent sensor object. The manual
enable marker was removed after startup; no automatic sensor boot service was
enabled. The guard remains active/running with deadline zero. This closes the
fresh-boot stage discovery check, not physical compass accuracy or rotation.

The owner subsequently compared iPhone 247° against Poco 336° (89° difference).
This is not sufficient to establish a constant offset: a later captured Poco
frame showed 247.4° with Left up orientation and paused readings. A flat,
same-direction comparison at two headings was still pending then. No compass correction
has been applied. The local libssc 0.4.4 source computes heading from the SSC
rotation-vector quaternion; the accelerometer's mount-matrix fix is not a
compass calibration.

With the phones flat and separated by approximately 30 cm, the owner later
reported iPhone 230° versus Poco 335°. A 30-second continuous SensorProxy claim
then produced approximately 255.6–256.7°, settling near 256.5°. The owner
reported 231° on the stationary iPhone during that sample: about +25.5°, not
a fixed +90° discrepancy. Earlier `303 -> 144` comparison was ambiguous and
is not treated as a controlled second-heading pair.

A separate 15-second direct SSC observation decoded 77 rotation-vector reports:
heading started at 255.3229° and ended at 255.6017°; all 77 had accuracy code 3
and none failed decoding. libssc's local protocol definition labels 3 as high
accuracy, but its compass measurement signal discards the accuracy field and
publishes only heading. High internal accuracy does not prove agreement with
an external north reference. The widget's short claims remain a possible
sampling limitation, but continuous sampling did not remove the observed
roughly 25° discrepancy. No correction, calibration reset or firmware write
was made. The owner confirmed iPhone “Use True North” is disabled, so that
reference is magnetic north. The approximately 25.5° discrepancy remains
unresolved; a controlled second-heading pair was still pending then. The guard
returned the phone to pmOS after these captures;
do not repeat them in pmOS or automatically loop through another boot.

On the subsequent untimed Omarchy boot, the owner reported iPhone 230° and
Poco 245–250° while slightly lifting the Poco but retaining its table heading.
The 15–20° difference is another posture-dependent observation, not evidence
for a constant correction. The widget reported Left up in that posture. Live
inspection confirmed SensorProxy itself reported `left-up` and the expected
180-degree X/Y mount matrix was present in udev. The widget does not transform
that label. An upright portrait comparison is needed to distinguish mapping
from a retained near-flat orientation. The upstream 3.9
[orientation calculation](https://codegraph.jelmer.uk/iio-sensor-proxy/3.9-1/src/orientation.c)
retains its previous orientation when neither axis exceeds its 35-degree
threshold. No matrix or compass offset was changed for this observation.
The owner then confirmed that fully upright portrait changes to Normal while
Test live runs. A two-second raw accelerometer observation during this exchange
showed predominantly positive Y (approximately 9.3–9.6 m/s²); the installed
matrix negates Y, consistent with Normal in the provider's calculation.
Upright portrait mapping is therefore reconfirmed. The near-flat Left up label
does not establish a mapping regression; it is consistent with retention of
the previous orientation. Full four-way orientation acceptance remains open.

The owner then supplied a flat-on-desk turn-and-return comparison, with iPhone
True North still disabled:

| Position | iPhone | Poco | Poco minus iPhone |
| --- | ---: | ---: | ---: |
| Initial straight | 214° | 235° | +21° |
| Turned left | 123° | 140° | +17° |
| Returned straight | 213° | 243° | +30° |

The outward changes are -91° and -95° respectively; the return changes are
+90° and +103°. The final readings differ from their initial values by -1°
on iPhone and +8° on Poco. This demonstrates approximately correct turn
direction and angular response in the tested plane, while absolute agreement
and return repeatability remain unqualified. It does not support a 90-degree
axis swap or one exact constant correction. Physical return alignment,
settling time and sampling were not instrumented, so the +8° return difference
is observed non-repeatability, not an isolated measurement of sensor drift.
Magnetic surroundings, sensor calibration and fusion/sampling behavior remain
possible contributors. No offset or calibration change was applied. The next
useful physical comparison, if accuracy work is reopened, is a matched flat
heading away from the desk and magnetic accessories rather than repeating the
same desk sequence unchanged.

**Owner sign-off, 2026-10-28:** “Let's sign this off as acceptable.” The compass
is accepted for the current Omarchy development baseline. Retain the measured
reference and return differences as limitations; do not label this precision
navigation qualification or claim a calibration fix. No further compass
testing, calibration or offset changes are required for this milestone.

The new compass QML files initially remained invisible despite matching
deployed hashes and a passing widget check. Changing the entry filename caused
`File name case mismatch` and a blank widget. Restoring `Widget.qml` and using
the supported `omarchy-restart-shell` command once restored the widget and
loaded the dial. A real Omarchy screenshot then confirmed the dial and button
fit inside the card. This required no sensor restart or reboot. Do not claim
live QML deployment from file hashes or lint alone.

### Targeted deployment and rollback

On Omarchy, the original stage script and unit are backed up under
`/var/lib/myron-sensor-test-20261028/{stage.before,unit.before}`. The new rule's
original absence is recorded in `udev-rule.before`; its pre-matrix version is
`udev-rule.before-matrix`. Restore the two originals, remove the added rule,
then reload systemd/udev for a repository rollback. Do not unload live drivers.
The existing guarded recovery returns the hardware to a fresh boot.

The widget is at `~/.config/omamobile/widgets/sensors/`. The original home
layout is `~/.config/omamobile/home.json.before-sensors-20261028`. Restore that
layout only if no subsequent owner layout edits need preserving. The source
is `packages/omamobile-shell/widgets/examples/sensors/` and ships through the
existing example installer. Its runtime checks must run on Omarchy too.

The test ran kernel
`6.12.23-android16-5-g5a0e85dd9db0-dirty-4k`, boot ID
`ac4ee6db-3c5a-49ac-9f6c-ab290d46719a`. It did not reboot, load a module,
restart the ADSP or change the display.

## Hardware evidence

The ordinary IIO inventory exposed only two Qualcomm ADC devices. The motion
sensors instead live behind Qualcomm's Sensor Core on the ADSP:

- QRTR advertised service 400, Snapdragon Sensor Core.
- `qti_qmi_sensor_v2` was loaded and the ADSP remoteproc was running.
- The stock Myron ODM configuration identifies LSM6DSV accelerometer/gyro,
  QMC6309 magnetometer, STK6B9x light/RGB and SX937x SAR sensors, plus rotation
  vector and device-orientation algorithms.
- With the board registry loaded, `ssccli` returned changing accelerometer,
  gyroscope and magnetometer values, a compass heading and proximity `FAR`.
- `net.hadess.SensorProxy` then reported `HasAccelerometer=true`,
  `HasAmbientLight=true` and `HasProximity=true`.

The live accelerometer values near rest were approximately X 0.12, Y 0.53 and
Z 9.90 m/s². The values are included only to prove a physical sample occurred;
the integration does not persist raw samples.

## Runtime and package

The private sensor configuration came read-only from this phone's own ODM
partition. It is not committed or redistributed:

```text
out/private/myron-sm8850-sensor-config-20261027.tar.gz
SHA-256 b57fd29b70c63fef2746ce877207b914fd2b193d6f385851fa29605372bf78ac

out/private/myron-sm8850-sensor-runtime-v3-20261027.tar.gz
SHA-256 01717daeb556d672c8bb2a04dcbd27834784ad48b61a2ff909121eff22ff4265
```

Upstream HexagonRPC 0.5.0 needed two narrow compatibility changes:

1. Map the same read-only sensor configuration under both Android's
   `/vendor/etc/sensors/config` and `/odm/etc/sensors/config` virtual paths.
2. Ignore non-JSON files in `sscregistrygen`; the unpatched generator
   dereferenced a null JSON object when the ODM directory contained PNG/list
   assets. A systemd coredump confirmed that exact failure.

The package is in `packages/hexagonrpc`. Its native tests and a real aarch64
development package build pass. The first two hardware layouts failed because
firmware kept resolving the ODM path. Runtime v3 supplied the ODM alias and
loaded 288 generated registry entries.

HexagonRPC currently exits cleanly when this firmware requests unsupported
FastRPC method 31 (`Unexpected buffer count for method 31`). Registry loading
has already completed by then and SSC continues serving samples. This remains
a limitation to fix before an always-running daemon is enabled.

## Omarchy integration safety

`myron-sensor-stage.service` is static and has two conditions: private assets
must exist and `/etc/omamobile/myron-sensors-enable` must be an explicit regular
file. The stage has a 45-second systemd limit, a 30-second HexagonRPC limit and
requires one real accelerometer sample before writing
`/run/omamobile-myron/sensors-ready`.

The composer accepts the private archive only with
`--sensor-runtime-archive`; it pins the exact v3 hash and extracts only the
`root/` asset subtree. It installs neither the archive's experimental binary
nor its library. The built `hexagonrpc` package supplies those. Composition
always removes the enable marker, and neither sensor staging nor autorotation
is enabled.

The combined v60 image contains the packaged sensor tools and
private-v3 registry alongside the radio and bounded speaker experiment:

```text
out/private/myron-omarchy-main-20261028-v60-audio-cellular-sensors.img
SHA-256 3c4c62321d0cf8ea69bd44472594d59c0e178564064f58a2e42fd42623d4c3bd
```

Its ext4 filesystem is clean. Image inspection confirmed `hexagonrpcd`,
`ssccli`, `sns_reg.conf`, the sensor stage and autorotation unit are present,
while the sensor enable marker and all sensor/rotation enable symlinks are
absent. The image was subsequently deployed and booted. On Omarchy, ADSP was
offline and the secure FastRPC device was absent, so sensor staging and physical
rotation remain untested there. The latest phone check found recovered pmOS
running with ADSP and secure FastRPC available. See [current status](STATUS.md)
for the current work boundary; do not start the speaker stack to obtain sensors.

The generic Omarchy Mobile autorotation client is reused from
`packages/omamobile-sensors/lib/autorotate.py`. Its user unit remains disabled
until an attended physical test can verify both DSI and touch transforms.

On 2026-10-28, a bounded service check on recovered pmOS demonstrated that
`systemctl try-restart iio-sensor-proxy.service` leaves an inactive proxy
inactive, while `restart` starts it. On cleanup, the proxy exceeded pmOS's
existing 3-second stop timeout and systemd killed it. After recording the
failure, `reset-failed` restored inactive/dead with `MainPID=0`; no reboot was
needed. This shutdown limitation remains open before repeated proxy refreshes.
All three capabilities were false on that boot; no registry was staged in this
check. The repository stage now explicitly restarts the proxy after registry
loading and fails if startup fails. Its unit no longer orders itself after
the service it restarts synchronously. The focused `tests/myron-sensors` gate
passes; deployment and end-to-end Omarchy staging remain pending.

## Attended Omarchy test

Do not run this while the owner is asleep or using the screen. First prove the
payload contains the pinned private runtime archive and the packaged
`hexagonrpc`. Then, on Omarchy:

```fish
sudo install -m0644 /dev/null /etc/omamobile/myron-sensors-enable
sudo systemctl start myron-sensor-stage.service
cat /run/omamobile-myron/sensors-ready
busctl --system get-property net.hadess.SensorProxy /net/hadess/SensorProxy net.hadess.SensorProxy HasAccelerometer
ssccli --sensor accelerometer --timeout 5
```

Expected: the ready marker says `result=ready`, SensorProxy returns `b true`,
and `ssccli` prints at least one accelerometer measurement. Stop on any timeout,
missing FastRPC device, missing measurement, DSP error, USB/SSH loss or kernel
error. Do not retry by restarting firmware or unloading modules.

Only after that pass, start rotation while watching the phone:

```fish
systemctl --user start omamobile-autorotate.service
```

Rotate the phone once through each portrait/landscape orientation. Pass means
the display and touchscreen remain aligned. Roll back immediately with:

```fish
systemctl --user stop omamobile-autorotate.service
sudo rm -f /etc/omamobile/myron-sensors-enable /run/omamobile-myron/sensors-ready
sudo systemctl reset-failed myron-sensor-stage.service
```

No reboot is part of this test.

## Physical proximity acceptance (2026-10-28)

On the existing Omarchy v60 boot, the owner covered/uncovered the upper front
of the phone during a 60-second `monitor-sensor --proximity` observation.
The log reported initial `near: 0`, then `1`, then `0`: a physical Far → Near →
Far transition. No display blanking, firmware startup, sensor restart or reboot
was performed. This qualifies the sensor feed, not automatic call-screen or
pocket behavior. The bounded monitor disconnects and releases its claim.

## First bounded autorotation trial (Omarchy, 2026-10-29)

Pocket protection and its styling were owner-accepted before this next task.
The same Omarchy boot retained its accelerometer. The laptop USB profile had
become disconnected; activating the existing `myron-usb-runtime-20261027`
profile restored SSH without touching phone services or rebooting.

The candidate autorotate helper preserves the live DRM mode, refresh rate,
position and scale, bounds compositor calls and records a transform only after
success. An apply failure quits the loop and returns nonzero so supervised
restoration runs. It releases the accelerometer when its loop exits. The
review's fail-stop finding referred to the earlier snapshot; the staged phone
copy contained the fix before launch. Four focused tests now cover mode
preservation, failure state, loop exit and compositor errors. The final source
also requires an exact `ok` response (not yet promoted to the phone).

A transient user unit ran an isolated candidate with an 85-second wrapper,
90-second RuntimeMaxSec and ExecStopPost restoring the captured baseline.
The wrapper also stops for lock, screen-off or missing compositor. Production
autorotation stayed disabled and its files were not replaced.

Observed DSI-1 transform 1 and touch transform 1/output DSI-1, with
1200x2608@120 Hz, scale 2 and position 0x0 preserved. On timed exit, readback
confirmed monitor transform 0, the same mode/scale/position, touch transform 0
and touch output `[[Auto]]`. SSH remained available. Owner confirmation of
physical rotation direction and tap alignment is still pending; this is not a
persistent-enable qualification. The only logged orientation was transform 1.

Private test artifacts: `/home/menno/myron-rotation-20261029/` on the phone;
unit `myron-rotation-trial-20261029.service`. No kernel, firmware, boot, audio,
production service enablement or persistent display configuration changed.

### Rotation direction and touch accepted; settling refinement

The owner confirmed the second attended trial worked, including rotation and
touch alignment, then requested a delay and flat-on-desk deadzone. Its journal
recorded transforms 3 and 0 and successful timed restoration.

The next candidate uses SensorProxy's existing AccelerometerTilt property:
face-up, face-down and uncertain tilt hold the current rotation. Vertical or
tilted-up orientation must remain stable for 700 ms before applying. A change,
flat placement, rotation lock or proxy loss cancels pending rotation. On older
proxies without a tilt property, settling still applies but flat detection is
reported unavailable. Eight focused checks pass. This refinement is staged in
the isolated test directory, not installed or persistently enabled. Trial r3
uses the same independent portrait restoration; physical desk/settling
acceptance remains pending.

### Rotation controls trial (2026-10-29)

Basic display rotation and rotated touch alignment were accepted by the owner
on Omarchy. The controller now waits 700 ms for a stable orientation and holds
rotation when SensorProxy reports flat or uncertain tilt. Those refinements
still need explicit physical acceptance.

Rotation controls are deployed for an attended 180-second test on the same
Omarchy boot. Quick settings has a current-rotation lock and a details arrow.
The details panel controls all four allowed orientations, optional hints and
a 2–15 second hint lifetime (default 5). A hint appears at bottom right over
applications; tapping it rotates once without clearing the rotation lock.
Ignoring it preserves the screen orientation. PIN, pocket protection and a
dark screen suppress requests. No above-lock layer rule was added.

The Myron image composer now carries the control wrapper and new plugin.
Fifteen focused controller checks passed; the settings preview rendered and
the live plugin loaded without a Rotation.qml error. Production autorotation
remains disabled. The transient unit is
`myron-rotation-settings-trial-20261029.service`, with RuntimeMaxSec=180 and the
existing captured portrait/touch restore in ExecStopPost. Live runtime reports
an available accelerometer and current transform 0 with rotation locked.
UI and physical hint acceptance remain pending. Polling cost must be reduced
before enabling the production service; this trial is not a battery result.

System-file backups: `/var/lib/myron-rotation-settings-before-20261029`.
New files are recorded in that directory's `new-files`. User shell settings and
previous rotation preferences are backed up under
`~/myron-rotation-settings-20261029/user-before`. To stop the trial immediately,
use `systemctl --user stop myron-rotation-settings-trial-20261029.service`;
its ExecStopPost restores the captured portrait baseline. To roll back files,
restore the backed-up paths, remove only the recorded new files, restore the
user shell.json and previous rotation preferences, and reload the shell while
unlocked. No boot image, kernel, audio service or persistent sensor startup
was changed.

Owner acceptance follow-up: the rotation settings menu works. After initially
reporting that the floating button did not respond, the owner retested and
explicitly confirmed that it works. No tap-path fix was applied. The follow-up
unit `myron-rotation-hint-check-20261029.service` uses a 600-second limit and the
same portrait restore. This confirms practical use of the hint; it does not
qualify idle power or persistent service startup. USB was disconnected for
free movement and reconnected afterward. The laptop USB profile needed
reactivation after reconnect; no phone reboot was required.

Owner-requested hint placement adjustment: anchor the button to the physical
panel corner corresponding to bottom-right in upright portrait. Transform 0
uses bottom-right, 1 top-right, 2 top-left and 3 bottom-left. The 96/28-pixel
safe-area insets rotate with that corner. The glyph remains readable in the
current screen orientation. QML formatting validation passed; physical corner
acceptance is pending. Prior QML is backed up as
`Rotation.before-physical-corner.qml` in the system backup directory.

The owner rejected the first physical-corner mapping: the button still moved.
Corrected the quarter turns to use inverse output coordinates: transform 1
bottom-left and transform 3 top-right (0 bottom-right, 2 top-left unchanged).
QML IPC state now exposes the transform and chosen corner for diagnosis.
This correction still requires physical acceptance; the initial mapping is
not a verified result.

### Rotation settings and brightness toggle restyle (2026-10-29)

The rotation settings panel now matches the quick-settings Wi-Fi panel: a
popup card over a scrim, a back glyph, an Auto-rotate switch row, one switch
row per allowed orientation (a phone glyph turned to that orientation), a
Suggest rotation switch and a 2–15 second stepper that is disabled while
suggestions are off. Controller commands and policy are unchanged. The
quick-settings Auto brightness bar was replaced by the brightness slider's
glyph: an accent-filled auto-brightness glyph means Auto; tapping it switches
mode, and dragging the slider still switches to Manual.

Omarchy rendering was checked by screenshot; physical tap acceptance is
pending. sudo needed an interactive password, so the trial is a user-level
override: `~/.config/omarchy/plugins/omamobile.rotation` and
`omamobile.quicksettings` are directory copies instead of symlinks. Rollback:
replace each with the symlink target recorded in
`~/myron-rotation-ui-fix-20261029/<plugin>.symlink` and restart the shell
while unlocked. System files were not changed.

### Quick-settings rotation tile: persistent controller (2026-10-29)

The owner reported that the quick-settings rotation tile did nothing. Cause:
both attended controller units had reached their 10-minute RuntimeMaxSec, so
`omamobile-rotation status` reported `available: false, running: false` and
the tile's toggle returned early. The tile code itself was correct.

To make a always-on controller acceptable, `lib/autorotate.py` now checks the
pocket marker and `bl_power` first and spawns no process while the panel is
dark; while lit it caches the forked `hyprctl -j monitors` and lock-state
queries for 2 s (a rotation or hint acceptance always re-checks fresh), and
rewrites the runtime JSON only on a state change or a 1 s heartbeat (the
shell's freshness window is 3 s). 18 focused controller tests pass, three of
them new for these paths. Measured on Omarchy with the panel lit: 1.06 s CPU
per 60 s, against 36.8 s per 10 minutes in the earlier trial (about 3.5x
less). Dark-panel cost and battery impact are not yet measured.

Deployed without sudo as the enabled user unit
`~/.config/systemd/user/myron-autorotate.service`, running a user-owned copy in
`~/myron-rotation-service-20261029/`; its ExecStopPost restores transform 0.
The packaged `omamobile-autorotate.service` stays disabled. Through the shell
IPC, the tile toggled Current locked to Auto-rotate and back, and the
controller followed. Physical tap acceptance is pending. Rollback:
`systemctl --user disable --now myron-autorotate.service` and remove the unit
file.

### Boot start and image reproduction (2026-10-29)

This supersedes the manual-only rule above for images composed with the
private assets. `myron-sensor-stage.service` now has an `[Install]` section.
It waits at most 60 s for `/dev/fastrpc-adsp-secure` (`$$` escaping, because
systemd expands `$` in Exec lines) within `TimeoutStartSec=105`. It still
requires the enable marker and the registry. The composer writes the marker and
both enable links only inside its sensor-runtime branch. The autorotate user
unit runs `--monitor DSI-1` and restores transform 0 in ExecStopPost.
`tests/myron-sensors` checks this contract. The manual runbook remains valid
for images without the assets and for diagnosis. Reboot acceptance is
pending.
