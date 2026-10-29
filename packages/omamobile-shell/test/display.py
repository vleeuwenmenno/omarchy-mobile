#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Targeted display policy checks; hardware acceptance is separate."""
import importlib.machinery
import importlib.util
from pathlib import Path
import tempfile
import unittest
import sys
sys.dont_write_bytecode = True
from unittest.mock import patch

loader = importlib.machinery.SourceFileLoader('display', str(Path(__file__).resolve().parents[1] / 'bin/omamobile-display'))
spec = importlib.util.spec_from_loader(loader.name, loader)
display = importlib.util.module_from_spec(spec)
loader.exec_module(display)


class Policy(unittest.TestCase):
    config = dict(min_percent=3, max_percent=55, rise_per_second=1,
                  fall_per_second=.5, fast_rise_per_second=5, fast_fall_per_second=5)

    def test_continuous_claim_rejects_dead_restarted_and_starting_services(self):
        state = dict(owner=':1.42', at=100, since=90)
        self.assertTrue(display.live_sensor_claim(state, ':1.42', 102))
        self.assertFalse(display.live_sensor_claim(state, ':1.42', 106))
        self.assertFalse(display.live_sensor_claim(state, ':1.43', 102))
        self.assertFalse(display.live_sensor_claim(state, ':1.42', 99))
        self.assertFalse(display.live_sensor_claim(dict(state, since=102), ':1.42', 102.1))

    def simulate(self, initial_lux, current, lux, seconds, maximum=16383):
        quantum = 100 / maximum
        control = display.AdaptiveBrightness(self.config, quantum)
        control.update(initial_lux, current, 0)
        values = [current]
        for _ in range(round(seconds / display.RAMP_INTERVAL)):
            value, _, _ = control.update(lux, current, display.RAMP_INTERVAL)
            self.assertLessEqual(abs(value - values[-1]), .1 + quantum)
            current = round(value / quantum) * quantum
            values.append(current)
        return values

    def test_large_transitions_and_endpoints(self):
        bright = display.target(10000, 3, 55)
        down = self.simulate(10000, bright, 0, 16)
        up = self.simulate(0, 3, 10000, 16)
        saturated = self.simulate(0, 3, 1000000, 20)
        self.assertLess(down[100], bright - 5)
        self.assertGreater(up[100], 8)
        self.assertAlmostEqual(down[-1], 3, delta=.02)
        self.assertAlmostEqual(up[-1], bright, delta=.3)
        self.assertAlmostEqual(saturated[-1], 55, delta=.02)
        self.assertTrue(all(a >= b for a, b in zip(down, down[1:])))
        self.assertTrue(all(a <= b for a, b in zip(up, up[1:])))

    def test_small_changes_and_quantized_panel_do_not_stall(self):
        start = display.target(20, 3, 55)
        # A 4095-count panel used to round every slow 20ms step to zero.
        values = self.simulate(20, start, 15, 8, maximum=4095)
        self.assertLess(values[-1], start - .5)
        self.assertGreater(values[50], start - .7)

    def test_reversal_and_wake_write_reconcile(self):
        control = display.AdaptiveBrightness(self.config)
        current = 20
        for _ in range(30):
            current, _, _ = control.update(10000, current, .02)
        previous = current
        current, _, _ = control.update(0, current, .02)
        self.assertLessEqual(current, previous)
        # Wake preparation can write 3% between polling ticks.
        current, _, _ = control.update(10000, 3, .5)
        self.assertLessEqual(current, 3.1)

    def test_filter_catchup_keeps_fast_polling(self):
        control = display.AdaptiveBrightness(self.config)
        start = display.target(8, 3, 55)
        control.update(8, start, 0)
        value, details, pending = control.update(20, start, .02)
        self.assertTrue(pending)
        self.assertLess(details['target_percent'], details['light_target_percent'])
        self.assertLessEqual(value - start, .1)

    def test_limits_and_gradual_steps(self):
        self.assertEqual(display.target(0, 3, 55), 3)
        self.assertEqual(display.target(1000000, 3, 55), 55)
        self.assertEqual(display.ramp(20, 55, .5, 1, .5), 20.5)
        self.assertEqual(display.ramp(20, 3, .5, 1, .5), 19.75)
        self.assertEqual(display.ramp(20, 20.1, .5, 1, .5), 20.1)

    def test_wake_fallback_and_idempotence(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / 'brightness').write_text('9000')
            (folder / 'bl_power').write_text('4')
            panel = object.__new__(display.Panel)
            panel.path = panel.runtime = folder
            panel.maximum = 10000
            panel.state_path = folder / 'state.json'
            panel.c = dict(min_percent=3, max_percent=55, wake_max_percent=15)
            panel.c['power_key_only'] = True
            with self.assertRaisesRegex(RuntimeError, 'power button'):
                display.prepare(panel, sample=False)
            self.assertEqual(panel.raw(), 9000)
            panel.save({'wake_until': display.time.monotonic() + 5, 'manual': True})
            display.prepare(panel, sample=False)
            self.assertEqual(panel.raw(), 300)
            self.assertTrue(panel.state()["manual"])
            self.assertFalse(panel.lit())
            (folder / 'bl_power').write_text('0')
            (folder / 'brightness').write_text('4000')
            display.prepare(panel, sample=False)
            self.assertEqual(panel.raw(), 4000)

    def test_invalid_configuration_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'display.json'
            with patch.object(display, 'CONFIG', path):
                self.assertIsNone(display.configuration())
                path.write_text('{"enabled":true,"backlight":"panel0","min_percent":60}')
                with self.assertRaises(ValueError):
                    display.configuration()

    def test_sensor_loss_stops_ramp(self):
        handlers = {}
        class FakeLight:
            claimed = True
            lux = 500
            ticks = 0
            def drain(self):
                self.ticks += 1
                if self.ticks > 1:
                    self.lux = None
                if self.ticks == 3:
                    handlers[display.signal.SIGTERM]()
            def release(self):
                self.claimed = False
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / 'brightness').write_text('1000')
            (folder / 'bl_power').write_text('0')
            panel = object.__new__(display.Panel)
            panel.path = panel.runtime = folder
            panel.maximum = 10000
            panel.state_path = folder / 'state.json'
            panel.c = dict(min_percent=3, max_percent=55, rise_per_second=1, fall_per_second=.5)
            with patch.object(display, 'Light', FakeLight), \
                    patch.object(display.time, 'sleep'), \
                    patch.object(display.time, 'monotonic', side_effect=[0, .5, .51, 1, 1.5]), \
                    patch.object(display.signal, 'signal', side_effect=lambda sig, handler: handlers.update({sig: handler})):
                display.daemon(panel)
            self.assertEqual(panel.raw(), 1010)


if __name__ == '__main__':
    unittest.main()
