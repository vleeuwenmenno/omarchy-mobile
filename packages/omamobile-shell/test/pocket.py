#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Guard races: stale expiry, late swipe and preservation of PIN boundaries."""
import importlib.machinery
import importlib.util
from pathlib import Path
import contextlib
import tempfile
import unittest
from unittest.mock import patch
import sys
sys.dont_write_bytecode = True
loader = importlib.machinery.SourceFileLoader('pocket', str(Path(__file__).resolve().parents[1] / 'bin/omamobile-pocket'))
spec = importlib.util.spec_from_loader(loader.name, loader)
pocket = importlib.util.module_from_spec(spec)
loader.exec_module(pocket)

class Panel:
    @contextlib.contextmanager
    def transition(self):
        yield
    def lit(self):
        return True

class Guard(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = patch.object(pocket, 'STATE', Path(self.temp.name) / 'state.json')
        self.state.start()
        self.addCleanup(self.state.stop)

    def test_old_timeout_cannot_blank_new_wake(self):
        pocket.save(dict(active=True, token='new'))
        with patch.object(pocket, 'panel', return_value=Panel()), patch.object(pocket, 'off_locked') as off:
            pocket.expire('old')
            off.assert_not_called()
            pocket.expire('new')
            off.assert_called_once()

    def test_late_swipe_and_wrong_token_do_not_dismiss(self):
        for token, deadline, expected in [('new', 9, False), ('old', 11, False), ('new', 11, True)]:
            pocket.save(dict(active=True, phase='blocked', token='new', deadline=deadline))
            with patch.object(pocket, 'panel', return_value=Panel()), patch.object(pocket, 'clear_locked') as clear, patch.object(pocket.time, 'monotonic', return_value=10), patch.object(sys, 'argv', ['pocket', 'dismiss', token]):
                pocket.main()
                self.assertEqual(clear.called, expected)

    def test_repeated_wake_does_not_replace_active_guard(self):
        pocket.save(dict(active=True, token='first', deadline=20))
        with patch.object(pocket, 'panel', return_value=Panel()), patch.object(pocket, 'proximity') as probe:
            pocket.begin()
            probe.assert_not_called()
        self.assertEqual(pocket.read(pocket.STATE)['token'], 'first')

    def test_cleanup_continues_after_failure(self):
        calls = []
        def failed():
            calls.append('failed')
            raise RuntimeError('IPC down')
        with self.assertRaises(RuntimeError):
            pocket.attempt_all([failed, lambda: calls.append('restored')])
        self.assertEqual(calls, ['failed', 'restored'])

    def test_dark_pending_guard_cannot_be_replaced(self):
        p = Panel()
        p.lit = lambda: False
        pocket.save(dict(active=True, token='first'))
        with patch.object(pocket, 'panel', return_value=p), patch.object(pocket, 'enabled', return_value=True), patch.object(pocket, 'proximity') as probe:
            with self.assertRaisesRegex(RuntimeError, 'pending'):
                pocket.begin()
            probe.assert_not_called()
        self.assertEqual(pocket.read(pocket.STATE)['token'], 'first')

    def test_prepare_phase_cannot_be_swiped(self):
        pocket.save(dict(active=True, phase='preparing', token='new', deadline=20))
        with patch.object(pocket, 'panel', return_value=Panel()), patch.object(pocket, 'clear_locked') as clear, patch.object(sys, 'argv', ['pocket', 'dismiss', 'new']):
            pocket.main()
            clear.assert_not_called()

if __name__ == '__main__':
    unittest.main()
