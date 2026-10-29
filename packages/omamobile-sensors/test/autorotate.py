#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Focused checks for monitor preservation and failed-rotation state."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
import tempfile
import time
from unittest.mock import patch, Mock
spec=importlib.util.spec_from_file_location('rotate',Path(__file__).resolve().parents[1]/'lib/autorotate.py')
r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)
class Rotation(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name)
        for name,value in [('lock_path',str(root/'rotation-lock')),('settings_path',root/'rotation.json'),('runtime_path',root/'runtime.json')]:
            mock=patch.object(r,name,return_value=value);mock.start();self.addCleanup(mock.stop)

    def test_mode_position_scale_preserved(self):
        code=r.rotation_lua(dict(name='DSI-1',width=1200,height=2608,refreshRate=120,x=600,y=-40,scale=2),1)
        self.assertIn('mode = "1200x2608@120.000000"',code)
        self.assertIn('position = "600x-40"',code)
        self.assertIn('scale = 2, transform = 1',code)
        self.assertIn('touchdevice = { transform = 1',code)
    def test_failed_rotation_not_recorded_as_applied(self):
        rot=r.Rotator.__new__(r.Rotator);rot.current=0;rot.args=SimpleNamespace(monitor='DSI-1',dry_run=False)
        with patch.object(r,'apply',return_value=False):rot._rotate('left-up')
        self.assertEqual(rot.current,0)
        with patch.object(r,'apply',return_value=True):rot._rotate('left-up')
        self.assertEqual(rot.current,1)
    def test_failed_apply_quits_loop_for_supervised_restore(self):
        rot=r.Rotator.__new__(r.Rotator);rot.current=0;rot.failed=False;rot.loop=Mock()
        rot.args=SimpleNamespace(monitor='DSI-1',dry_run=False)
        with patch.object(r,'apply',return_value=False):rot._rotate('left-up')
        self.assertTrue(rot.failed)
        rot.loop.quit.assert_called_once()
    def pending_rotator(self):
        rot=r.Rotator.__new__(r.Rotator)
        rot.current=0;rot.claimed=True;rot.orientation='left-up'
        rot.tilt='vertical';rot.has_tilt=True;rot.pending=None;rot.settle_timer=0
        rot.policy=r.settings();rot.last_hint_orientation=None;rot.hint=None
        rot._session_safe=Mock(return_value=True);rot._publish=Mock()
        rot._rotate=Mock()
        return rot
    def test_flat_cancels_pending_rotation(self):
        rot=self.pending_rotator()
        with patch.object(r.GLib,'timeout_add',return_value=42) as timer, patch.object(r.GLib,'source_remove') as cancel:
            rot._queue_rotation()
            timer.assert_called_once_with(700,rot._settled)
            rot.tilt='face-up';rot._queue_rotation()
            cancel.assert_called_once_with(42)
            self.assertIsNone(rot.pending)
            rot._settled();rot._rotate.assert_not_called()
    def test_orientation_must_stay_stable_until_settled(self):
        rot=self.pending_rotator()
        with patch.object(r.GLib,'timeout_add',return_value=42),patch.object(r.GLib,'source_remove'),patch.object(r.os.path,'exists',return_value=False):
            rot._queue_rotation()
            rot.orientation='right-up';rot._queue_rotation()
            rot._settled();rot._rotate.assert_called_once_with('right-up')
    def test_raising_phone_rearms_after_flat_hold(self):
        rot=self.pending_rotator();rot.tilt='face-down'
        with patch.object(r.GLib,'timeout_add',return_value=42) as timer:
            rot._queue_rotation();timer.assert_not_called()
            rot.tilt='tilted-up';rot._queue_rotation()
            timer.assert_called_once_with(700,rot._settled)
    def test_unknown_tilt_holds_but_missing_capability_uses_delay(self):
        rot=self.pending_rotator();rot.tilt='undefined'
        with patch.object(r.GLib,'timeout_add',return_value=42) as timer:
            rot._queue_rotation();timer.assert_not_called()
            rot.has_tilt=False;rot._queue_rotation();timer.assert_called_once()
    def test_locked_hint_does_not_rotate_or_repeat(self):
        Path(r.lock_path()).touch()
        rot=self.pending_rotator();rot.policy=r.settings();rot.pending='left-up'
        rot._settled()
        rot._rotate.assert_not_called()
        self.assertEqual(rot.hint['orientation'],'left-up')
        self.assertEqual(rot.last_hint_orientation,'left-up')
        with patch.object(r.GLib,'timeout_add') as timer:
            rot._queue_rotation();timer.assert_not_called()
    def test_disallowed_direction_has_no_rotation_or_hint(self):
        rot=self.pending_rotator();rot.policy['allowed']=['normal']
        with patch.object(r.GLib,'timeout_add') as timer:
            rot._queue_rotation();timer.assert_not_called()
        self.assertIsNone(rot.hint)
    def test_accept_is_one_shot_and_keeps_lock(self):
        Path(r.lock_path()).touch()
        rot=self.pending_rotator();rot.policy=r.settings();rot.last_policy=rot.policy.copy()
        rot.safe=True;rot.available=True;rot._update_claim=Mock();rot._queue_rotation=Mock()
        rot.hint=dict(token='current',orientation='left-up',expires=time.monotonic()+5)
        r.atomic_json(r.runtime_path().with_name('omamobile-rotation-request.json'),{'token':'current'})
        rot._tick();rot._rotate.assert_called_once_with('left-up')
        self.assertTrue(Path(r.lock_path()).exists());self.assertIsNone(rot.hint)
    def test_expired_hint_request_is_ignored(self):
        Path(r.lock_path()).touch()
        rot=self.pending_rotator();rot.policy=r.settings();rot.last_policy=rot.policy.copy()
        rot.safe=True;rot.available=True;rot._update_claim=Mock();rot._queue_rotation=Mock()
        rot.hint=dict(token='old',orientation='left-up',expires=time.monotonic()-1)
        r.atomic_json(r.runtime_path().with_name('omamobile-rotation-request.json'),{'token':'old'})
        rot._tick();rot._rotate.assert_not_called()
    def test_malformed_settings_use_defaults(self):
        for value in ['[]', '{"hint_seconds":null,"allowed":[{}]}']:
            r.settings_path().write_text(value)
            self.assertEqual(r.settings()['hint_seconds'],5)
    def test_lifecycle_error_quits_for_cleanup(self):
        rot=self.pending_rotator();rot.loop=Mock()
        rot._tick_checked=Mock(side_effect=OSError('disk full'))
        self.assertEqual(rot._tick(),r.GLib.SOURCE_REMOVE)
        self.assertTrue(rot.failed);rot.loop.quit.assert_called_once()
    def test_flat_transient_does_not_destroy_visible_hint(self):
        rot=self.pending_rotator();rot.hint={'token':'live'};rot.tilt='face-up'
        rot._queue_rotation()
        self.assertEqual(rot.hint,{'token':'live'})
    def test_lua_error_is_not_success(self):
        m=dict(name='DSI-1',width=1200,height=2608,refreshRate=120,x=0,y=0,scale=2)
        with patch.object(r,'monitor',return_value=m),patch.object(r,'hyprctl',return_value=SimpleNamespace(returncode=0,stdout='error: rejected',stderr='')):
            self.assertFalse(r.apply(1))
    def safety_rotator(self, bl_power):
        rot=r.Rotator.__new__(r.Rotator)
        rot.args=SimpleNamespace(session=False,dry_run=False,monitor='DSI-1')
        rot.safe_cached=False;rot.safe_until=0
        d=tempfile.mkdtemp();Path(d,'bl0').mkdir();Path(d,'bl0','bl_power').write_text(bl_power)
        def read(path):
            return {'backlight':'bl0'} if str(path).endswith('display.json') else {}
        real=r.Path
        def fake_path(*a):
            if a and a[0]=='/sys/class/backlight':return real(d)
            return real(*a)
        return rot,read,fake_path
    def test_dark_panel_spawns_nothing(self):
        rot,read,fake=self.safety_rotator('4')
        with patch.dict(r.os.environ,{'XDG_RUNTIME_DIR':'/tmp'}),patch.object(r,'read_json',side_effect=read),patch.object(r,'Path',side_effect=fake),\
             patch.object(r,'monitor') as mon,patch.object(r.subprocess,'run') as run:
            self.assertFalse(rot._session_safe())
            mon.assert_not_called();run.assert_not_called()
    def test_lit_panel_caches_forked_checks(self):
        rot,read,fake=self.safety_rotator('0')
        with patch.dict(r.os.environ,{'XDG_RUNTIME_DIR':'/tmp'}),patch.object(r,'read_json',side_effect=read),patch.object(r,'Path',side_effect=fake),\
             patch.object(r,'monitor',return_value={'dpmsStatus':True}) as mon,\
             patch.object(r.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout='false\n')):
            self.assertTrue(rot._session_safe());self.assertTrue(rot._session_safe())
            self.assertEqual(mon.call_count,1)
            self.assertTrue(rot._session_safe(fresh=True))
            self.assertEqual(mon.call_count,2)
    def test_publish_skips_unchanged_state_until_heartbeat(self):
        rot=r.Rotator.__new__(r.Rotator)
        rot.args=SimpleNamespace(session=False,dry_run=False)
        rot.hint=None;rot.safe=True;rot.available=True;rot.current=0
        rot.policy={'locked':True,'hints':True};rot.published=None;rot.published_at=0
        with patch.object(r,'atomic_json') as write,patch.object(r,'runtime_path',return_value=Path('/tmp/x')):
            rot._publish();rot._publish()
            self.assertEqual(write.call_count,1)
            rot.current=1;rot._publish()
            self.assertEqual(write.call_count,2)
            rot.published_at-=r.PUBLISH_HEARTBEAT_S;rot._publish()
            self.assertEqual(write.call_count,3)
if __name__=='__main__':unittest.main()
