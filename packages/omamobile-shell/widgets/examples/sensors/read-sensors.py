#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Bounded SensorProxy snapshots/streams; all claims share one connection.

Idle: one coarse snapshot. Fast: cached D-Bus updates at 5 Hz for at most 60s.
No firmware access, device-specific paths, calibration or privileged commands.
"""
import argparse
import json
import math
import os
import shutil
import signal
import subprocess
import time

import gi
gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib

NAME = "net.hadess.SensorProxy"
PATH = "/net/hadess/SensorProxy"
SENSORS = (
    ("Orientation", PATH, NAME, "HasAccelerometer", "Accelerometer", "AccelerometerOrientation"),
    ("Light", PATH, NAME, "HasAmbientLight", "Light", "LightLevel"),
    ("Proximity", PATH, NAME, "HasProximity", "Proximity", "ProximityNear"),
    ("Compass", PATH + "/Compass", NAME + ".Compass", "HasCompass", "Compass", "CompassHeading"),
)


def emit(data):
    print(json.dumps(data, allow_nan=False), flush=True)


class Reader:
    def __init__(self, stream, duration):
        self.stream, self.duration = stream, duration
        self.bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        self.claims, self.rows, self.values, self.changed = [], [], {}, set()
        self.loop = GLib.MainLoop()
        self.stopped = False
        self.session = None
        self.lock_command = shutil.which("omarchy-shell")

    def call(self, path, interface, method, args=None, name=NAME):
        return self.bus.call_sync(name, path, interface, method, args, None,
                                  Gio.DBusCallFlags.NO_AUTO_START, 1200, None)

    def props(self, path, interface, name=NAME):
        return self.call(path, "org.freedesktop.DBus.Properties", "GetAll",
                         GLib.Variant("(s)", (interface,)), name).unpack()[0]

    def session_allowed(self):
        """Fail closed if there is no active, unlocked graphical session."""
        login = "org.freedesktop.login1"
        if self.session is None:
            sessions = self.call("/org/freedesktop/login1", login + ".Manager",
                                 "ListSessions", name=login).unpack()[0]
            for _, uid, _, _, path in sessions:
                if uid != os.getuid():
                    continue
                values = self.props(path, login + ".Session", login)
                if values.get("Type") in ("wayland", "x11") and values.get("Active"):
                    self.session = path
                    break
        if not self.session:
            return False
        values = self.props(self.session, login + ".Session", login)
        if not values.get("Active") or values.get("LockedHint", True):
            return False
        # Omarchy's ext-session-lock does not currently mirror LockedHint.
        # Check its public IPC too. Only fast mode repeats this once a second.
        if self.lock_command:
            try:
                result = subprocess.run([self.lock_command, "lock", "isLocked"],
                                        capture_output=True, text=True, timeout=1)
                return result.returncode == 0 and result.stdout.strip() == "false"
            except (OSError, subprocess.TimeoutExpired):
                return False
        return True

    def stop(self):
        self.stopped = True
        self.loop.quit()
        return GLib.SOURCE_REMOVE

    def update(self, connection, sender, path, interface, signal_name, params):
        iface, values, invalidated = params.unpack()
        key = (path, iface)
        if key not in self.values:
            return
        self.values[key].update(values)
        for prop in invalidated:
            self.values[key].pop(prop, None)
        self.changed.update((path, prop) for prop in values)

    def frame(self):
        rows = []
        for row, spec in zip(self.rows, SENSORS):
            row = dict(row)
            label, path, interface, _, _, prop = spec
            if row["state"] != "waiting":
                rows.append(row)
                continue
            values = self.values.get((path, interface), {})
            value = values.get(prop)
            if value is not None and value != "undefined":
                if label in ("Light", "Compass"):
                    if not math.isfinite(float(value)) or value < 0:
                        rows.append(row)
                        continue
                    if label == "Compass" and not self.stream:
                        value = (round(value / 5) * 5) % 360
                    unit = values.get("LightLevelUnit", "") if label == "Light" else "°"
                    row["value"] = (f"{value:.1f} {unit}" if self.stream else f"{value:.0f} {unit}").strip()
                elif label == "Proximity":
                    row["value"] = "Near" if value else "Far"
                else:
                    row["value"] = str(value).replace("-", " ").capitalize()
                row["state"] = "updated" if (path, prop) in self.changed else "reported"
            rows.append(row)
        self.changed.clear()
        return {"rows": rows, "at": int(time.time() * 1000), "mode": "fast" if self.stream else "low"}

    def run(self):
        subscription = self.bus.signal_subscribe(
            NAME, "org.freedesktop.DBus.Properties", "PropertiesChanged", None,
            None, Gio.DBusSignalFlags.NONE, self.update)
        handlers = [GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, self.stop)
                    for sig in (signal.SIGTERM, signal.SIGINT)]
        timer = None
        try:
            if not self.session_allowed():
                emit({"suspended": True, "rows": []})
                return
            started = time.monotonic()
            for label, path, interface, capability, method, prop in SENSORS:
                row = {"label": label, "value": "Unavailable", "state": "unavailable"}
                self.rows.append(row)
                try:
                    values = self.props(path, interface)
                    self.values[(path, interface)] = values
                    if not values.get(capability, False):
                        continue
                    self.call(path, interface, "Claim" + method)
                    self.claims.append((path, interface, method))
                    row.update(state="waiting", value="Waiting for reading")
                except GLib.Error as error:
                    denied = "denied" in str(error).lower() or "authorized" in str(error).lower()
                    row.update(state="error", value="Access denied" if denied else "Service unavailable")
            if not self.claims:
                emit(self.frame())
                return
            last_check = time.monotonic()

            def tick():
                nonlocal last_check
                now = time.monotonic()
                if self.stream and now - last_check >= 1:
                    last_check = now
                    try:
                        allowed = self.session_allowed()
                    except GLib.Error:
                        allowed = False
                    if not allowed:
                        emit({"suspended": True, "rows": []})
                        return self.stop()
                emit(self.frame())
                if not self.stream or now - started >= self.duration:
                    return self.stop()
                return GLib.SOURCE_CONTINUE

            timer = GLib.timeout_add(200 if self.stream else 1200, tick)
            self.loop.run()
        finally:
            # Disconnection also releases claims if termination interrupts cleanup.
            for path, interface, method in reversed(self.claims):
                try:
                    self.call(path, interface, "Release" + method)
                except GLib.Error:
                    pass
            self.bus.signal_unsubscribe(subscription)
            for source in handlers + ([timer] if timer else []):
                if GLib.MainContext.default().find_source_by_id(source):
                    GLib.source_remove(source)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stream", action="store_true")
    parser.add_argument("--duration", type=int, default=60, choices=range(1, 61), metavar="1..60")
    args = parser.parse_args()
    try:
        Reader(args.stream, args.duration).run()
    except (GLib.Error, BrokenPipeError):
        # No retry loop or background service; the widget may try its next slow tick.
        try:
            emit({"error": "System sensor service unavailable", "rows": []})
        except BrokenPipeError:
            pass


if __name__ == "__main__":
    main()
