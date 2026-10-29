# SPDX-License-Identifier: MIT
"""omamobile-location-usage: the system-bus wiring around model.Tracker.

Two bus connections, one job each:

* The monitor connection is made a bus monitor with only these match rules:
  GeoClue Client.Start method calls (the caller and the call's serial), method
  returns sent by GeoClue (see below), and the Client's and the Manager's
  PropertiesChanged signals (Active, DesktopId, InUse; the arg0 rule excludes
  the Location objects, so no Location signal ever reaches this process). A bus
  monitor cannot send, so it is used for nothing else.
* The ordinary connection owns org.omamobile.LocationUsage1, asks the bus for
  caller credentials and GeoClue's owner, and watches names.

Start success. A bus rule cannot match a reply's reply_serial, so the monitor
receives every method return GeoClue sends, which may carry a response body
(for example a Location property read). The filter below reads only message
headers of those: type, sender, destination, reply serial and signature. It
never calls get_body on a method return, never stores or logs a message, and
discards everything except a reply with an empty signature that answers an
outstanding Start. GDBus itself decodes the message in memory before the
filter runs; this code simply never looks at the body. Nothing subscribes to
Location objects, LocationUpdated or GetLocation.

It never calls GeoClue except one Properties.Get of Manager.InUse when GeoClue
was already running at startup, flagged NO_AUTO_START: activating GeoClue is
not this service's job. No polling: events, plus one slow prune timer.

Failure is loud. If the monitor or the ordinary connection closes, or the event
queue overflows, the service does not keep claiming to watch: overflow marks
coverage partial and ends open uses as unknown; a closed connection ends the
process with a failure status so systemd restarts it.
"""
import argparse
import collections
import json
import os
import signal
import sys
import threading

import gi

gi.require_version('Gio', '2.0')
from gi.repository import Gio, GLib  # noqa: E402

import model  # noqa: E402

BUS_NAME = 'org.omamobile.LocationUsage1'
OBJECT_PATH = '/org/omamobile/LocationUsage1'
INTERFACE = 'org.omamobile.LocationUsage1'
CALL_TIMEOUT_MS = 1500
PRUNE_SECONDS = 6 * 3600
EVENT_QUEUE = 512

INTROSPECTION = '''<node>
  <interface name="org.omamobile.LocationUsage1">
    <method name="GetStatus"><arg type="s" direction="out"/></method>
    <method name="GetHistory"><arg type="s" direction="out"/></method>
    <method name="ClearHistory"><arg type="u" direction="out"/></method>
  </interface>
</node>'''

CLIENT_INTERFACE = 'org.freedesktop.GeoClue2.Client'
MONITOR_RULES = [
    "type='method_call',interface='org.freedesktop.GeoClue2.Client',member='Start'",
    "type='method_return',sender='org.freedesktop.GeoClue2'",
    "type='signal',interface='org.freedesktop.DBus.Properties',member='PropertiesChanged',"
    "path_namespace='/org/freedesktop/GeoClue2/Client',arg0='org.freedesktop.GeoClue2.Client'",
    "type='signal',interface='org.freedesktop.DBus.Properties',member='PropertiesChanged',"
    "path='/org/freedesktop/GeoClue2/Manager',arg0='org.freedesktop.GeoClue2.Manager'",
]


def proc_identity(pid, uid, proc='/proc'):
    """The process name for a bus-reported PID, only when /proc agrees that
    the process belongs to the bus-reported UID (a recycled PID does not).
    comm only: no command line and no environment are ever read."""
    if not isinstance(pid, int) or pid <= 0:
        return None
    try:
        with open(f'{proc}/{pid}/status', encoding='utf-8', errors='replace') as handle:
            for line in handle:
                if line.startswith('Uid:'):
                    if int(line.split()[1]) != uid:
                        return None
                    break
            else:
                return None
        with open(f'{proc}/{pid}/comm', encoding='utf-8', errors='replace') as handle:
            return model.clean_label(handle.readline().strip())
    except (OSError, ValueError, IndexError):
        return None


class Service:
    def __init__(self, bus_address, state_dir, proc='/proc', uid_override=None):
        self.bus_address = bus_address
        self.proc = proc
        self.uid_override = uid_override   # tests only: a fixed caller UID
        self.loop = GLib.MainLoop()
        self.watches = {}
        self.queue = collections.deque()
        self.queue_lock = threading.Lock()
        self.scheduled = False
        self.gap = False                 # an event was dropped since the last 'lost' marker
        self.replies = model.AttemptTable(ttl=model.PENDING_TTL)   # worker thread only: header pre-filter
        self.failure = None
        self.store = model.HistoryStore(state_dir)
        self.tracker = None
        self.monitor = None
        self.bus = None

    # ------------------------------------------------------------ the bus

    def connect(self):
        flags = (Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT |
                 Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION)
        return Gio.DBusConnection.new_for_address_sync(self.bus_address, flags, None, None)

    def bus_call(self, conn, method, args, reply, timeout=CALL_TIMEOUT_MS,
                 name='org.freedesktop.DBus', path='/org/freedesktop/DBus',
                 interface='org.freedesktop.DBus', flags=Gio.DBusCallFlags.NONE):
        return conn.call_sync(name, path, interface, method, args,
                              GLib.VariantType(reply) if reply else None, flags, timeout, None)

    def lookup_owner(self):
        try:
            return self.bus_call(self.bus, 'GetNameOwner', GLib.Variant('(s)', (model.GEOCLUE_NAME,)), '(s)').unpack()[0]
        except GLib.Error:
            return None

    def credentials(self, sender):
        """UID and PID of a bus name, or None if the bus cannot say."""
        uid = pid = None
        try:
            data = self.bus_call(self.bus, 'GetConnectionCredentials', GLib.Variant('(s)', (sender,)),
                                 '(a{sv})').unpack()[0]
            uid, pid = data.get('UnixUserID'), data.get('ProcessID')
        except GLib.Error as error:
            if 'UnknownMethod' not in str(error):
                return None
            try:
                uid = self.bus_call(self.bus, 'GetConnectionUnixUser', GLib.Variant('(s)', (sender,)), '(u)').unpack()[0]
                pid = self.bus_call(self.bus, 'GetConnectionUnixProcessID', GLib.Variant('(s)', (sender,)), '(u)').unpack()[0]
            except GLib.Error:
                if uid is None:
                    return None
        if not isinstance(uid, int):
            return None
        return {'uid': uid, 'pid': pid if isinstance(pid, int) else None,
                'process': proc_identity(pid, uid, self.proc)}

    # ------------------------------------------------------------- watches

    def watch(self, name):
        if name in self.watches:
            return
        self.watches[name] = Gio.bus_watch_name_on_connection(
            self.bus, name, Gio.BusNameWatcherFlags.NONE, None,
            lambda conn, vanished: GLib.idle_add(self.on_vanished, vanished))

    def unwatch(self, name):
        watch_id = self.watches.pop(name, None)
        if watch_id is not None:
            Gio.bus_unwatch_name(watch_id)

    def on_vanished(self, name):
        if name in self.watches:
            self.tracker.name_vanished(name)
        return False

    # ------------------------------------------------------------- monitor

    def become_monitor(self):
        self.bus_call(self.monitor, 'BecomeMonitor', GLib.Variant('(asu)', (MONITOR_RULES, 0)), '()',
                      interface='org.freedesktop.DBus.Monitoring')
        self.monitor.add_filter(self.on_message, None)

    def on_message(self, conn, message, incoming, user_data=None):
        # GDBus worker thread: copy a few header fields, hand over to the main
        # loop, and drop the message so the monitor never tries to answer it.
        try:
            event = self.classify(message)
        except Exception:  # a malformed message may have been one we needed
            self.enqueue(None)
            return None
        if event:
            self.enqueue(event)
        return None

    def classify(self, message):
        kind = message.get_message_type()
        if kind == Gio.DBusMessageType.METHOD_CALL:
            if message.get_member() == 'Start' and message.get_interface() in (None, CLIENT_INTERFACE):
                sender, serial = message.get_sender(), message.get_serial()
                if sender and serial:
                    self.replies.add(sender, serial, {})
                return ('start', sender, message.get_destination(), message.get_path(), serial)
        elif kind == Gio.DBusMessageType.METHOD_RETURN:
            # HEADERS ONLY: the body of a reply (it can be a coordinate) is
            # never read. Only a reply with an empty signature that answers a
            # Start seen from this destination is passed on.
            destination, reply_serial = message.get_destination(), message.get_reply_serial()
            if message.get_signature() == '' and self.replies.pop(destination, reply_serial) is not None:
                return ('reply', message.get_sender(), destination, reply_serial)
        elif kind == Gio.DBusMessageType.SIGNAL and message.get_member() == 'PropertiesChanged' \
                and message.get_signature() == 'sa{sv}as':
            body = message.get_body().unpack()
            changed = {k: v for k, v in body[1].items() if k in ('Active', 'DesktopId', 'InUse')}
            return ('props', message.get_sender(), message.get_path(), body[0], changed)
        return None

    def enqueue(self, event):
        """Bounded and never silent: an event that does not fit (event None is
        one that could not be read) leaves a gap, and the tracker is told, in
        order, that events were lost."""
        with self.queue_lock:
            if self.gap and len(self.queue) < EVENT_QUEUE - 1:
                self.queue.append(('lost',))
                self.gap = False
            if event is None or len(self.queue) >= EVENT_QUEUE:
                self.gap = True
            else:
                self.queue.append(event)
            schedule = not self.scheduled
            self.scheduled = True
        if schedule:
            GLib.idle_add(self.drain)

    def drain(self):
        while True:
            with self.queue_lock:
                if self.queue:
                    event = self.queue.popleft()
                elif self.gap:
                    self.gap = False
                    event = ('lost',)
                else:
                    self.scheduled = False
                    return False
            try:
                self.dispatch(event)
            except Exception as error:  # one bad event must not stop monitoring
                print(f'event dropped: {type(error).__name__}', file=sys.stderr)
                self.tracker.events_lost()

    def dispatch(self, event):
        t = self.tracker
        if event[0] == 'lost':
            t.events_lost()
        elif event[0] == 'start':
            t.call_start(*event[1:])
        elif event[0] == 'reply':
            t.call_reply(*event[1:])
        else:
            _, sender, path, interface, changed = event
            if interface == 'org.freedesktop.GeoClue2.Manager':
                t.manager_changed(sender, path, interface, changed)
            else:
                t.properties_changed(sender, path, interface, changed)

    # ----------------------------------------------------------------- API

    def caller_uid(self, sender):
        if self.uid_override is not None:
            return self.uid_override
        data = self.bus_call(self.bus, 'GetConnectionCredentials', GLib.Variant('(s)', (sender,)),
                             '(a{sv})').unpack()[0]
        uid = data.get('UnixUserID')
        if not isinstance(uid, int):
            raise GLib.Error('no UID')
        return uid

    def on_method(self, conn, sender, path, interface, method, params, invocation):
        try:
            uid = self.caller_uid(sender)
        except GLib.Error:
            invocation.return_dbus_error('org.freedesktop.DBus.Error.AccessDenied', 'caller identity unavailable')
            return
        if method == 'GetStatus':
            invocation.return_value(GLib.Variant('(s)', (json.dumps(self.tracker.status(uid)),)))
        elif method == 'GetHistory':
            invocation.return_value(GLib.Variant('(s)', (json.dumps(self.tracker.history(uid)),)))
        elif method == 'ClearHistory':
            invocation.return_value(GLib.Variant('(u)', (self.tracker.clear(uid),)))
        else:
            invocation.return_dbus_error('org.freedesktop.DBus.Error.UnknownMethod', method)

    # ----------------------------------------------------------------- run

    def read_in_use(self):
        """One read of Manager.InUse when GeoClue was already running; never
        activates GeoClue."""
        try:
            value = self.bus_call(self.bus, 'Get', GLib.Variant('(ss)', ('org.freedesktop.GeoClue2.Manager', 'InUse')),
                                  '(v)', name=model.GEOCLUE_NAME, path='/org/freedesktop/GeoClue2/Manager',
                                  interface='org.freedesktop.DBus.Properties',
                                  flags=Gio.DBusCallFlags.NO_AUTO_START).unpack()[0]
            if isinstance(value, bool):
                self.tracker.manager_in_use = value
        except GLib.Error:
            pass

    def on_owner_changed(self, conn, sender, path, interface, signal_name, params):
        self.tracker.set_owner(params.unpack()[2] or None)

    def run(self):
        self.bus = self.connect()
        self.monitor = self.connect()
        self.tracker = model.Tracker(self.store, self.credentials, self.lookup_owner, self.watch, self.unwatch)
        self.bus.signal_subscribe('org.freedesktop.DBus', 'org.freedesktop.DBus', 'NameOwnerChanged',
                                  '/org/freedesktop/DBus', model.GEOCLUE_NAME, Gio.DBusSignalFlags.NONE,
                                  self.on_owner_changed)
        self.become_monitor()
        owner = self.lookup_owner()
        self.tracker.begin(owner)
        if owner:
            self.read_in_use()
        node = Gio.DBusNodeInfo.new_for_xml(INTROSPECTION)
        self.bus.register_object(OBJECT_PATH, node.interfaces[0], self.on_method, None, None)
        reply = self.bus_call(self.bus, 'RequestName', GLib.Variant('(su)', (BUS_NAME, 4)), '(u)').unpack()[0]
        if reply != 1:
            print(f'{BUS_NAME} is already owned', file=sys.stderr)
            return 1
        GLib.timeout_add_seconds(PRUNE_SECONDS, lambda: (self.tracker.prune(), True)[1])
        GLib.unix_signal_add(GLib.PRIORITY_HIGH, signal.SIGTERM, self.quit)
        GLib.unix_signal_add(GLib.PRIORITY_HIGH, signal.SIGINT, self.quit)
        self.bus.connect('closed', lambda *a: GLib.idle_add(self.connection_lost, 'the system bus connection'))
        self.monitor.connect('closed', lambda *a: GLib.idle_add(self.connection_lost, 'the bus monitor'))
        if self.bus.is_closed() or self.monitor.is_closed():
            self.failure = 'a bus connection'
            self.tracker.monitor_lost()
            print('a bus connection closed during start-up', file=sys.stderr)
        else:
            self.loop.run()
        self.tracker.shutdown()
        return 1 if self.failure else 0

    def connection_lost(self, what):
        """Neither connection closes in normal operation (a stop is a signal,
        not a close), so this is a failure: say it, stop claiming to monitor
        and exit non-zero so Restart=on-failure brings a working monitor back."""
        if not self.loop.is_running():
            return False
        self.failure = what
        print(f'{what} closed', file=sys.stderr)
        self.tracker.monitor_lost()
        self.loop.quit()
        return False

    def quit(self):
        self.loop.quit()
        return False


def main(argv=None):
    parser = argparse.ArgumentParser(prog='omamobile-location-usaged')
    parser.add_argument('--bus', help='bus address (default: the system bus)')
    parser.add_argument('--state-dir', default='/var/lib/omamobile-location-usage')
    parser.add_argument('--proc', default='/proc')
    parser.add_argument('--uid-override', type=int, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    address = args.bus or Gio.dbus_address_get_for_bus_sync(Gio.BusType.SYSTEM, None)
    os.makedirs(args.state_dir, mode=0o700, exist_ok=True)
    return Service(address, args.state_dir, args.proc, args.uid_override).run()
