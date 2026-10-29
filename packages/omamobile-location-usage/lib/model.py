# SPDX-License-Identifier: MIT
"""Location-use lifecycle model: no D-Bus, no clock, no filesystem beyond the
history file, so every rule is testable.

What counts as use. GeoClue broadcasts PropertiesChanged for a client's
Active flag, so Active=true is the proof that a request was granted and a
location source is running. It never says who asked, and a Start method call
alone proves nothing: GeoClue rejects a caller that is not the client's owner
but the bus monitor still sees the attempt.

Attribution therefore needs a successful Start. The daemon feeds the model the
Start call (sender, serial, path) and, from GeoClue's unique owner only, the
header of a method return with an empty signature. A reply whose destination
and reply serial match an outstanding Start proves that exactly that sender
owns exactly that client path (GeoClue's method wrapper answers every
non-owner with an error, which is never seen here). The owner is remembered per
client path, so a later Active=true is credited to it whichever of reply and
signal comes first, and a restart GeoClue performs on its own (agent policy)
keeps its owner. A denied or racing Start is only an outstanding attempt: it is
never promoted, cannot replace the proven owner and cannot end a use. Two
Starts with the same sender and serial are ambiguous and are never trusted.

Trust. A reply or signal counts only when its sender is the actual unique owner
of org.freedesktop.GeoClue2; the model re-resolves the owner when a sender does
not match. DesktopId is self-reported and only ever a label. An Active=true
that cannot be tied to a proven owner is not guessed: it only degrades the
coverage warning, which carries no per-user detail.

Honesty. Every place that can lose or doubt an event (event queue overflow, a
bounded table at its limit, an Active=true nobody claimed) marks coverage
partial instead of claiming it is complete; lost events end the open uses with
an unknown end time.

Nothing here sees coordinates: the model is never handed a reply body and the
daemon does not subscribe to the Location objects or the LocationUpdated
signal.
"""
import json
import os
import re
import tempfile
import time
from collections import OrderedDict

GEOCLUE_NAME = 'org.freedesktop.GeoClue2'
CLIENT_PATH = re.compile(r'^/org/freedesktop/GeoClue2/Client/[0-9]{1,10}$')

RETENTION_DAYS = 7
MAX_PER_UID = 50
MAX_TOTAL = 1000
MAX_ACTIVE = 64
MAX_ATTEMPTS = 64           # outstanding Start calls, all senders
MAX_PER_SENDER = 8          # outstanding Start calls of one sender
MAX_OWNED = 128             # client paths whose owner a successful Start proved
MAX_AWAITING = 64           # Active=true seen, owner not proven yet
MAX_UNKNOWN = 64            # active clients nobody claimed
MAX_LABELS = 128
PENDING_TTL = 120.0         # seconds a Start may wait for GeoClue's reply
AWAIT_TTL = 30.0            # seconds an Active=true may wait for the reply
REFRESH_MIN_INTERVAL = 0.05  # at most 20 owner lookups a second
# A phone without a battery-backed RTC boots with a wrong date until time sync
# runs: ages are only trusted once the clock is plausible.
CLOCK_FLOOR = 1767225600    # 2026-01-01
MAX_LABEL = 128

END_STOPPED = 'stopped'
END_CLIENT_EXITED = 'client-exited'
END_GEOCLUE_RESTARTED = 'geoclue-restarted'
END_GEOCLUE_STOPPED = 'geoclue-stopped'
END_MONITOR_STOPPED = 'monitor-stopped'
END_MONITOR_RESTARTED = 'monitor-restarted'   # end time unknown
END_EVENTS_LOST = 'events-lost'               # end time unknown
END_UNCERTAIN = 'uncertain'                   # end time unknown


def clean_label(value):
    """A self-reported string, made safe to store and show."""
    if not isinstance(value, str):
        return None
    value = ''.join(c for c in value if c.isprintable())[:MAX_LABEL].strip()
    return value or None


class HistoryStore:
    """history.json in a root-owned 0700 directory, written atomically 0600."""

    def __init__(self, directory):
        self.directory = directory
        self.path = os.path.join(directory, 'history.json')

    def load(self):
        try:
            with open(self.path, encoding='utf-8') as handle:
                data = json.load(handle)
            entries = data['entries']
            if data.get('version') != 1 or not isinstance(entries, list):
                raise ValueError('shape')
            return [e for e in entries if self._valid(e)]
        except FileNotFoundError:
            return []
        except (OSError, ValueError, KeyError, TypeError):
            # Keep one copy for inspection and start empty; never loop on it.
            try:
                os.replace(self.path, self.path + '.corrupt')
            except OSError:
                pass
            return []

    @staticmethod
    def _valid(e):
        return (isinstance(e, dict) and isinstance(e.get('id'), int) and isinstance(e.get('uid'), int)
                and isinstance(e.get('started'), (int, float)))

    def save(self, entries):
        fd, tmp = tempfile.mkstemp(dir=self.directory, prefix='.history-')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as handle:
                os.fchmod(handle.fileno(), 0o600)
                json.dump({'version': 1, 'entries': entries}, handle, separators=(',', ':'))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self.path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise


class AttemptTable:
    """Outstanding Start calls keyed by (sender, serial), bounded and expiring.
    Values are dicts. A key seen twice is ambiguous (a reply could belong to
    either call), so the stored value is poisoned and the newcomer is dropped.
    Over the per-sender limit a sender evicts its own oldest entry; over the
    total limit the busiest sender's oldest goes, so a flooder mostly evicts
    itself."""

    def __init__(self, mono=time.monotonic, ttl=PENDING_TTL, limit=MAX_ATTEMPTS, per_sender=MAX_PER_SENDER):
        self.mono = mono
        self.ttl = ttl
        self.limit = limit
        self.per_sender = per_sender
        self.items = OrderedDict()     # (sender, serial) -> [mono, value]

    def __len__(self):
        return len(self.items)

    def expire(self):
        t = self.mono()
        for key in [k for k, v in self.items.items() if t - v[0] > self.ttl]:
            del self.items[key]

    def add(self, sender, serial, value):
        """True when a total-limit eviction may have cost someone an attempt."""
        self.expire()
        key = (sender, serial)
        if key in self.items:
            self.items[key][1]['poisoned'] = True
            return False
        mine = [k for k in self.items if k[0] == sender]
        if len(mine) >= self.per_sender:
            del self.items[mine[0]]
        evicted = False
        if len(self.items) >= self.limit:
            counts = {}
            for k in self.items:
                counts[k[0]] = counts.get(k[0], 0) + 1
            busiest = max(counts.values())
            for k in self.items:
                if counts[k[0]] == busiest:
                    del self.items[k]
                    break
            evicted = True
        self.items[key] = [self.mono(), value]
        return evicted

    def get(self, sender, serial):
        item = self.items.get((sender, serial))
        if item is None or self.mono() - item[0] > self.ttl:
            return None
        return item[1]

    def pop(self, sender, serial):
        value = self.get(sender, serial)
        self.items.pop((sender, serial), None)
        return value

    def drop_sender(self, sender):
        for key in [k for k in self.items if k[0] == sender]:
            del self.items[key]

    def values_of(self, sender):
        return [v[1] for k, v in self.items.items() if k[0] == sender]

    def clear(self):
        self.items.clear()


class Tracker:
    """resolve(sender) -> {'uid', 'pid', 'process'} or None. lookup_owner() ->
    the unique name that owns GeoClue now, or None. watch(name)/unwatch(name)
    ask the daemon to report that bus name vanishing."""

    def __init__(self, store, resolve, lookup_owner, watch=None, unwatch=None,
                 now=time.time, mono=time.monotonic):
        self.store = store
        self.resolve = resolve
        self.lookup_owner = lookup_owner
        self.watch = watch or (lambda name: None)
        self.unwatch = unwatch or (lambda name: None)
        self.now = now
        self.mono = mono
        self.owner = None
        self.manager_in_use = False
        self.monitoring = 'running'
        self.degraded = OrderedDict()   # reason -> note; any entry means partial coverage
        self.coverage = 'full'
        self.coverage_note = ''
        self.coverage_since = now()
        self.history_error = False
        self.entries = store.load()
        self.next_id = max([e['id'] for e in self.entries] + [0]) + 1
        self.active = {}           # client path -> entry
        self.unknown = set()       # client paths active with no proven owner (bounded)
        self.attempts = AttemptTable(mono)   # outstanding Starts: never trusted by themselves
        self.owned = OrderedDict()     # client path -> {'sender', 'creds'}, proven by a successful Start
        self.awaiting = OrderedDict()  # client path -> mono: Active=true before the Start reply
        self.labels = OrderedDict()    # client path -> self-reported DesktopId
        self._last_refresh = -1e9
        # An entry left open by a previous run ended at an unknown time.
        reopened = False
        for e in self.entries:
            if e.get('ended') is None and not e.get('end_reason'):
                e['end_reason'] = END_MONITOR_RESTARTED
                reopened = True
        if reopened:
            self._save()

    # ------------------------------------------------------------ coverage

    def _degrade(self, reason, note):
        if reason not in self.degraded:
            self.degraded[reason] = note
        self.coverage = 'partial'
        self.coverage_note = ' '.join(self.degraded.values())

    def _restore_coverage(self):
        if self.degraded:
            self.degraded.clear()
            self.coverage = 'full'
            self.coverage_note = ''
            self.coverage_since = self.now()

    def begin(self, owner):
        """Monitoring is up. A GeoClue that already runs may have clients that
        started before the monitor: say so instead of claiming there are none."""
        self.owner = owner
        self._restore_coverage()
        self.coverage_since = self.now()
        if owner:
            self._degrade('preexisting', 'GeoClue was already running when monitoring began; earlier uses may be missing.')
            self.manager_in_use = None
        else:
            self.manager_in_use = False

    def set_owner(self, owner):
        """GeoClue's owner changed: its clients, and what we proved about
        their owners, are gone with it. Outstanding Starts are kept: a reply
        from the new owner may legitimately answer one (our name signal can lag
        the monitor's stream); each is only ever matched by its exact sender,
        serial and a reply from the current owner."""
        if owner == self.owner:
            return
        reason = END_GEOCLUE_RESTARTED if owner else END_GEOCLUE_STOPPED
        self._close_all(reason)
        for path in list(self.owned):
            self._forget_owned(path)
        self.awaiting.clear()
        self.labels.clear()
        self.unknown.clear()
        self.owner = owner
        self.manager_in_use = False
        # A GeoClue that began after the monitor, or none at all, has no
        # client the monitor missed and no event it lost.
        self._restore_coverage()

    def monitor_lost(self):
        """The monitor connection (or the bus) closed: nothing is observed."""
        self.monitoring = 'stopped'
        self._degrade('monitor', 'Monitoring stopped.')

    def events_lost(self):
        """Events were dropped: every open use may have ended and any start may
        have been missed. Close what is open with an unknown end and forget
        what was in flight; proven owners stay (they only change on events the
        daemon does not drop: owner and client loss)."""
        self._close_all(END_EVENTS_LOST, known_end=False)
        self.attempts.clear()
        self.awaiting.clear()
        self.unknown.clear()
        self._degrade('events-lost', 'Some events were lost; uses may be missing or have an unknown end.')

    def _trusted(self, sender):
        if not sender:
            return False
        if sender != self.owner:
            t = self.mono()
            if t - self._last_refresh < REFRESH_MIN_INTERVAL:
                return False
            self._last_refresh = t
            self.set_owner(self.lookup_owner())
        return sender == self.owner

    def _dest_ok(self, destination):
        return destination == GEOCLUE_NAME or (destination and self._trusted(destination))

    # -------------------------------------------------------------- events

    def _creds_for(self, sender):
        """One credential lookup per connection, however many Starts it sends."""
        for value in self.attempts.values_of(sender):
            if value.get('creds'):
                return value['creds']
        for owned in self.owned.values():
            if owned['sender'] == sender and owned['creds']:
                return owned['creds']
        return self.resolve(sender)

    def call_start(self, sender, destination, path, serial):
        """A Start method call was seen. Only an outstanding attempt: it proves
        nothing until GeoClue's own success reply for exactly this call."""
        if not (sender and isinstance(serial, int) and serial > 0 and CLIENT_PATH.match(path or '')
                and self._dest_ok(destination)):
            return
        self.attempts.expire()
        if (sender, serial) in self.attempts.items:
            self.attempts.add(sender, serial, {})   # poisons the first; neither is trusted
            return
        value = {'path': path, 'dest': destination, 'creds': self._creds_for(sender)}
        if self.attempts.add(sender, serial, value):
            self._degrade('overflow', 'Too many simultaneous requests; some uses may be missing.')

    def call_reply(self, sender, destination, reply_serial, signature=''):
        """Header of a method return seen from `sender`. Only a reply with an
        empty signature from GeoClue's current owner, whose destination and
        reply serial match an outstanding Start, proves that Start succeeded.
        The reply body is never passed in."""
        if signature or not destination or not isinstance(reply_serial, int):
            return
        attempt = self.attempts.get(destination, reply_serial)
        if attempt is None or not self._trusted(sender):
            return
        if attempt['dest'] != GEOCLUE_NAME and attempt['dest'] != sender:
            return
        self.attempts.pop(destination, reply_serial)
        if attempt.get('poisoned'):
            return
        self._prove(attempt['path'], destination, attempt['creds'])

    def properties_changed(self, sender, path, interface, changed):
        if not CLIENT_PATH.match(path or '') or not self._trusted(sender):
            return
        if interface == 'org.freedesktop.GeoClue2.Client':
            if 'DesktopId' in changed:
                label = clean_label(changed['DesktopId'])
                self.labels.pop(path, None)
                if label:
                    self.labels[path] = label
                    while len(self.labels) > MAX_LABELS:
                        self.labels.popitem(last=False)
                if path in self.active:
                    self.active[path]['app'] = label
                    self._save()
            if 'Active' in changed:
                if changed['Active'] is True:
                    self._opened(path)
                elif changed['Active'] is False:
                    self._closed(path)

    def manager_changed(self, sender, path, interface, changed):
        if (path == '/org/freedesktop/GeoClue2/Manager' and interface == 'org.freedesktop.GeoClue2.Manager'
                and 'InUse' in changed and isinstance(changed['InUse'], bool) and self._trusted(sender)):
            self.manager_in_use = changed['InUse']

    def name_vanished(self, name):
        """A proven owner's connection went away without Active=false."""
        for path in [p for p, o in self.owned.items() if o['sender'] == name]:
            self._close(path, END_CLIENT_EXITED)
            self._forget_owned(path, release=False)
        self.attempts.drop_sender(name)
        self.unwatch(name)

    # ------------------------------------------------------------ internals

    def _expire(self):
        self.attempts.expire()
        t = self.mono()
        for path in [p for p, since in self.awaiting.items() if t - since > AWAIT_TTL]:
            del self.awaiting[path]
            self._unattributed(path)

    def _unattributed(self, path):
        self._degrade('unattributed', 'A location use could not be attributed; it may be missing from history.')
        if len(self.unknown) < MAX_UNKNOWN:
            self.unknown.add(path)
        else:
            self._degrade('overflow', 'Too many simultaneous requests; some uses may be missing.')

    def _forget_owned(self, path, release=True):
        owned = self.owned.pop(path, None)
        if owned and release:
            self._release(owned['sender'])

    def _release(self, sender):
        if not any(o['sender'] == sender for o in self.owned.values()):
            self.unwatch(sender)

    def _prove(self, path, sender, creds):
        """GeoClue accepted a Start from `sender` for `path`: only the client's
        owner can be accepted, so `sender` is the owner."""
        self._expire()
        current = self.owned.get(path)
        if current and current['sender'] != sender:
            # Impossible with a conforming GeoClue: trust neither.
            self._close(path, END_UNCERTAIN, known_end=False)
            self._forget_owned(path)
            self._unattributed(path)
            return
        self.owned[path] = {'sender': sender, 'creds': creds}
        self.owned.move_to_end(path)
        self.watch(sender)
        while len(self.owned) > MAX_OWNED:
            victim = next((p for p in self.owned if p not in self.active and p != path), None)
            if victim is None:
                break
            self._forget_owned(victim)
        if path in self.awaiting:
            del self.awaiting[path]
            self._open(path)

    def _opened(self, path):
        if path in self.active or path in self.unknown:
            return
        self._expire()
        if path in self.owned:
            self._open(path)
            return
        self.awaiting[path] = self.mono()
        self.awaiting.move_to_end(path)
        while len(self.awaiting) > MAX_AWAITING:
            self._unattributed(self.awaiting.popitem(last=False)[0])

    def _open(self, path):
        creds = self.owned[path]['creds']
        if not creds or not isinstance(creds.get('uid'), int):
            self._unattributed(path)
            return
        if len(self.active) >= MAX_ACTIVE:
            self._degrade('overflow', 'Too many simultaneous requests; some uses may be missing.')
            self._unattributed(path)
            return
        entry = {'id': self.next_id, 'uid': creds['uid'], 'pid': creds.get('pid'),
                 'process': clean_label(creds.get('process')), 'app': self.labels.get(path),
                 'started': self.now(), 'ended': None, 'end_reason': None}
        self.next_id += 1
        self.entries.append(entry)
        self.active[path] = entry
        self._prune()
        self._save()

    def _closed(self, path):
        self.unknown.discard(path)
        self.awaiting.pop(path, None)
        if path in self.active:
            self._close(path, END_STOPPED)

    def _close(self, path, reason, known_end=True):
        entry = self.active.pop(path, None)
        if entry is None:
            return
        entry['ended'] = self.now() if known_end else None
        entry['end_reason'] = reason
        self._prune()
        self._save()

    def _close_all(self, reason, known_end=True):
        for path in list(self.active):
            self._close(path, reason, known_end)

    def shutdown(self):
        self._close_all(END_MONITOR_STOPPED)

    def _prune(self):
        now = self.now()
        keep = []
        by_uid = {}
        for e in sorted(self.entries, key=lambda e: e['id'], reverse=True):
            is_active = e.get('ended') is None and not e.get('end_reason')
            old = (now >= CLOCK_FLOOR and e['started'] >= CLOCK_FLOOR
                   and now - e['started'] > RETENTION_DAYS * 86400)
            count = by_uid.get(e['uid'], 0)
            if not is_active and (old or count >= MAX_PER_UID or len(keep) >= MAX_TOTAL):
                continue
            by_uid[e['uid']] = count + 1
            keep.append(e)
        keep.reverse()
        self.entries[:] = keep

    def prune(self):
        self._prune()
        self._save()

    def _save(self):
        stored = [{k: v for k, v in e.items() if not k.startswith('_')} for e in self.entries]
        try:
            self.store.save(stored)
            self.history_error = False
        except OSError:
            self.history_error = True

    # ------------------------------------------------------------ the API

    @staticmethod
    def _view(e):
        active = e.get('ended') is None and not e.get('end_reason')
        known = bool(e.get('process'))
        return {'id': e['id'], 'app': e.get('app'), 'process': e.get('process'),
                'pid': e.get('pid') if known else None, 'started': e['started'],
                'ended': e.get('ended'), 'end_reason': e.get('end_reason'), 'active': active}

    def status(self, uid):
        """Only the caller's own entries; other users' uses count as nothing
        but, at most, the GeoClue-wide InUse flag GeoClue itself publishes."""
        mine = [self._view(e) for e in self.entries if e['uid'] == uid]
        self._expire()
        return {
            'version': 1,
            'monitoring': self.monitoring,
            'coverage': self.coverage,
            'coverage_note': self.coverage_note,
            'coverage_since': self.coverage_since,
            'geoclue_running': bool(self.owner),
            'manager_in_use': self.manager_in_use if self.owner else False,
            'active': [v for v in mine if v['active']],
            'history_error': self.history_error,
            'retention_days': RETENTION_DAYS,
            'max_entries': MAX_PER_UID,
        }

    def history(self, uid):
        mine = [self._view(e) for e in self.entries if e['uid'] == uid]
        mine.sort(key=lambda v: v['id'], reverse=True)
        return {'status': self.status(uid), 'entries': mine}

    def clear(self, uid):
        """Removes the caller's finished entries; a use still in progress stays."""
        before = len(self.entries)
        self.entries[:] = [e for e in self.entries
                           if e['uid'] != uid or (e.get('ended') is None and not e.get('end_reason'))]
        removed = before - len(self.entries)
        if removed:
            self._save()
        return removed
