# SPDX-License-Identifier: MIT
"""The daemon on a private D-Bus daemon (never the machine's own bus) against a
fake GeoClue that follows the 2.8.2 wire contract: only the connection that
created a client may call it (any other caller gets AccessDenied, which a bus
monitor still sees as a Start call), Start answers with an empty method return
and may emit Active=true before or after that reply, PropertiesChanged
broadcasts for Active/DesktopId, Manager.InUse. The tests check what the
daemon may and may not do on the bus as well as what it shows."""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import warnings

warnings.filterwarnings('ignore', category=DeprecationWarning)
import gi  # noqa: E402

gi.require_version('Gio', '2.0')
from gi.repository import Gio, GLib  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'lib'))
import model  # noqa: E402
import usage_daemon  # noqa: E402

DAEMON = os.path.join(HERE, '..', 'bin', 'omamobile-location-usaged')
CLI = os.path.join(HERE, '..', 'bin', 'omamobile-location')
GC = 'org.freedesktop.GeoClue2'
API = ('org.omamobile.LocationUsage1', '/org/omamobile/LocationUsage1', 'org.omamobile.LocationUsage1')
BUS_CONFIG = '''<!DOCTYPE busconfig PUBLIC "-//freedesktop//DTD D-BUS Bus Configuration 1.0//EN"
 "http://www.freedesktop.org/standards/dbus/1.0/busconfig.dtd">
<busconfig>
  <type>omamobile-location-usage-test</type>
  <listen>unix:path={path}</listen>
  <auth>EXTERNAL</auth>
  <policy context="default">
    <allow user="*"/>
    <allow own="*"/>
    <allow send_destination="*" eavesdrop="true"/>
    <allow receive_sender="*"/>
    <allow eavesdrop="true"/>
    <allow send_destination="org.freedesktop.DBus" send_interface="org.freedesktop.DBus.Monitoring"/>
  </policy>
</busconfig>
'''
FLAGS = Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION
IFACES = Gio.DBusNodeInfo.new_for_xml('''<node>
  <interface name="org.freedesktop.GeoClue2.Manager">
    <method name="GetClient"><arg type="o" direction="out"/></method>
    <property name="InUse" type="b" access="read"/>
  </interface>
  <interface name="org.freedesktop.GeoClue2.Client">
    <method name="Start"/><method name="Stop"/>
    <property name="DesktopId" type="s" access="readwrite"/>
    <property name="Active" type="b" access="read"/>
  </interface>
</node>''')


def wait_for(check, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        value = check()
        if value:
            return value
        time.sleep(0.02)
    return check()


class FakeGeoClue:
    """GeoClue on the bus. Records every method call made to it so a test can
    prove the daemon never called it (and never activated it)."""

    def __init__(self, address, allow=True):
        self.conn = Gio.DBusConnection.new_for_address_sync(address, FLAGS, None, None)
        self.allow = allow
        self.order = 'reply-first'     # or 'active-first': GeoClue emits Active before it replies
        self.hold_start = False        # emit Active=true, then keep the reply until release()
        self.held = []
        self.in_use = False
        self.calls = []
        self.clients = {}
        self.owner_id = None
        self.next = 1
        self.loop = GLib.MainLoop()
        ready = threading.Event()
        self.thread = threading.Thread(target=self._run, args=(ready,), daemon=True)
        self.thread.start()
        ready.wait(5)

    def _run(self, ready):
        self.conn.register_object('/org/freedesktop/GeoClue2/Manager', IFACES.interfaces[0],
                                  self._manager_call, lambda *a: GLib.Variant('b', self.in_use), None)
        self.conn.call_sync('org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus', 'RequestName',
                            GLib.Variant('(su)', (GC, 4)), None, Gio.DBusCallFlags.NONE, 2000, None)
        ready.set()
        self.loop.run()

    def _manager_call(self, conn, sender, path, iface, method, params, inv):
        self.calls.append(method)
        number = self.next
        self.next += 1
        client = f'/org/freedesktop/GeoClue2/Client/{number}'
        self.clients[client] = {'Active': False, 'DesktopId': '', 'owner': sender}
        conn.register_object(client, IFACES.interfaces[1], self._client_call,
                             lambda c, s, p, i, name: GLib.Variant('b' if name == 'Active' else 's',
                                                                   self.clients[p][name]),
                             self._set)
        inv.return_value(GLib.Variant('(o)', (client,)))

    def _set(self, conn, sender, path, iface, name, value):
        self.clients[path][name] = value.unpack()
        self.broadcast(path, 'org.freedesktop.GeoClue2.Client', {name: value})
        return True

    def _client_call(self, conn, sender, path, iface, method, params, inv):
        self.calls.append(method)
        if sender != self.clients[path]['owner']:
            inv.return_dbus_error('org.freedesktop.DBus.Error.AccessDenied', 'Access denied')
            return
        if method == 'Start' and not self.allow:
            inv.return_dbus_error('org.freedesktop.DBus.Error.AccessDenied', 'denied')
            return
        active = method == 'Start'
        self.clients[path]['Active'] = active
        announce = lambda: self.broadcast(path, 'org.freedesktop.GeoClue2.Client',
                                          {'Active': GLib.Variant('b', active)})
        if method == 'Start' and self.hold_start:
            announce()
            self.held.append(inv)
        elif self.order == 'active-first':
            announce()
            inv.return_value(None)
        else:
            inv.return_value(None)
            announce()
        self.set_in_use(any(c['Active'] for c in self.clients.values()))

    def release(self):
        """Send the withheld Start replies."""
        held, self.held = self.held, []
        for inv in held:
            inv.return_value(None)

    def set_in_use(self, value):
        if value != self.in_use:
            self.in_use = value
            self.broadcast('/org/freedesktop/GeoClue2/Manager', 'org.freedesktop.GeoClue2.Manager',
                           {'InUse': GLib.Variant('b', value)})

    def broadcast(self, path, interface, changed):
        self.conn.emit_signal(None, path, 'org.freedesktop.DBus.Properties', 'PropertiesChanged',
                              GLib.Variant('(sa{sv}as)', (interface, changed, [])))

    def stop(self):
        self.loop.quit()
        if not self.conn.is_closed():
            self.conn.close_sync(None)


class App:
    """A GeoClue client program, as its own bus connection."""

    def __init__(self, address, desktop_id='org.example.Maps'):
        self.conn = Gio.DBusConnection.new_for_address_sync(address, FLAGS, None, None)
        self.desktop_id = desktop_id
        self.path = self.call(GC, '/org/freedesktop/GeoClue2/Manager', 'org.freedesktop.GeoClue2.Manager',
                              'GetClient', None, '(o)').unpack()[0]

    def call(self, name, path, interface, method, args, reply=None):
        return self.conn.call_sync(name, path, interface, method, args, GLib.VariantType(reply) if reply else None,
                                   Gio.DBusCallFlags.NONE, 10000, None)

    def start(self):
        self.call(GC, self.path, 'org.freedesktop.DBus.Properties', 'Set', GLib.Variant(
            '(ssv)', ('org.freedesktop.GeoClue2.Client', 'DesktopId', GLib.Variant('s', self.desktop_id))))
        self.call(GC, self.path, 'org.freedesktop.GeoClue2.Client', 'Start', None)

    def set_desktop_id(self):
        self.call(GC, self.path, 'org.freedesktop.DBus.Properties', 'Set', GLib.Variant(
            '(ssv)', ('org.freedesktop.GeoClue2.Client', 'DesktopId', GLib.Variant('s', self.desktop_id))))

    def stop(self):
        self.call(GC, self.path, 'org.freedesktop.GeoClue2.Client', 'Stop', None)

    def exit(self):
        if not self.conn.is_closed():
            self.conn.close_sync(None)


class ServiceTest(unittest.TestCase):
    uid_override = None
    geoclue_first = True

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        path = os.path.join(self.dir.name, 'bus')
        services = os.path.join(self.dir.name, 'services')
        os.makedirs(services)
        self.activation = os.path.join(self.dir.name, 'activated')
        with open(os.path.join(services, 'gc.service'), 'w') as f:
            f.write(f'[D-BUS Service]\nName={GC}\nExec=/bin/sh -c "touch {self.activation}"\n')
        with open(os.path.join(self.dir.name, 'bus.conf'), 'w') as f:
            f.write(BUS_CONFIG.format(path=path).replace('<auth>', f'<servicedir>{services}</servicedir><auth>'))
        self.bus = subprocess.Popen(['dbus-daemon', '--nofork', '--config-file=' + os.path.join(self.dir.name, 'bus.conf')],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(self.bus.wait)
        self.addCleanup(self.bus.terminate)
        self.address = 'unix:path=' + path
        wait_for(lambda: os.path.exists(path), 10)
        self.state = os.path.join(self.dir.name, 'state')
        self.daemon = None
        self.apps = []
        self.geoclue = None
        self.admin = Gio.DBusConnection.new_for_address_sync(self.address, FLAGS, None, None)
        self.addCleanup(lambda: None if self.admin.is_closed() else self.admin.close_sync(None))

    def tearDown(self):
        for app in self.apps:
            app.exit()
        if self.geoclue:
            self.geoclue.stop()
        self.stop_daemon()

    def start_daemon(self, *extra):
        self.daemon = subprocess.Popen([sys.executable, '-B', DAEMON, '--bus', self.address, '--state-dir', self.state,
                                        *extra], stderr=subprocess.PIPE)
        owned = wait_for(lambda: self.owner('org.omamobile.LocationUsage1') or self.daemon.poll() is not None, 10)
        if self.daemon.poll() is not None:
            self.fail('daemon exited: ' + self.daemon.stderr.read().decode())
        self.assertTrue(owned)

    def stop_daemon(self):
        if self.daemon and self.daemon.poll() is None:
            self.daemon.terminate()
            self.daemon.wait(10)

    def owner(self, name):
        try:
            return self.admin.call_sync('org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus',
                                        'GetNameOwner', GLib.Variant('(s)', (name,)), None,
                                        Gio.DBusCallFlags.NONE, 1000, None).unpack()[0]
        except GLib.Error:
            return None

    def api(self, method, reply='(s)'):
        result = self.admin.call_sync(*API, method, None, GLib.VariantType(reply), Gio.DBusCallFlags.NONE, 3000, None)
        value = result.unpack()[0]
        return json.loads(value) if reply == '(s)' else value

    def history(self):
        return self.api('GetHistory')

    def start_geoclue(self, **kw):
        self.geoclue = FakeGeoClue(self.address, **kw)

    def new_app(self, desktop_id='org.example.Maps'):
        app = App(self.address, desktop_id)
        self.apps.append(app)
        return app


class Lifecycle(ServiceTest):
    def setUp(self):
        super().setUp()
        self.start_daemon()
        self.start_geoclue()

    def test_granted_use_shows_active_then_history_without_geoclue_calls_from_the_daemon(self):
        app = self.new_app()
        app.start()
        status = wait_for(lambda: self.api('GetStatus') if self.api('GetStatus')['active'] else None)
        [entry] = status['active']
        self.assertEqual((entry['app'], entry['pid']), ('org.example.Maps', os.getpid()))
        self.assertTrue(entry['process'])
        self.assertEqual(status['coverage'], 'full')
        self.assertTrue(wait_for(lambda: self.api('GetStatus')['manager_in_use']))
        app.stop()
        done = wait_for(lambda: [e for e in self.history()['entries'] if not e['active']])
        self.assertEqual(done[0]['end_reason'], 'stopped')
        self.assertEqual(self.api('GetStatus')['active'], [])
        # The daemon never asked GeoClue for anything: only the fake client app did.
        self.assertEqual(sorted(set(self.geoclue.calls)), ['GetClient', 'Start', 'Stop'])
        self.assertEqual(len(self.geoclue.calls), 3)

    def test_denied_start_leaves_no_history(self):
        self.geoclue.allow = False
        app = self.new_app()
        with self.assertRaises(GLib.Error):
            app.start()
        time.sleep(0.3)
        self.assertEqual(self.history()['entries'], [])
        self.assertEqual(self.api('GetStatus')['coverage'], 'full')

    def test_app_exit_without_stop_is_closed(self):
        app = self.new_app()
        app.start()
        wait_for(lambda: self.api('GetStatus')['active'])
        app.exit()
        done = wait_for(lambda: [e for e in self.history()['entries'] if e['end_reason']])
        self.assertEqual(done[0]['end_reason'], 'client-exited')
        self.assertEqual(self.api('GetStatus')['active'], [])

    def test_geoclue_restart_closes_active_use(self):
        app = self.new_app()
        app.start()
        wait_for(lambda: self.api('GetStatus')['active'])
        self.geoclue.stop()
        self.geoclue = None
        done = wait_for(lambda: [e for e in self.history()['entries'] if e['end_reason']])
        self.assertEqual(done[0]['end_reason'], 'geoclue-stopped')
        self.assertFalse(self.api('GetStatus')['geoclue_running'])
        self.start_geoclue()
        self.new_app().start()
        self.assertTrue(wait_for(lambda: self.api('GetStatus')['active']))

    def test_a_forged_signal_from_another_connection_is_ignored(self):
        app = self.new_app()
        forger = Gio.DBusConnection.new_for_address_sync(self.address, FLAGS, None, None)
        self.addCleanup(forger.close_sync, None)
        forger.emit_signal(None, app.path, 'org.freedesktop.DBus.Properties', 'PropertiesChanged',
                           GLib.Variant('(sa{sv}as)', ('org.freedesktop.GeoClue2.Client',
                                                       {'Active': GLib.Variant('b', True)}, [])))
        time.sleep(0.4)
        status = self.api('GetStatus')
        self.assertEqual((status['active'], status['coverage']), ([], 'full'))
        # Location objects are outside the monitor's rules: no match, no delivery.
        forger.emit_signal(None, app.path + '/Location/0', 'org.freedesktop.DBus.Properties', 'PropertiesChanged',
                           GLib.Variant('(sa{sv}as)', ('org.freedesktop.GeoClue2.Location',
                                                       {'Latitude': GLib.Variant('d', 1.0)}, [])))
        time.sleep(0.2)
        self.assertNotIn('Latitude', json.dumps(self.history()))

    def test_clear_removes_finished_entries_only_for_the_caller(self):
        app = self.new_app()
        app.start()
        wait_for(lambda: self.api('GetStatus')['active'])
        app.stop()
        wait_for(lambda: [e for e in self.history()['entries'] if not e['active']])
        self.assertEqual(self.api('ClearHistory', '(u)'), 1)
        self.assertEqual(self.history()['entries'], [])

    def test_state_directory_is_private_and_history_survives_restart(self):
        app = self.new_app()
        app.start()
        wait_for(lambda: self.api('GetStatus')['active'])
        app.stop()
        wait_for(lambda: [e for e in self.history()['entries'] if not e['active']])
        self.stop_daemon()
        self.assertEqual(os.stat(self.state).st_mode & 0o777, 0o700)
        self.assertEqual(os.stat(os.path.join(self.state, 'history.json')).st_mode & 0o777, 0o600)
        self.start_daemon()
        self.assertEqual(len(self.history()['entries']), 1)
        # GeoClue was already running at this restart: coverage is partial.
        self.assertEqual(self.api('GetStatus')['coverage'], 'partial')

    def test_cli_emits_json(self):
        env = dict(os.environ, DBUS_SYSTEM_BUS_ADDRESS=self.address)
        out = subprocess.run([sys.executable, '-B', CLI, 'status'], env=env, capture_output=True, text=True, timeout=15)
        self.assertEqual(out.returncode, 0, out.stderr)
        data = json.loads(out.stdout)
        self.assertTrue(data['available'])
        self.assertEqual(data['coverage'], 'full')
        out = subprocess.run([sys.executable, '-B', CLI, 'history'], env=env, capture_output=True, text=True, timeout=15)
        self.assertEqual(json.loads(out.stdout)['entries'], [])
        out = subprocess.run([sys.executable, '-B', CLI, 'bogus'], env=env, capture_output=True, text=True, timeout=15)
        self.assertEqual(out.returncode, 2)


# A second program on the bus, so it has its own PID: it stays alive until its
# stdin closes. "denied" = GeoClue refused its Start; "own" = it creates and
# starts a client of its own.
OTHER_PROGRAM = """
import sys, warnings
warnings.filterwarnings('ignore')
import gi
gi.require_version('Gio', '2.0')
from gi.repository import Gio, GLib
F = Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION
c = Gio.DBusConnection.new_for_address_sync(sys.argv[1], F, None, None)
CLIENT = 'org.freedesktop.GeoClue2.Client'
def call(path, iface, method, args, reply=None):
    return c.call_sync('org.freedesktop.GeoClue2', path, iface, method, args,
                       GLib.VariantType(reply) if reply else None, Gio.DBusCallFlags.NONE, 3000, None)
try:
    path = sys.argv[2]
    if path == 'own':
        path = call('/org/freedesktop/GeoClue2/Manager', 'org.freedesktop.GeoClue2.Manager', 'GetClient', None, '(o)').unpack()[0]
        call(path, 'org.freedesktop.DBus.Properties', 'Set', GLib.Variant('(ssv)', (CLIENT, 'DesktopId', GLib.Variant('s', 'org.example.Other'))))
    call(path, CLIENT, 'Start', None)
    print('started', flush=True)
except GLib.Error as e:
    print('denied' if 'Access denied' in e.message else e.message, flush=True)
sys.stdin.read()
"""


class Racing(ServiceTest):
    """Attribution must come from a successful Start, never from a Start that
    GeoClue refused but the monitor saw."""

    def setUp(self):
        super().setUp()
        self.start_daemon()
        self.start_geoclue()
        self.others = []
        self.addCleanup(self.close_others)

    def close_others(self):
        for proc in self.others:
            proc.stdin.close()
            proc.wait(5)

    def other(self, path):
        proc = subprocess.Popen([sys.executable, '-I', '-c', OTHER_PROGRAM, self.address, path],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        self.others.append(proc)
        return proc, proc.stdout.readline().strip()

    def entries(self, active=None):
        return [e for e in self.history()['entries'] if active is None or e['active'] == active]

    def test_victim_start_then_attacker_start_only_the_victim_is_credited(self):
        self.geoclue.hold_start = True                 # Active=true is out before the victim's reply
        victim = self.new_app()
        victim.set_desktop_id()
        starter = threading.Thread(target=victim.call, args=(
            GC, victim.path, 'org.freedesktop.GeoClue2.Client', 'Start', None))
        starter.start()
        self.assertTrue(wait_for(lambda: self.geoclue.held))
        attacker, result = self.other(victim.path)     # races its own Start onto the victim's client
        self.assertEqual(result, 'denied')
        time.sleep(0.4)
        # Active=true is on the bus, but nothing proves who owns it yet.
        self.assertEqual(self.entries(), [])
        self.assertEqual(self.api('GetStatus')['active'], [])
        self.geoclue.release()
        starter.join(5)
        [entry] = wait_for(lambda: self.entries(True))
        self.assertEqual((entry['pid'], entry['app']), (os.getpid(), 'org.example.Maps'))
        self.assertNotIn(attacker.pid, [e['pid'] for e in self.entries()])
        # The attacker's "Stop" is refused too and does not end the victim's use.
        victim.stop()
        [done] = wait_for(lambda: self.entries(False))
        self.assertEqual((done['pid'], done['end_reason']), (os.getpid(), 'stopped'))

    def test_denied_attacker_before_a_later_victim_start_is_not_credited(self):
        victim = self.new_app()
        attacker, result = self.other(victim.path)
        self.assertEqual(result, 'denied')
        victim.start()
        [entry] = wait_for(lambda: self.entries(True))
        self.assertEqual(entry['pid'], os.getpid())
        self.assertEqual(len(self.entries()), 1)

    def test_a_proven_owner_keeps_the_use_while_others_poke_the_client(self):
        victim = self.new_app()
        victim.start()
        wait_for(lambda: self.entries(True))
        for _ in range(3):
            attacker, result = self.other(victim.path)
            self.assertEqual(result, 'denied')
        time.sleep(0.3)
        [entry] = self.entries()
        self.assertEqual((entry['pid'], entry['active']), (os.getpid(), True))

    def test_a_programs_own_granted_use_is_its_own(self):
        victim = self.new_app()
        victim.start()
        other, result = self.other('own')
        self.assertEqual(result, 'started')
        entries = wait_for(lambda: self.entries(True) if len(self.entries(True)) == 2 else None)
        self.assertEqual(sorted(e['pid'] for e in entries), sorted([os.getpid(), other.pid]))

    def test_success_is_recognised_whichever_comes_first_reply_or_active(self):
        for order in ('reply-first', 'active-first'):
            with self.subTest(order=order):
                self.geoclue.order = order
                app = self.new_app()
                app.start()
                self.assertTrue(wait_for(lambda: self.api('GetStatus')['active']))
                app.stop()
                self.assertTrue(wait_for(lambda: not self.api('GetStatus')['active']))
        self.assertEqual([e['end_reason'] for e in self.entries()], ['stopped', 'stopped'])
        self.assertEqual(self.api('GetStatus')['coverage'], 'full')


class Failure(ServiceTest):
    def test_losing_the_bus_is_a_failure_so_systemd_restarts_the_service(self):
        self.start_daemon()
        self.bus.terminate()
        self.assertTrue(wait_for(lambda: self.daemon.poll() is not None, 10), 'the daemon kept running')
        self.assertNotEqual(self.daemon.returncode, 0)
        self.assertIn('closed', self.daemon.stderr.read().decode())

    def test_a_normal_stop_is_success(self):
        self.start_daemon()
        self.daemon.terminate()
        self.assertEqual(self.daemon.wait(10), 0)


class FakeMessage:
    """What the monitor filter may read of a message: headers. The body of
    anything but a PropertiesChanged signal must never be touched."""

    def __init__(self, kind, member=None, interface=None, sender=None, destination=None, path=None,
                 serial=0, reply_serial=0, signature='', body=None):
        self.kind, self.member, self.interface, self.sender, self.destination = kind, member, interface, sender, destination
        self.path, self.serial, self.reply_serial, self.signature, self.body = path, serial, reply_serial, signature, body
        self.body_reads = 0

    get_message_type = lambda self: self.kind
    get_member = lambda self: self.member
    get_interface = lambda self: self.interface
    get_sender = lambda self: self.sender
    get_destination = lambda self: self.destination
    get_path = lambda self: self.path
    get_serial = lambda self: self.serial
    get_reply_serial = lambda self: self.reply_serial
    get_signature = lambda self: self.signature

    def get_body(self):
        self.body_reads += 1
        if self.body is None:
            raise AssertionError('the body was read')
        return self.body


class SpyTracker:
    def __init__(self):
        self.events = []

    def __getattr__(self, name):
        return lambda *args: self.events.append((name,) + args)


class Filter(unittest.TestCase):
    """The monitor filter and its queue, without a bus."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.service = usage_daemon.Service('unix:path=/nonexistent', self.dir.name)
        self.service.tracker = SpyTracker()
        T = Gio.DBusMessageType
        self.T = T
        self.start = FakeMessage(T.METHOD_CALL, 'Start', usage_daemon.CLIENT_INTERFACE, ':1.10', GC,
                                 '/org/freedesktop/GeoClue2/Client/1', serial=4)

    def test_a_reply_is_read_by_headers_only_and_only_when_it_answers_a_start(self):
        T = self.T
        self.assertEqual(self.service.classify(self.start), ('start', ':1.10', GC, '/org/freedesktop/GeoClue2/Client/1', 4))
        located = FakeMessage(T.METHOD_RETURN, sender=':1.5', destination=':1.10', reply_serial=4)
        self.assertEqual(self.service.classify(located), ('reply', ':1.5', ':1.10', 4))
        self.assertEqual(located.body_reads, 0)
        # Replies that carry a body (a Location property read, say), answer no
        # Start, or answer someone else's: ignored, and never unpacked.
        for message in (FakeMessage(T.METHOD_RETURN, sender=':1.5', destination=':1.10', reply_serial=4, signature='v'),
                        FakeMessage(T.METHOD_RETURN, sender=':1.5', destination=':1.10', reply_serial=99),
                        FakeMessage(T.METHOD_RETURN, sender=':1.5', destination=':1.11', reply_serial=4),
                        FakeMessage(T.ERROR, sender=':1.5', destination=':1.10', reply_serial=4)):
            self.service.replies.add(':1.10', 4, {})
            self.assertIsNone(self.service.classify(message))
            self.assertEqual(message.body_reads, 0)

    def test_a_reply_is_forwarded_once(self):
        T = self.T
        self.service.classify(self.start)
        reply = FakeMessage(T.METHOD_RETURN, sender=':1.5', destination=':1.10', reply_serial=4)
        self.assertIsNotNone(self.service.classify(reply))
        self.assertIsNone(self.service.classify(reply))

    def test_flooding_replies_cannot_fill_the_queue(self):
        for i in range(model.MAX_ATTEMPTS * 20):
            self.service.on_message(None, FakeMessage(self.T.METHOD_RETURN, sender=':1.5', destination=':1.10',
                                                      reply_serial=i + 1000), True)
        self.assertEqual(len(self.service.queue), 0)
        self.assertFalse(self.service.gap)

    def test_the_start_table_is_bounded_per_sender(self):
        for serial in range(1, 200):
            self.service.classify(FakeMessage(self.T.METHOD_CALL, 'Start', usage_daemon.CLIENT_INTERFACE,
                                              ':1.11', GC, '/org/freedesktop/GeoClue2/Client/9', serial=serial))
        self.assertEqual(len(self.service.replies), model.MAX_PER_SENDER)

    def test_queue_overflow_is_reported_to_the_tracker_in_order(self):
        service = self.service
        for i in range(usage_daemon.EVENT_QUEUE + 25):
            service.enqueue(('props', ':1.5', '/org/freedesktop/GeoClue2/Client/1', 'x', {'n': i}))
        self.assertEqual(len(service.queue), usage_daemon.EVENT_QUEUE)
        self.assertTrue(service.gap)
        service.drain()
        names = [e[0] for e in service.tracker.events]
        self.assertEqual(len(names), usage_daemon.EVENT_QUEUE + 1)
        self.assertEqual(names[-1], 'events_lost')        # nothing after the gap: reported at the end
        self.assertFalse(service.gap)

    def test_an_event_after_a_gap_follows_the_lost_marker(self):
        service = self.service
        for i in range(usage_daemon.EVENT_QUEUE + 1):
            service.enqueue(('props', ':1.5', '/org/freedesktop/GeoClue2/Client/1', 'x', {}))
        service.queue.popleft()
        service.queue.popleft()
        service.enqueue(('start', ':1.10', GC, '/org/freedesktop/GeoClue2/Client/1', 1))
        self.assertEqual([e[0] for e in list(service.queue)[-2:]], ['lost', 'start'])

    def test_an_unreadable_message_counts_as_a_lost_event(self):
        self.service.on_message(None, FakeMessage(self.T.SIGNAL, 'PropertiesChanged', signature='sa{sv}as',
                                                  body=None), True)
        self.service.drain()
        self.assertEqual([e[0] for e in self.service.tracker.events], ['events_lost'])

    def test_a_failing_dispatch_marks_events_lost(self):
        self.service.dispatch = lambda event: 1 / 0
        self.service.enqueue(('lost',))
        self.service.drain()
        self.assertEqual([e[0] for e in self.service.tracker.events], ['events_lost'])


class MonitorRules(unittest.TestCase):
    def test_rules_name_only_start_calls_geoclue_replies_and_the_two_property_signals(self):
        rules = usage_daemon.MONITOR_RULES
        self.assertEqual(len(rules), 4)
        self.assertIn("type='method_return',sender='org.freedesktop.GeoClue2'", rules)
        self.assertNotIn('Stop', ' '.join(rules))
        self.assertNotIn('Location', ' '.join(rules))
        for rule in rules:
            self.assertTrue(rule.startswith("type='method_return'") or "member='Start'" in rule or 'arg0=' in rule)


class OtherUser(ServiceTest):
    def test_another_uid_sees_none_of_it(self):
        self.start_daemon()
        self.start_geoclue()
        app = self.new_app()
        app.start()
        wait_for(lambda: self.api('GetStatus')['active'])
        self.stop_daemon()
        self.start_daemon('--uid-override', str(os.getuid() + 1))
        data = self.history()
        self.assertEqual(data['entries'], [])
        self.assertEqual(data['status']['active'], [])
        self.assertEqual(self.api('ClearHistory', '(u)'), 0)


class NoActivation(ServiceTest):
    def test_no_geoclue_means_full_coverage_and_the_daemon_does_not_start_it(self):
        self.start_daemon()
        status = self.api('GetStatus')
        self.assertEqual((status['coverage'], status['geoclue_running'], status['manager_in_use']),
                         ('full', False, False))
        self.api('GetHistory')
        time.sleep(0.5)
        self.assertFalse(os.path.exists(self.activation), 'the observer activated GeoClue')


class AlreadyRunning(ServiceTest):
    def test_geoclue_running_first_reports_partial_and_reads_in_use_once(self):
        self.start_geoclue()
        self.geoclue.in_use = True
        self.start_daemon()
        status = self.api('GetStatus')
        self.assertEqual((status['coverage'], status['manager_in_use']), ('partial', True))
        self.assertEqual(self.geoclue.calls, [])


if __name__ == '__main__':
    unittest.main()
