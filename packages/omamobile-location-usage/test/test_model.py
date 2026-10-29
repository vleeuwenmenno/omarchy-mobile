# SPDX-License-Identifier: MIT
"""Lifecycle rules of model.Tracker with fake time, a fake bus and no D-Bus."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'lib'))
import model  # noqa: E402

GC = 'org.freedesktop.GeoClue2'
CLIENT = 'org.freedesktop.GeoClue2.Client'
MANAGER = 'org.freedesktop.GeoClue2.Manager'
P1 = '/org/freedesktop/GeoClue2/Client/1'
P2 = '/org/freedesktop/GeoClue2/Client/2'
BASE = model.CLOCK_FLOOR + 1000


class Clock:
    def __init__(self):
        self.wall = BASE
        self.tick = 1000.0

    def now(self):
        return self.wall

    def mono(self):
        return self.tick

    def advance(self, seconds):
        self.wall += seconds
        self.tick += seconds


class Fixture(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.clock = Clock()
        self.creds = {':1.10': {'uid': 1000, 'pid': 4242, 'process': 'where-am-i'},
                      ':1.11': {'uid': 1001, 'pid': 4343, 'process': 'maps'}}
        self.real_owner = ':1.5'
        self.watched = set()
        self.build()

    def build(self):
        self.t = model.Tracker(model.HistoryStore(self.dir.name), lambda s: self.creds.get(s),
                               lambda: self.real_owner, self.watched.add, self.watched.discard,
                               self.clock.now, self.clock.mono)

    serial = 0

    def next_serial(self):
        Fixture.serial += 1
        return Fixture.serial

    def start_use(self, sender=':1.10', path=P1, app='org.example.Maps', geoclue=':1.5', order='reply-first'):
        """A granted Start: the call, GeoClue's success reply and Active=true,
        in either order (GeoClue may emit Active before it replies)."""
        if app:
            self.t.properties_changed(geoclue, path, CLIENT, {'DesktopId': app})
        serial = self.next_serial()
        self.t.call_start(sender, GC, path, serial)
        steps = [lambda: self.t.call_reply(geoclue, sender, serial),
                 lambda: self.t.properties_changed(geoclue, path, CLIENT, {'Active': True})]
        for step in (steps if order == 'reply-first' else steps[::-1]):
            step()
        return serial

    def mine(self, uid=1000):
        return self.t.history(uid)['entries']


class Lifecycle(Fixture):
    def setUp(self):
        super().setUp()
        self.t.begin(None)
        self.t.set_owner(':1.5')
        self.creds[':1.12'] = {'uid': 1002, 'pid': 4444, 'process': 'attacker'}

    def active_of(self, uid):
        return self.t.status(uid)['active']

    def test_granted_use_becomes_active_then_history_in_either_order(self):
        for order in ('reply-first', 'active-first'):
            with self.subTest(order=order):
                self.build()
                self.t.begin(None)
                self.t.set_owner(':1.5')
                self.start_use(order=order)
                [entry] = self.t.status(1000)['active']
                self.assertEqual((entry['app'], entry['process'], entry['pid']),
                                 ('org.example.Maps', 'where-am-i', 4242))
                self.clock.advance(30)
                self.t.properties_changed(':1.5', P1, CLIENT, {'Active': False})    # a genuine Stop
                self.assertEqual(self.t.status(1000)['active'], [])
                done = self.mine()[-1]
                self.assertEqual((done['end_reason'], done['ended'] - done['started']), (model.END_STOPPED, 30))
                self.assertEqual(self.t.status(1000)['coverage'], 'full')
                self.assertEqual(self.t.unknown, set())

    def test_start_without_a_success_reply_is_not_use(self):
        self.t.call_start(':1.10', GC, P1, 1)     # GeoClue denied it: an error, never seen
        self.assertEqual(self.mine(), [])
        self.assertEqual(self.t.status(1000)['coverage'], 'full')

    def test_victim_start_then_attacker_start_only_the_victim_is_credited(self):
        """The race: the attacker's denied Start lands after the victim's."""
        self.t.call_start(':1.10', GC, P1, 1)     # victim, will succeed
        self.t.call_start(':1.11', GC, P1, 7)     # attacker on the victim's path: GeoClue says no
        self.t.properties_changed(':1.5', P1, CLIENT, {'Active': True})
        self.assertEqual(self.mine(1000), [])      # nothing proven yet
        self.t.call_reply(':1.5', ':1.10', 1)
        self.assertEqual(len(self.mine(1000)), 1)
        self.assertEqual(self.mine(1001), [])
        self.assertEqual(self.t.status(1001)['active'], [])

    def test_attacker_start_before_the_victims_is_not_credited_either(self):
        self.t.call_start(':1.11', GC, P1, 7)     # denied
        self.t.call_start(':1.10', GC, P1, 1)
        self.t.call_reply(':1.5', ':1.10', 1)
        self.t.properties_changed(':1.5', P1, CLIENT, {'Active': True})
        self.assertEqual(len(self.mine(1000)), 1)
        self.assertEqual(self.mine(1001), [])

    def test_attacker_attempts_never_replace_or_end_the_proven_owner(self):
        self.start_use()
        for serial in range(20, 26):
            self.t.call_start(':1.11', GC, P1, serial)
        self.t.properties_changed(':1.5', P1, CLIENT, {'Active': False})   # agent policy stops it...
        self.t.properties_changed(':1.5', P1, CLIENT, {'Active': True})    # ...and later restarts it
        entries = self.mine(1000)
        self.assertEqual([e['active'] for e in entries], [True, False])   # newest first
        self.assertEqual(self.mine(1001), [])
        self.assertEqual(len(self.active_of(1000)), 1)

    def test_a_reply_from_anyone_but_geoclues_owner_proves_nothing(self):
        self.t.call_start(':1.11', GC, P1, 7)
        self.t.call_reply(':1.77', ':1.11', 7)    # a forged "success"
        self.t.properties_changed(':1.5', P1, CLIENT, {'Active': True})
        self.assertEqual((self.mine(1001), self.mine(1000)), ([], []))
        self.assertEqual(self.t.owned, {})
        # The forger did not consume the attempt: the real reply still works.
        self.t.call_start(':1.10', GC, P2, 3)
        self.t.call_reply(':1.77', ':1.10', 3)
        self.assertIn((':1.10', 3), self.t.attempts.items)

    def test_only_a_reply_with_the_exact_destination_serial_and_empty_signature_counts(self):
        self.t.call_start(':1.10', GC, P1, 1)
        self.t.call_reply(':1.5', ':1.11', 1)             # another connection's reply
        self.t.call_reply(':1.5', ':1.10', 2)             # another call's reply
        self.t.call_reply(':1.5', ':1.10', 1, 'o')        # a reply that carries a body
        self.t.call_reply(':1.5', None, 1)
        self.t.properties_changed(':1.5', P1, CLIENT, {'Active': True})
        self.assertEqual(self.mine(1000), [])
        self.assertEqual(self.t.owned, {})

    def test_the_same_serial_twice_is_ambiguous_and_trusted_for_neither(self):
        """Sending serial 1 to the attacker's own client and again, with the
        victim's path, must not turn the first call's success into the second."""
        self.t.call_start(':1.11', GC, P2, 1)     # attacker's own client: will succeed
        self.t.call_start(':1.11', GC, P1, 1)     # same serial, victim's path: denied
        self.t.call_reply(':1.5', ':1.11', 1)
        self.t.properties_changed(':1.5', P1, CLIENT, {'Active': True})
        self.t.properties_changed(':1.5', P2, CLIENT, {'Active': True})
        self.assertEqual(self.mine(1001), [])
        self.assertEqual(self.t.owned, {})

    def test_concurrent_attempts_are_kept_apart(self):
        self.t.call_start(':1.10', GC, P1, 1)
        self.t.call_start(':1.11', GC, P2, 1)     # same serial, other sender: a different key
        self.t.call_start(':1.10', GC, P2, 2)     # denied (P2 is not its client)
        self.t.call_reply(':1.5', ':1.11', 1)
        self.t.call_reply(':1.5', ':1.10', 1)
        self.t.properties_changed(':1.5', P2, CLIENT, {'Active': True})
        self.t.properties_changed(':1.5', P1, CLIENT, {'Active': True})
        self.assertEqual([e['pid'] for e in self.mine(1000)], [4242])
        self.assertEqual([e['pid'] for e in self.mine(1001)], [4343])
        self.assertEqual(self.mine(1002), [])

    def test_a_late_reply_cannot_attribute_an_old_active(self):
        self.t.call_start(':1.10', GC, P1, 1)
        self.t.properties_changed(':1.5', P1, CLIENT, {'Active': True})
        self.clock.advance(model.AWAIT_TTL + 1)
        self.t.call_reply(':1.5', ':1.10', 1)
        self.assertEqual(self.mine(), [])
        self.assertEqual(self.t.status(1000)['coverage'], 'partial')

    def test_stale_start_expires(self):
        self.t.call_start(':1.10', GC, P1, 1)
        self.clock.advance(model.PENDING_TTL + 1)
        self.t.call_reply(':1.5', ':1.10', 1)
        self.t.properties_changed(':1.5', P1, CLIENT, {'Active': True})
        self.assertEqual(self.mine(), [])
        self.assertEqual(self.t.owned, {})

    def test_unknown_caller_is_not_guessed(self):
        self.start_use(':1.99', P1)               # credentials unavailable
        self.assertEqual(self.mine(), [])
        status = self.t.status(1000)
        self.assertEqual(status['coverage'], 'partial')
        self.assertNotIn('unknown_active', status)
        self.t.properties_changed(':1.5', P1, CLIENT, {'Active': False})
        self.assertEqual(self.t.unknown, set())

    def test_active_without_a_seen_start_degrades_coverage_without_a_count(self):
        self.t.properties_changed(':1.5', P1, CLIENT, {'Active': True})
        self.assertEqual(self.t.status(1000)['coverage'], 'full')     # a reply may still come
        self.clock.advance(model.AWAIT_TTL + 1)
        for uid in (1000, 1001, 4000):
            status = self.t.status(uid)
            self.assertEqual(status['coverage'], 'partial')
            self.assertIn('could not be attributed', status['coverage_note'])
            self.assertEqual(status['active'], [])
            self.assertNotIn('unknown', json.dumps(status).replace('could not be attributed', ''))
        self.assertEqual((self.mine(1000), self.mine(1001)), ([], []))

    def test_client_exit_without_active_false_closes_the_entry(self):
        self.start_use()
        self.assertEqual(self.watched, {':1.10'})
        self.clock.advance(5)
        self.t.name_vanished(':1.10')
        [done] = self.mine()
        self.assertEqual(done['end_reason'], model.END_CLIENT_EXITED)
        self.assertFalse(done['active'])
        self.assertEqual(self.watched, set())
        self.assertEqual(self.t.owned, {})
        # Nothing is remembered about the gone client.
        self.t.properties_changed(':1.5', P1, CLIENT, {'Active': True})
        self.assertEqual(len(self.mine()), 1)

    def test_geoclue_restart_closes_everything_and_forgets_owners(self):
        self.start_use()
        self.start_use(':1.11', P2, 'org.example.Other')
        self.t.set_owner(':1.6')
        self.assertEqual(self.t.status(1000)['active'], [])
        self.assertEqual(self.mine()[0]['end_reason'], model.END_GEOCLUE_RESTARTED)
        self.assertEqual(self.watched, set())
        # The old paths mean nothing to the new process: the old owner is not inherited.
        self.t.properties_changed(':1.6', P1, CLIENT, {'Active': True})
        self.assertEqual(len(self.mine()), 1)

    def test_geoclue_exit_is_recorded(self):
        self.start_use()
        self.t.set_owner(None)
        self.assertEqual(self.mine()[0]['end_reason'], model.END_GEOCLUE_STOPPED)
        self.assertFalse(self.t.status(1000)['geoclue_running'])

    def test_signals_from_anyone_but_geoclue_are_ignored(self):
        self.t.call_start(':1.10', GC, P1, 1)
        self.t.call_reply(':1.5', ':1.10', 1)
        self.clock.advance(1)
        self.t.properties_changed(':1.77', P1, CLIENT, {'Active': True})   # a forger
        self.assertEqual(self.mine(), [])
        self.assertEqual(self.t.awaiting, {})
        self.t.manager_changed(':1.77', '/org/freedesktop/GeoClue2/Manager', MANAGER, {'InUse': True})
        self.assertFalse(self.t.status(1000)['manager_in_use'])

    def test_a_forged_active_false_cannot_end_a_real_use(self):
        self.start_use()
        self.clock.advance(1)
        self.t.properties_changed(':1.77', P1, CLIENT, {'Active': False})
        self.assertEqual(len(self.t.status(1000)['active']), 1)

    def test_owner_is_re_resolved_when_the_name_signal_lags(self):
        self.t.set_owner(None)
        self.real_owner = ':1.8'                   # GeoClue just started; our signal is late
        self.t.call_start(':1.10', GC, P1, 1)
        self.clock.advance(1)
        self.t.call_reply(':1.8', ':1.10', 1)
        self.t.properties_changed(':1.8', P1, CLIENT, {'Active': True})
        self.assertEqual(len(self.mine()), 1)

    def test_a_start_sent_before_a_late_owner_change_still_matches_the_new_owners_reply(self):
        self.real_owner = ':1.6'                   # restart; our name signal has not arrived
        self.t.call_start(':1.10', GC, P1, 1)
        self.t.call_reply(':1.6', ':1.10', 1)      # re-resolves the owner, then proves
        self.t.properties_changed(':1.6', P1, CLIENT, {'Active': True})
        self.assertEqual(len(self.mine()), 1)

    def test_start_by_unique_name_needs_the_reply_from_that_name(self):
        self.t.call_start(':1.10', ':1.5', P1, 1)
        self.t.call_start(':1.11', ':1.77', P1, 2)          # not GeoClue: not an attempt
        self.assertEqual(list(self.t.attempts.items), [(':1.10', 1)])
        self.t.call_reply(':1.5', ':1.10', 1)
        self.assertEqual(self.t.owned[P1]['sender'], ':1.10')

    def test_bad_paths_and_interfaces_are_ignored(self):
        for path in ('/org/freedesktop/GeoClue2/Client/1/Location/0', '/org/freedesktop/GeoClue2/Client/x', '/other'):
            self.t.call_start(':1.10', GC, path, 1)
            self.t.properties_changed(':1.5', path, CLIENT, {'Active': True})
        self.t.call_start(':1.10', GC, P1, 2)
        self.t.call_reply(':1.5', ':1.10', 2)
        self.t.properties_changed(':1.5', P1, 'org.freedesktop.GeoClue2.Location', {'Active': True})
        self.assertEqual(self.mine(), [])
        self.assertEqual(self.t.awaiting, {})
        self.assertEqual(len(self.t.attempts), 0)

    def test_start_to_another_service_is_ignored(self):
        self.t.call_start(':1.10', 'org.example.Other', P1, 1)
        self.assertEqual(len(self.t.attempts), 0)

    def test_credentials_are_looked_up_once_per_connection(self):
        calls = []
        self.t.resolve = lambda sender: calls.append(sender) or self.creds.get(sender)
        for serial in range(1, 6):
            self.t.call_start(':1.10', GC, P1, serial)
        self.assertEqual(calls, [':1.10'])

    def test_self_reported_label_is_sanitised(self):
        self.start_use(app='x‮\n' + 'a' * 500)
        self.assertLessEqual(len(self.mine()[0]['app']), model.MAX_LABEL)
        self.assertNotIn('\n', self.mine()[0]['app'])


class Isolation(Fixture):
    def setUp(self):
        super().setUp()
        self.t.begin(None)
        self.t.set_owner(':1.5')

    def test_users_see_only_their_own_entries_and_clear_only_theirs(self):
        self.start_use(':1.10', P1, 'a')
        self.start_use(':1.11', P2, 'b')
        for uid, name in ((1000, 'a'), (1001, 'b')):
            data = self.t.history(uid)
            self.assertEqual([e['app'] for e in data['entries']], [name])
            self.assertEqual([e['app'] for e in data['status']['active']], [name])
            self.assertNotIn('uid', json.dumps(data))
        self.t.properties_changed(':1.5', P1, CLIENT, {'Active': False})
        self.t.properties_changed(':1.5', P2, CLIENT, {'Active': False})
        self.assertEqual(self.t.clear(1000), 1)
        self.assertEqual(self.mine(1000), [])
        self.assertEqual(len(self.mine(1001)), 1)
        self.assertEqual(self.t.history(4000), {'status': self.t.status(4000), 'entries': []})

    def test_clear_keeps_a_use_in_progress(self):
        self.start_use()
        self.assertEqual(self.t.clear(1000), 0)
        self.assertEqual(len(self.t.status(1000)['active']), 1)


class Coverage(Fixture):
    def test_geoclue_already_running_is_partial_until_it_restarts(self):
        self.t.begin(':1.5')
        status = self.t.status(1000)
        self.assertEqual((status['coverage'], status['manager_in_use']), ('partial', None))
        self.assertTrue(status['coverage_note'])
        self.t.set_owner(None)
        self.assertEqual(self.t.status(1000)['coverage'], 'full')

    def test_geoclue_not_running_at_start_is_full(self):
        self.t.begin(None)
        status = self.t.status(1000)
        self.assertEqual((status['coverage'], status['geoclue_running'], status['manager_in_use']),
                         ('full', False, False))

    def test_manager_in_use_follows_trusted_signals(self):
        self.t.begin(None)
        self.t.set_owner(':1.5')
        self.t.manager_changed(':1.5', '/org/freedesktop/GeoClue2/Manager', MANAGER, {'InUse': True})
        self.assertTrue(self.t.status(1000)['manager_in_use'])
        self.t.set_owner(':1.6')
        self.assertFalse(self.t.status(1000)['manager_in_use'])


class Persistence(Fixture):
    def setUp(self):
        super().setUp()
        self.t.begin(None)
        self.t.set_owner(':1.5')

    def test_history_survives_restart_and_open_entries_end_unknown(self):
        self.start_use()
        self.start_use(':1.11', P2, 'b')
        self.t.properties_changed(':1.5', P2, CLIENT, {'Active': False})
        self.build()
        entries = {e['app']: e for e in self.mine(1000) + self.mine(1001)}
        self.assertEqual(entries['org.example.Maps']['end_reason'], model.END_MONITOR_RESTARTED)
        self.assertIsNone(entries['org.example.Maps']['ended'])
        self.assertEqual(entries['b']['end_reason'], model.END_STOPPED)
        self.assertFalse(self.mine(1000)[0]['active'])

    def test_file_is_private_and_holds_no_secrets(self):
        self.start_use()
        path = os.path.join(self.dir.name, 'history.json')
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
        text = open(path).read()
        for word in ('latitude', 'longitude', 'cmdline', 'environ', ':1.10'):
            self.assertNotIn(word, text)
        self.assertEqual(os.listdir(self.dir.name), ['history.json'])

    def test_corrupt_file_starts_empty_without_looping(self):
        with open(os.path.join(self.dir.name, 'history.json'), 'w') as f:
            f.write('{not json')
        self.build()
        self.assertEqual(self.t.entries, [])
        self.assertTrue(os.path.exists(os.path.join(self.dir.name, 'history.json.corrupt')))

    def test_unwritable_store_is_reported_not_fatal(self):
        self.t.store.directory = os.path.join(self.dir.name, 'missing')
        self.start_use()
        self.assertTrue(self.t.status(1000)['history_error'])
        self.assertEqual(len(self.t.status(1000)['active']), 1)


class Bounds(Fixture):
    def setUp(self):
        super().setUp()
        self.t.begin(None)
        self.t.set_owner(':1.5')

    def use_and_stop(self, path=P1, seconds=1):
        self.start_use(path=path, app=None)
        self.clock.advance(seconds)
        self.t.properties_changed(':1.5', path, CLIENT, {'Active': False})

    def test_at_most_fifty_per_user_newest_kept(self):
        for _ in range(model.MAX_PER_UID + 7):
            self.use_and_stop()
        entries = self.mine()
        self.assertEqual(len(entries), model.MAX_PER_UID)
        self.assertEqual(entries[0]['id'], model.MAX_PER_UID + 7)
        self.start_use(':1.11', P2, 'other')
        self.assertEqual(len(self.mine(1001)), 1)

    def test_entries_older_than_seven_days_go(self):
        self.use_and_stop()
        self.clock.advance(model.RETENTION_DAYS * 86400 + 10)
        self.use_and_stop()
        self.assertEqual([e['id'] for e in self.mine()], [2])

    def test_implausible_clock_keeps_entries(self):
        self.clock.wall = 1000.0                   # no RTC yet
        self.use_and_stop()
        self.clock.wall = BASE + 90 * 86400        # time sync caught up
        self.use_and_stop()
        self.assertEqual(len(self.mine()), 2)

    def test_attempts_and_labels_are_bounded(self):
        for i in range(model.MAX_PER_SENDER + 20):
            self.t.call_start(':1.10', GC, f'/org/freedesktop/GeoClue2/Client/{i}', i + 1)
            self.t.properties_changed(':1.5', f'/org/freedesktop/GeoClue2/Client/{i}', CLIENT, {'DesktopId': 'x'})
        self.assertEqual(len(self.t.attempts), model.MAX_PER_SENDER)
        self.assertLessEqual(len(self.t.labels), model.MAX_LABELS)
        self.assertEqual(self.t.status(1000)['coverage'], 'full')    # a sender evicting itself costs nobody

    def test_a_flooding_sender_cannot_evict_another_senders_attempt(self):
        self.t.call_start(':1.10', GC, P1, 1)
        for sender in range(100, 100 + model.MAX_ATTEMPTS // model.MAX_PER_SENDER + 3):
            for serial in range(model.MAX_PER_SENDER):
                self.t.call_start(f':1.{sender}', GC, P2, serial + 1)
        self.assertLessEqual(len(self.t.attempts), model.MAX_ATTEMPTS)
        self.t.call_reply(':1.5', ':1.10', 1)
        self.assertIn(P1, self.t.owned)

    def test_total_attempt_overflow_is_reported_not_silent(self):
        for sender in range(100, 100 + model.MAX_ATTEMPTS + 5):
            self.t.call_start(f':1.{sender}', GC, P2, 1)
        self.assertLessEqual(len(self.t.attempts), model.MAX_ATTEMPTS)
        self.assertEqual(self.t.status(1000)['coverage'], 'partial')

    def test_owned_set_is_bounded_and_keeps_active_owners(self):
        self.start_use()
        for i in range(2, model.MAX_OWNED + 20):
            path = f'/org/freedesktop/GeoClue2/Client/{i}'
            serial = self.next_serial()
            self.t.call_start(':1.10', GC, path, serial)
            self.t.call_reply(':1.5', ':1.10', serial)
        self.assertEqual(len(self.t.owned), model.MAX_OWNED)
        self.assertIn(P1, self.t.owned)
        self.assertEqual(self.watched, {':1.10'})

    def test_active_set_is_bounded_and_reported(self):
        for i in range(model.MAX_ACTIVE + 5):
            self.start_use(path=f'/org/freedesktop/GeoClue2/Client/{i}', app=None)
        self.assertEqual(len(self.t.active), model.MAX_ACTIVE)
        self.assertEqual(len(self.t.unknown), 5)
        self.assertEqual(self.t.status(1000)['coverage'], 'partial')

    def test_unclaimed_active_set_is_capped_and_degrades_coverage(self):
        for i in range(model.MAX_AWAITING + model.MAX_UNKNOWN + 10):
            self.t.properties_changed(':1.5', f'/org/freedesktop/GeoClue2/Client/{i}', CLIENT, {'Active': True})
        self.clock.advance(model.AWAIT_TTL + 1)
        status = self.t.status(1000)
        self.assertLessEqual(len(self.t.awaiting), model.MAX_AWAITING)
        self.assertLessEqual(len(self.t.unknown), model.MAX_UNKNOWN)
        self.assertEqual(status['coverage'], 'partial')
        self.assertIn('Too many', status['coverage_note'])


class Degraded(Fixture):
    def setUp(self):
        super().setUp()
        self.t.begin(None)
        self.t.set_owner(':1.5')

    def test_lost_events_end_open_uses_with_unknown_end_and_flag_partial(self):
        self.start_use()
        self.t.call_start(':1.11', GC, P2, 9)            # a start whose reply we may have missed
        self.clock.advance(10)
        self.t.events_lost()
        status = self.t.status(1000)
        self.assertEqual((status['coverage'], status['active']), ('partial', []))
        self.assertIn('lost', status['coverage_note'])
        [entry] = self.mine()
        self.assertEqual((entry['end_reason'], entry['ended'], entry['active']), (model.END_EVENTS_LOST, None, False))
        self.assertEqual((len(self.t.attempts), self.t.awaiting, self.t.unknown), (0, {}, set()))
        # A reply for the forgotten attempt proves nothing; the proven owner survives.
        self.t.call_reply(':1.5', ':1.11', 9)
        self.assertNotIn(P2, self.t.owned)
        self.t.properties_changed(':1.5', P1, CLIENT, {'Active': True})
        self.assertEqual(len(self.t.status(1000)['active']), 1)
        self.assertEqual(self.t.status(1000)['coverage'], 'partial')

    def test_a_new_geoclue_process_restores_full_coverage(self):
        self.t.events_lost()
        self.assertEqual(self.t.status(1000)['coverage'], 'partial')
        self.t.set_owner(':1.6')
        status = self.t.status(1000)
        self.assertEqual((status['coverage'], status['coverage_note']), ('full', ''))

    def test_monitor_loss_is_published_and_never_reads_as_running(self):
        self.start_use()
        self.t.monitor_lost()
        status = self.t.status(1000)
        self.assertEqual((status['monitoring'], status['coverage']), ('stopped', 'partial'))
        self.t.shutdown()
        self.assertEqual(self.mine()[0]['end_reason'], model.END_MONITOR_STOPPED)

    def test_ownership_conflict_trusts_nobody(self):
        self.start_use()
        serial = self.next_serial()
        self.t.call_start(':1.11', GC, P1, serial)
        self.t.call_reply(':1.5', ':1.11', serial)       # cannot happen with a conforming GeoClue
        self.assertEqual(self.mine(1001), [])
        self.assertEqual(self.mine(1000)[0]['end_reason'], model.END_UNCERTAIN)
        self.assertEqual(self.t.status(1000)['coverage'], 'partial')


if __name__ == '__main__':
    unittest.main()
