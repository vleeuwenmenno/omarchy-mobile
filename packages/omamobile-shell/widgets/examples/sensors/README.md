# Sensors widget

This home-screen widget uses the standard `net.hadess.SensorProxy` system-bus
interfaces, including the optional Compass interface. It contains no device
names, driver loading, privileged commands or location requests. Devices without
a provider or individual sensor show an unavailable state. Access follows the
provider's session policy; an SSH session can be denied even when the active
desktop user is allowed.

Low-power mode takes one 1.2-second snapshot every two seconds while its home
page is visible. Compass values use 5-degree steps and a simple dial. Claims
are released between snapshots; this does not keep the magnetometer claimed
throughout the idle interval. Cached values remain visible between snapshots.

Tap the dial or the speedometer icon at the top right for at most 60 seconds of updates at 5 Hz,
with 0.1-degree display formatting and more dial ticks. One helper holds the
claims and streams cached D-Bus updates; it does not spawn a helper per frame
or re-claim sensors five times per second. More displayed digits do not improve
the hardware's physical accuracy or guarantee a fresh sample on every frame.

Pause, page changes, covering applications, editing and panel-off activity
stop the helper through `host.active`. Existing home-screen panel polling has
a two-second resolution. The helper independently refuses an inactive or
locked graphical session and checks the public Omarchy lock IPC at startup
and once per second during fast mode (the lock currently does not mirror
logind's LockedHint). Failed lock checks suspend sampling. Fast mode does not
resume automatically after unlock or returning home. Idle snapshots resume
at the slow rate. Helper lifetime is also bounded by an external timeout
(10 seconds idle, 65 seconds fast); signals and normal completion release all
claims, and D-Bus disconnection releases them if cleanup is interrupted.
Values are kept only in widget memory. This bounds sampling work, not measured
whole-device battery consumption; another client may keep the sensors active.

The panel distinguishes unavailable, waiting, denied and reported values.
An accent-colored value changed during that snapshot; an unchanged reported
value alone does not prove a new physical sample. Orientation is discrete,
not raw X/Y/Z acceleration. The compass rotates its cardinal ring beneath a
fixed top bearing marker; the numeric heading comes unchanged from the provider.
It does not apply magnetic declination or promise true-north accuracy.

Board mount matrices belong in device configuration, not this universal widget.
Physically compare portrait/landscape, shade/unshade, near/far and heading before
claiming a device's sensors are qualified. Never treat a displayed zero or an
advertised capability alone as proof.
