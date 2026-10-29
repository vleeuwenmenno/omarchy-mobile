#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Rotate Hyprland's screen and touch input with the phone.

A client of iio-sensor-proxy's D-Bus API (net.hadess.SensorProxy, served on
cheetah by omamobile-sensor-proxy): it claims the accelerometer and, on every
AccelerometerOrientation change, sets the monitor's and the touchscreen's
transform through hyprctl, the way iio-hyprland does (normal 0, left-up 1,
bottom-up 2, right-up 3).

Rotation lock: while $XDG_STATE_HOME/omamobile/rotation-lock exists, the
screen stays as it is, with an accelerometer claim for optional hints; removing the file
applies the current orientation again (the quick-settings tile can toggle
it). Orientation must remain stable for 700 ms. When tilt is available, flat
or uncertain tilt holds the current rotation until the phone is raised.

  omamobile-autorotate [--monitor NAME] [--dry-run]
"""
import argparse
import contextlib
import fcntl
from pathlib import Path
import time
import uuid
import json
import os
import signal
import subprocess
import sys

import gi
gi.require_version('Gio', '2.0')
gi.require_version('GLibUnix', '2.0')
from gi.repository import Gio, GLib, GLibUnix  # noqa: E402

NAME = 'net.hadess.SensorProxy'
PATH = '/net/hadess/SensorProxy'
TRANSFORMS = {'normal': 0, 'left-up': 1, 'bottom-up': 2, 'right-up': 3}
SETTLE_MS = 700
# Hyprland and lock-state checks fork processes; reuse a result this long.
SAFE_CACHE_S = 2.0
PUBLISH_HEARTBEAT_S = 1.0
UPRIGHT_TILTS = ('vertical', 'tilted-up')


def log(msg):
    print(f'omamobile-autorotate: {msg}', file=sys.stderr, flush=True)


def lock_path():
    state = os.environ.get('XDG_STATE_HOME') or os.path.expanduser('~/.local/state')
    return os.path.join(state, 'omamobile', 'rotation-lock')


def settings_path():
    return Path(lock_path()).with_name('rotation.json')


def runtime_path():
    return Path(os.environ.get('XDG_RUNTIME_DIR', '/run/user/' + str(os.getuid()))) / 'omamobile-rotation.json'


def read_json(path):
    try:
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.' + uuid.uuid4().hex)
    tmp.write_text(json.dumps(value) + '\n')
    tmp.replace(path)


def settings():
    value = read_json(settings_path())
    allowed = value.get('allowed', list(TRANSFORMS))
    duration = value.get('hint_seconds', 5)
    if type(duration) is not int:
        duration = 5
    return dict(locked=os.path.exists(lock_path()),
                allowed=[x for x in allowed if isinstance(x, str) and x in TRANSFORMS] if isinstance(allowed, list) else list(TRANSFORMS),
                hints=value.get('hints', True) is True,
                hint_seconds=max(2, min(15, duration)))


@contextlib.contextmanager
def policy_lock():
    path = settings_path().with_suffix('.lock')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield


def control(command, payload):
    if command == 'status':
        state = read_json(runtime_path())
        live = 0 <= time.monotonic() - state.get('at', -100) < 4
        print(json.dumps(dict(settings(), available=live and state.get('available', False),
                              running=live, current=state.get('current'))))
        return 0
    with policy_lock():
        value = settings()
        if command in ('lock', 'unlock'):
            path = Path(lock_path())
            path.parent.mkdir(parents=True, exist_ok=True)
            if command == 'lock':
                path.touch()
            else:
                path.unlink(missing_ok=True)
        elif command == 'configure':
            patch = json.loads(payload)
            if set(patch) - {'allowed', 'hints', 'hint_seconds'}:
                raise ValueError('unknown rotation setting')
            if 'allowed' in patch and (not isinstance(patch['allowed'], list) or any(x not in TRANSFORMS for x in patch['allowed'])):
                raise ValueError('invalid allowed orientations')
            if 'hints' in patch and not isinstance(patch['hints'], bool):
                raise ValueError('hints must be boolean')
            if 'hint_seconds' in patch and (type(patch['hint_seconds']) is not int or not 2 <= patch['hint_seconds'] <= 15):
                raise ValueError('hint duration must be 2..15 seconds')
            value.update(patch)
            atomic_json(settings_path(), value)
        elif command == 'accept':
            atomic_json(runtime_path().with_name('omamobile-rotation-request.json'), {'token': payload})
        else:
            raise ValueError('unknown rotation command')
    return 0


def hyprctl(*args):
    return subprocess.run(['hyprctl', *args], capture_output=True, text=True, timeout=3)


def monitor(name=None):
    """Read the live output without changing its mode, position or scale."""
    try:
        result = hyprctl('-j', 'monitors')
        if result.returncode:
            return None
        mons = json.loads(result.stdout or '[]')
    except (json.JSONDecodeError, OSError, subprocess.TimeoutExpired):
        return None
    for m in mons:
        if not m.get('disabled') and (name is None or m.get('name') == name):
            return m
    return None


def rotation_lua(m, transform):
    name = json.dumps(m['name'])
    mode = f"{int(m['width'])}x{int(m['height'])}@{float(m['refreshRate']):.6f}"
    position = f"{int(m['x'])}x{int(m['y'])}"
    scale = float(m['scale'])
    return (f'hl.monitor({{ output = {name}, mode = "{mode}", position = "{position}", '
            f'scale = {scale:g}, transform = {transform} }}); '
            f'hl.config({{ input = {{ touchdevice = {{ transform = {transform}, output = {name} }} }} }})')


def apply(transform, name=None, dry_run=False):
    m = (dict(name=name or 'DSI-1', width=1200, height=2608, refreshRate=60,
              x=0, y=0, scale=1) if dry_run else monitor(name))
    if m is None:
        log('no monitor')
        return False
    lua = rotation_lua(m, transform)
    if dry_run:
        log(f'would run: hyprctl eval {lua!r}')
        return True
    try:
        r = hyprctl('eval', lua)
        if r.returncode != 0 or r.stdout.strip() != 'ok':
            log('rotation failed: ' + (r.stdout + r.stderr).strip())
            return False
    except (OSError, subprocess.TimeoutExpired) as error:
        log('rotation failed: ' + str(error))
        return False
    log(f"{m['name']}: transform {transform}")
    return True


class Rotator:
    def __init__(self, args):
        self.args = args
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION if args.session else Gio.BusType.SYSTEM, None)
        self.claimed = False
        self.current = None
        self.failed = False
        self.loop = None
        self.orientation = None
        self.tilt = None
        self.has_tilt = False
        self.pending = None
        self.settle_timer = 0
        self.hint = None
        self.last_hint_orientation = None
        self.safe = False
        self.available = False
        self.safe_cached = False
        self.safe_until = 0
        self.published = None
        self.published_at = 0
        self.policy = settings()
        self.last_policy = self.policy.copy()
        if not args.dry_run:
            m = monitor(args.monitor)
            self.current = m.get('transform') if m else None
        self.lifecycle_timer = GLib.timeout_add(500, self._tick)
        self.bus.signal_subscribe(NAME, 'org.freedesktop.DBus.Properties', 'PropertiesChanged',
                                  PATH, None, Gio.DBusSignalFlags.NONE, self._changed)
        Gio.bus_watch_name_on_connection(self.bus, NAME, Gio.BusNameWatcherFlags.NONE,
                                         self._appeared, self._vanished)
        lock = Gio.File.new_for_path(lock_path())
        self.lock_monitor = lock.monitor_file(Gio.FileMonitorFlags.NONE, None)
        self.lock_monitor.connect('changed', lambda *a: self._update_claim())

    def _call(self, method):
        try:
            self.bus.call_sync(NAME, PATH, NAME, method, None, None,
                               Gio.DBusCallFlags.NONE, 5000, None)
            return True
        except GLib.Error as e:
            log(f'{method}: {e.message}')
            return False

    def _prop(self, prop):
        try:
            v = self.bus.call_sync(NAME, PATH, 'org.freedesktop.DBus.Properties', 'Get',
                                   GLib.Variant('(ss)', (NAME, prop)), GLib.VariantType.new('(v)'),
                                   Gio.DBusCallFlags.NONE, 5000, None)
            return v.unpack()[0]
        except GLib.Error:
            return None

    def _appeared(self, conn, name, owner):
        self.available = bool(self._prop('HasAccelerometer'))
        if not self.available:
            log('the sensor proxy has no accelerometer')
            return
        self._update_claim()

    def _vanished(self, conn, name):
        self.claimed = False
        self.available = False
        self.hint = None
        self._cancel_pending()
        self.orientation = self.tilt = None

    def _session_safe(self, fresh=False):
        """Cheap file checks every tick; the forked hyprctl and lock queries
        only while the panel is lit, and at most every SAFE_CACHE_S unless
        `fresh`. A dark panel then costs no process spawns at all."""
        if self.args.session or self.args.dry_run:
            return True
        try:
            if read_json(Path(os.environ['XDG_RUNTIME_DIR']) / 'omamobile-pocket.json').get('active'):
                self.safe_until = 0
                return False
            config = read_json(Path('/etc/omamobile/display.json'))
            name = config.get('backlight', '')
            if name and '/' not in name and (Path('/sys/class/backlight') / name / 'bl_power').read_text().strip() != '0':
                self.safe_until = 0
                return False
            now = time.monotonic()
            if not fresh and now < self.safe_until:
                return self.safe_cached
            self.safe_cached = self._session_safe_slow()
            self.safe_until = now + SAFE_CACHE_S
            return self.safe_cached
        except (OSError, subprocess.TimeoutExpired):
            self.safe_until = 0
            return False

    def _session_safe_slow(self):
        try:
            m = monitor(self.args.monitor)
            if not m or not m.get('dpmsStatus'):
                return False
            result = subprocess.run(['omarchy-shell', 'lock', 'isLocked'], capture_output=True, text=True, timeout=1)
            return result.returncode == 0 and result.stdout.strip() == 'false'
        except (OSError, subprocess.TimeoutExpired):
            return False

    def _publish(self):
        if self.args.session or self.args.dry_run:
            return
        hint = self.hint if self.safe and self.policy['locked'] and self.policy['hints'] else None
        if hint and time.monotonic() >= hint['expires']:
            hint = None
        state = dict(available=self.available, current=self.current, hint=hint,
                     locked=self.policy['locked'], safe=self.safe)
        # The shell watches this file: rewrite it on a change, otherwise only
        # as a heartbeat inside the shell's 3-second freshness window.
        now = time.monotonic()
        if state == self.published and now - self.published_at < PUBLISH_HEARTBEAT_S:
            return
        self.published = state
        self.published_at = now
        atomic_json(runtime_path(), dict(state, at=now, at_wall=time.time()))

    def _tick(self):
        try:
            return self._tick_checked()
        except Exception as error:
            log(f'lifecycle failed: {error}')
            self.failed = True
            self.safe = False
            self.hint = None
            if self.loop:
                self.loop.quit()
            return GLib.SOURCE_REMOVE

    def _tick_checked(self):
        self.safe = self._session_safe()
        self.policy = settings()
        if self.policy != self.last_policy:
            self._cancel_pending()
            self.hint = None
            self.last_policy = self.policy.copy()
        if not self.safe:
            self._cancel_pending()
            self.hint = None
        self._update_claim()
        if self.claimed:
            self._queue_rotation()
        request_path = runtime_path().with_name('omamobile-rotation-request.json')
        with policy_lock():
            request = read_json(request_path)
            request_path.unlink(missing_ok=True)
            if (self.hint and request.get('token') == self.hint['token']
                    and time.monotonic() < self.hint['expires']
                    and self.orientation == self.hint['orientation']
                    and self.safe and self._session_safe(fresh=True)
                    and settings()['locked'] and self.orientation in settings()['allowed']
                    and (not self.has_tilt or self.tilt in UPRIGHT_TILTS)):
                self._rotate(self.orientation)
                self.hint = None
        self._publish()
        return GLib.SOURCE_CONTINUE

    def _update_claim(self):
        policy = settings()
        wanted = self.available and self.safe and (not policy['locked'] or policy['hints'])
        if not wanted:
            self._cancel_pending()
            if self.claimed:
                self.claimed = not self._call('ReleaseAccelerometer')
        elif not self.claimed:
            self.claimed = self._call('ClaimAccelerometer')
            if self.claimed:
                self.orientation = self._prop('AccelerometerOrientation')
                self.tilt = self._prop('AccelerometerTilt')
                self.has_tilt = self.tilt is not None
                self._queue_rotation()

    def _changed(self, conn, sender, path, iface, signal_name, params):
        prop_iface, changed, invalidated = params.unpack()
        if prop_iface != NAME or not self.claimed:
            return
        if 'HasAccelerometer' in invalidated or changed.get('HasAccelerometer') is False:
            self._cancel_pending()
            self.orientation = None
            self.available = False
            self.hint = None
            return
        if 'AccelerometerOrientation' in changed:
            self.orientation = changed['AccelerometerOrientation']
        elif 'AccelerometerOrientation' in invalidated:
            self.orientation = None
        if 'AccelerometerTilt' in changed:
            self.has_tilt = True
            self.tilt = changed['AccelerometerTilt']
        elif 'AccelerometerTilt' in invalidated:
            self.has_tilt = True
            self.tilt = None
        self._queue_rotation()

    def _cancel_pending(self):
        if self.settle_timer:
            GLib.source_remove(self.settle_timer)
        self.settle_timer = 0
        self.pending = None

    def _queue_rotation(self):
        target = TRANSFORMS.get(self.orientation)
        # Hold the existing rotation on a desk or while tilt is uncertain.
        # Proxies without a tilt property still get the settling delay.
        allowed = (not self.has_tilt or self.tilt in UPRIGHT_TILTS) and self.orientation in self.policy['allowed']
        if not self.claimed or not allowed or target is None:
            self._cancel_pending()
            return
        if self.policy['locked'] and self.last_hint_orientation == self.orientation:
            return
        if self.pending == self.orientation and self.settle_timer:
            return
        self._cancel_pending()
        self.pending = self.orientation
        self.settle_timer = GLib.timeout_add(SETTLE_MS, self._settled)

    def _settled(self):
        candidate = self.pending
        self.settle_timer = 0
        self.pending = None
        with policy_lock():
            policy = settings()
            if (not self.claimed or not self._session_safe(fresh=True) or candidate != self.orientation
                    or candidate not in policy['allowed']
                    or (self.has_tilt and self.tilt not in UPRIGHT_TILTS)):
                return GLib.SOURCE_REMOVE
            if TRANSFORMS[candidate] == self.current:
                self.last_hint_orientation = candidate
                self.hint = None
            elif policy['locked']:
                if policy['hints'] and self.last_hint_orientation != candidate:
                    self.last_hint_orientation = candidate
                    self.hint = dict(token=uuid.uuid4().hex, orientation=candidate,
                                     expires=time.monotonic() + policy['hint_seconds'],
                                     expires_wall=time.time() + policy['hint_seconds'])
            else:
                self._rotate(candidate)
                self.hint = None
        self._publish()
        return GLib.SOURCE_REMOVE

    def _rotate(self, orientation):
        t = TRANSFORMS.get(orientation)
        if t is None or t == self.current:
            return
        if apply(t, self.args.monitor, self.args.dry_run):
            self.current = t
        else:
            self.failed = True
            if getattr(self, "loop", None):
                self.loop.quit()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--control', choices=['status', 'lock', 'unlock', 'configure', 'accept'])
    ap.add_argument('payload', nargs='?', default='')
    ap.add_argument('--monitor', help='the output to rotate (default: the first one)')
    ap.add_argument('--dry-run', action='store_true', help='log the hyprctl calls instead of making them')
    ap.add_argument('--session', action='store_true', help='use the session bus (testing)')
    a = ap.parse_args(argv)
    if a.control:
        return control(a.control, a.payload)
    # Only one controller may own display rotation and hint requests.
    daemon_lock = runtime_path().with_suffix(".lock").open("w")
    fcntl.flock(daemon_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    rotator = Rotator(a)
    loop = GLib.MainLoop()
    rotator.loop = loop
    GLibUnix.signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, loop.quit)
    GLibUnix.signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, loop.quit)
    try:
        loop.run()
    finally:
        rotator._cancel_pending()
        GLib.source_remove(rotator.lifecycle_timer)
        rotator.safe = False
        rotator.hint = None
        try:
            rotator._publish()
        except OSError as error:
            log(f"final state publication failed: {error}")
        if rotator.claimed:
            rotator._call("ReleaseAccelerometer")
    return 1 if rotator.failed else 0


if __name__ == '__main__':
    sys.exit(main())
