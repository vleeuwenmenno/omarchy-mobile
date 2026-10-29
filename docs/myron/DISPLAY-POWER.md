<!-- SPDX-License-Identifier: MIT -->
# Myron display wake and ambient brightness

Updated 2026-10-28. Acceptance is on the installed Omarchy v60 system, not
postmarketOS. This change does not reboot, replace the kernel, load sensor
drivers, modify boot images or start the audio stack.

## Owner policy

Only the power-button path may wake a dark display for now. Touch, pointer
motion, ordinary keyboard activity and ordinary software wake requests must
not light it. Pocket-safe double-tap wake is deferred until broader hardware
support is further along. This is normal session behavior, not a security
boundary against processes that can directly control Hyprland as the user.

The owner reported accidental backpack wake, heat and approximately 40%
battery loss in three hours. That report motivates the fix; it does not prove
that the panel was the only cause. Suspend, modem/DSP power and long-duration
screen-off drain remain unqualified. At reconnect, battery temperature was
38.5°C and the panel was off.

## Implementation and limits

- `omamobile-display` is an opt-in helper. Myron selects `panel0-backlight`
  through `/etc/omamobile/display.json`; other devices without that file keep
  manual brightness behavior. No device-specific sensor API is used.
- Patch `0016-display-bounded-wake-and-touch-policy.patch` integrates it into
  Omarchy's existing brightness command. A transition lock covers off/on,
  ambient precheck, panel power and touch restoration. The existing lock/PIN
  implementation is preserved.
- While dark, Hyprland's touchscreen input is disabled at libinput. Its
  mouse/key DPMS wake settings are disabled. Loading the phone configuration
  again reads the actual panel state, so a reload does not re-enable dark
  touch. Power wake restores touch, including the already-DPMS-on branch.
- The power-key handler authorizes a short-lived wake and calls the display
  command before rearming the lock timer. Ordinary software wake is rejected
  while dark. Power from the screensaver also uses the authorized path.
- Automatic range is **3–55%**. Minor changes use gentle rates starting at
  **2 percentage points/second up** and **1.5 down**. Large target errors or a
  large recent light change smoothly increase the rate up to **5 points/second**
  in either direction. The recent baseline spans about three seconds.
  Filtering operates on the logarithmic brightness target, rather than raw
  lux, with a 0.3–2 second response depending on change size. A brief bright
  reading therefore does not dominate raw-lux averaging long after darkness.
- Ramping uses 20 ms steps capped at **0.1 percentage point per write**.
  Fractional progress survives integer sysfs rounding, including lower-resolution
  backlights. A 0.25-point deadband reduces small fluctuations; exact minimum
  and maximum targets continue to the endpoint. Direction reversals cannot
  continue moving toward an obsolete target. Steady, manual and dark states
  retain 500 ms polling.
- Quick settings reads fractional actual brightness every 500 ms only while
  open, skipping dragging and rejecting read results older than a manual edit.
  Manual slider changes override automatic adjustment until screen-off, or
  `omamobile-display auto` explicitly resumes it. Values outside the automatic
  range ramp back gradually. Only off-screen wake preparation may change
  brightness immediately because the panel is dark.
- Wake requests attempt a fresh ambient reading for 1.2 seconds. Only a
  post-claim signal in lux, with a finite nonnegative value, is accepted.
  Fresh readings are capped at **15%** for wake. Missing/late readings use
  **3%**, then ramp once valid data arrives. The outer process timeout and
  fallback keep wake bounded. No cached reading is claimed to be fresh.
- The user service holds only the light sensor while lit, releases it when
  dark or manually overridden, and stops changing brightness when data is
  invalidated or the sensor service disappears. A timed-out claim is still
  released because it may have completed on the server. Sensor foundation
  startup remains a separate, manual guarded operation.
- The existing power-key blackout is coordinated with the daemon. It retains
  the secure-lock wait and no longer restores an old level after panel-off,
  which could overwrite a concurrent wake precheck.

## Deployment and recovery

The live changes were staged in `/home/menno/myron-display-20261028` and backed
up in `/var/lib/myron-display-before-20261028`. The backup contains original
production files, the patch-manager state and an `installed.json` manifest.
The normal patch manager applied the new patch and changed only the brightness
script. The user service was enabled for the existing graphical session.
Hyprland configuration reloaded without errors. No shell restart was needed.

Source locations:

1. `packages/omamobile-shell/bin/omamobile-display` and `omamobile-keys`.
2. `packages/omamobile-shell/hypr/phone.lua`, quick-settings slider and user unit.
3. `packages/omamobile-omarchy/patches/0016-display-bounded-wake-and-touch-policy.patch`.
4. `device/myron/hardware-test-overlay/etc/omamobile/display.json`.
5. `tools/myron-dev-image-compose` carries the matching helper, hook and unit
   into subsequent development images. That updated composition path has
   syntax validation; no new image was built for this change.

Inspect on the phone as the graphical user:

```sh
omamobile-display status
systemctl --user status omamobile-display.service
hyprctl getoption input:touchdevice:enabled
```

Emergency wake through SSH, with the graphical session environment available:

```sh
omamobile-display authorize-wake
omarchy-brightness-display on
```

To pause automatic brightness without restoring touch wake:

```sh
systemctl --user disable --now omamobile-display.service
```

For a full rollback, stop/disable that user service, remove patch 0016 from
the installed series, run `sudo omamobile-omarchy-patches apply`, restore the
backed-up keys/phone.lua/QuickSettings.qml, and remove the added display config,
helper and unit. Reload Hyprland and the user unit manager. Do not run the patch
manager's blanket `restore` command: that would remove unrelated phone fixes.
The backup deliberately preserves the original touch-wake behavior; restoring
it also restores the backpack-wake risk reported by the owner.

## Evidence and remaining acceptance

- Owner physically confirmed: taps/swipes on the dark screen do not wake it;
  the power button does wake it.
- Live configuration reported touchscreen input false while off and true
  while on. PIN lock remained `secure=true` throughout the bounded test.
- An ordinary software wake was rejected; `bl_power` remained 4.
- On-device automatic mode received real 29.1-lux and 6.4-lux samples. The
  latter drove a measured gradual ramp from 3% to 5.6% after wake. Pre-wake light
  claims timed out while dark, including a separate 4-second diagnostic;
  therefore the conservative fallback is necessary on this boot.
- Focused tests cover bounds/ramp rates, wake authorization, fallback,
  already-lit idempotence, invalid settings and stopping the ramp after
  sensor loss. QML and shell syntax checks passed. The final hardware run
  also confirmed the ramp with sensor events accepted only while claimed,
  then returned to panel-off with touch disabled and the PIN lock secure.
- Physical cover/uncover response, both ramp directions across changing
  lighting, manual slider feel and long-duration battery savings still need
  observation. No claim is made that system suspend or backpack drain is fixed.

Implementation reference: Hyprland's
[touchdevice and DPMS options](https://wiki.hypr.land/Configuring/Basics/Variables/).
The installed 0.56.2 source confirms that disabling touchscreen input selects
`LIBINPUT_CONFIG_SEND_EVENTS_DISABLED`.

### Smaller-step follow-up

The owner confirmed wake-time adjustment is visibly working. The follow-up
uses smaller, more frequent writes at the same overall rise/fall limits and
keeps the quick-settings slider synchronized while open. Its three changed
live files are backed up in `/var/lib/myron-display-before-smooth-20261028`.
The plugin rescan retained cached QML, so one supported shell restart was
required while the owner session was unlocked. No compositor restart or reboot
was used.

Live acceptance: while quick settings remained open, a temporary 0.4-point
brightness change was observed through its public state IPC, followed by
restoration. The slider tracked actual fractional values (11.2861%, then
11.1274% after restoration). During automatic settling a single downward
change was 0.0488 percentage point, consistent with the new smaller step cap.
The manual-override state was preserved. Four focused display tests and both
changed QML parse checks passed.

### Adaptive-response follow-up

The owner reported that large light changes adjusted too slowly and covering
appeared to stop near 13%. The first capture command failed; the corrected
capture found manual brightness at 1%, with automatic sampling paused. That
interval cannot validate the covered-sensor minimum. A 20-lux reading maps to
about 11.4%; the previous 2-point deadband could leave the actual value near
13%. No sensor offset or calibration has been inferred from this report.

The adaptive controller replaces the slow raw-lux average and fixed rates.
Seven focused tests cover large transitions, saturated endpoints, small changes,
quantized 4095-count panels, reversals, wake-write reconciliation and sensor
loss, as well as configuration and wake authorization. Review found the need
to retain fractional progress; this was fixed and tested before deployment.
The helper and config backup is `/var/lib/myron-display-before-adaptive-20261028`.
Deployment required only restarting the brightness user service, with no shell
restart or reboot. Physical bright/dark response and the covered minimum remain
subject to actual lux measurements; an off display deliberately holds no claim.

### High-brightness warning and response refinement

The brightness slider marks the 80–100% track segment in red. Above 80%, its
thumb and percentage also become red, and a short outdoor/high-battery-use hint
appears. Other sliders retain their original colors. A local render checked
75%, 80% and 90% without driving the phone panel to high brightness.

After the owner reported the adaptive response was still slow, live readings
showed a transition from 7.9 to 19.8 lux and exposed slow polling during filter
catch-up. The controller now retains fast cadence until that catch-up completes,
subtracts computation/write time from the frame delay, and reaches faster
rates for moderate target changes. Myron's gentle rates are now 2 points/second
up and 1.5 down, increasing toward the existing 5-point cap for larger changes.
The per-write 0.1-point cap remains. Eight focused checks passed, including a
regression check for premature idle polling. Physical feel remains for owner
confirmation. Backup: `/var/lib/myron-display-before-warning-20261028`.

The warning was also verified in a live Omarchy screenshot at 9%: the muted
red high-brightness segment is visible, and the active low-brightness fill and
thumb keep their normal colors. Only the local preview exercised 90%, avoiding
an unnecessary high-brightness phone test. One unlocked shell restart loaded
the QML; the brightness service remains active.

Owner feedback after the response refinement and red-zone deployment:
“This is 10x better!” Preserve this tuning as the accepted usability baseline.
This feedback does not separately qualify the covered-sensor minimum,
long-duration battery drain or pre-wake sensor availability.

## Pocket protection (owner-accepted on Omarchy, 2026-10-28)

The owner selected a check on **every physical power-button wake**, including
wakes to the PIN screen. The new `omamobile-pocket` helper reads SensorProxy
proximity after a bounded claim and settling interval, on the same connection,
then releases it. It never starts sensor firmware or the sensor service.
SensorProxy supplies no measurement timestamp: this is its latest reported
state, not proof of a fresh hardware sample. Unknown/error is guarded with an
honest “Proximity unavailable” message. Physical Near/Far wake qualification
is required; this is an accidental-input heuristic, not an authentication gate.

Near shows a dim, opaque shield on every output. A deliberate horizontal swipe
must finish and release before the helper accepts its token. It dismisses only
the shield. The existing PIN session lock remains, with explicit input and
PAM completion gates while protected. Calls and the keyboard controls are
hidden; a temporary Hyprland submap suppresses other shortcuts. Power blanks
the guard and consumes that press/release. A covered-to-uncovered change does
not dismiss an already displayed guard.

A systemd user timer expires after five seconds, with 50 ms scheduling
accuracy. Its helper validates the wake token under the display-transition
lock before disabling touch and blanking. A separate supervised worker checks
shield coverage; loss blanks the screen. Its 12-second maximum runtime and
ExecStopPost expiry are additional recovery paths. Old timeout tokens cannot
blank a later wake. Automatic and manual brightness writes cannot brighten an
active guard. The optional continuous-claim policy below supersedes the original
claim-on-wake lifecycle when explicitly enabled.

The **Pocket protection** quick-settings tile persists its setting per user at
`~/.local/state/omamobile/pocket.json`. It is available on devices opting into
`/etc/omamobile/display.json`; the implementation contains no Myron sensor IDs.
The profile and setup helper install the plugin for new and existing users.
The Myron image composer carries the same helper, units and patch 0017.

Deployment backup: `/var/lib/myron-pocket-before-20261028`, containing prior
files, absent/symlink records and the entire Omarchy patch-manager state.
Private deployment staging is `/home/menno/myron-pocket-20261028` on the phone.
Initial deployment deliberately leaves the feature disabled until UI readiness
and hardware checks pass. This does not change the accepted power-only wake
policy or brightness curve.

Emergency SSH recovery, in the graphical user's environment: run
`omarchy-brightness-display off`, then `omamobile-pocket off`. Power can then
wake normally. Do not remove the runtime guard state while a shield is lit.
A complete file rollback restores the recorded files and patch-manager state
from the backup, removes only recorded newly added files, reloads user units
and Hyprland, and restarts the shell only while unlocked.

Validation so far: four focused token/deadline race checks, eight existing
brightness checks, QML parsing and offscreen UI load passed. Initial Omarchy
installation changed only the two intended upstream files through patch 0017;
new shield IPC and lock-input IPC loaded, Hyprland reported no config errors,
and the brightness service remained active. Physical Near/Far wake, deliberate
swipe, five-second screen-off and toggle acceptance remain pending.

### Final helper update (2026-10-28)

On the same Omarchy boot, installed the reviewed power-key marker cleanup,
independent existing-user plugin migration, and best-effort recovery cleanup.
The guard worker starts asynchronously to avoid waiting on the display
transition lock during preparation; an active dark preparation cannot be
replaced by another wake. Six focused guard tests and shell syntax checks
passed, and all three installed helper hashes match the tested sources.
Backup: `/var/lib/myron-pocket-fixes-before-20261028`. No reboot or shell
restart was needed. Pocket protection was already enabled when reconnecting;
physical covered-wake, swipe and timeout acceptance remains pending.


### Continuous sensor claims (owner request, 2026-10-28)

The owner requested keeping proximity, compass and ambient light active to
avoid restarting their measurements for each UI request. The opt-in marker is
`/etc/omamobile/sensors-keepalive`; per-sensor user units retain SensorProxy
claims and release them on shutdown. They do not start firmware or SensorProxy.
A runtime heartbeat records the D-Bus owner and claim continuity. It is **not**
a hardware sample timestamp or proof of sensor accuracy. Wake reads reject
missing, expired, newly started or different-owner heartbeats.

On the same verified Omarchy boot, Proximity and Compass claims remained active
with zero restarts. Light's five-second claim timed out while the panel was off;
the repeating Light restart loop was stopped rather than repeated unchanged.
The next discriminating test is starting Light with the panel on, then checking
whether its existing claim survives panel-off. Do not report all three sensors
working continuously until that passes. Screen-off remained `bl_power=4` and
battery temperature was 32.5 C at this check. No battery-life improvement or
acceptable overnight power cost has been established for continuous claims.

Installed-file backup: `/var/lib/myron-sensor-keepalive-before-20261028`.
Staging: `/home/menno/myron-sensor-keepalive-20261028`. Reversal stops and disables
the three instance units, restores the backed-up display/pocket helpers and
removes only newly installed files listed in the backup records. Restore the
previous brightness helper before removing keepalive integration.


Light subsequently claimed successfully while the owner held the PIN screen
on: 6.19 lux. After the owner blanked the display, all three services remained
active with zero restarts and Light's heartbeat continued. Light then reported
0 lux. This establishes retained claims, not yet correct off-screen readings.
The keepalive helper now waits for a normally lit panel before its initial
Light claim, avoiding the demonstrated dark-start timeout loop. It never
turns the panel on itself; existing claims are not restarted for this change.


### Owner acceptance: covered wake, timeout and swipe

The owner confirmed: “IT WORKS AS I EXPECTED IT SHOULD WORK!” on the same
Omarchy boot. The bounded capture independently recorded:

- Proximity Near while the panel was off.
- Covered wake entering `blocked` with the panel lit at 157.2 seconds.
- Timeout recovery at 162.3 seconds and panel-off observed at 162.5 seconds:
  approximately five seconds, within the capture's 250 ms sampling resolution
  and the non-atomic readback of panel/guard state.
- A second covered wake at 164.8 seconds, dismissed by swipe at 166.0 seconds.
- Proximity changing to Far, followed by an unguarded wake at 170.1 seconds.

The requested pocket-wake behavior is accepted for the current Omarchy
baseline. Do not repeat these checks merely to reconfirm them. No unlock is
performed by the guard helper; separate lock security auditing was not part
of this physical observation. Continuous off-screen light/compass accuracy,
long-term battery cost and across-boot sensor foundation startup remain
unqualified. The private trace is
`/home/menno/myron-sensor-keepalive-20261028/covered-wake.jsonl` on the phone.

### Omarchy visual alignment (2026-10-28)

Deployed a presentation-only Pocket.qml update: square track and handle,
two-pixel border, Omarchy's configured font, and live foreground/background/
accent/muted palette roles. Gesture thresholds, input gates and timeout logic
are unchanged. QML parsing and offscreen rendering passed; the unlocked shell
reloaded successfully and plugin IPC responded. Installed/source SHA-256:
`5a3e6017de932166dcb9073797d827d66dce0db5837bacd78833797a5d1cb5b9`.
Prior QML: `/var/lib/myron-pocket-before-blocky-20261028.qml` on the phone.

### Auto brightness control (2026-10-29)

Quick settings now has an Auto brightness toggle above the slider. Slider
changes call the existing manual command; the toggle reflects the controller's
runtime state instead of a separate UI preference. Selecting Auto clears the
manual override and resumes ambient control. Turning Auto off retains the
current brightness. The mode survives screen-off and wake within the session;
the existing conservative wake brightness cap remains, including in Manual.

Deployed on Omarchy with backups in
`/var/lib/myron-auto-brightness-before-20261029`. Nine focused display tests
passed, including manual-mode preservation during safe wake, and QML parsed.
A live 7% manual command showed automaticBrightness=false in quick settings;
Auto resumed mode=auto with 5.30 lux and automaticBrightness=true. Physical
toggle/slider interaction acceptance remains pending. No reboot or change to
power-button-only wake was required.
