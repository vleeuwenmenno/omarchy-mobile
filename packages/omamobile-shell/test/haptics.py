#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
import importlib.machinery
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import json
import time

loader=importlib.machinery.SourceFileLoader('haptics',str(Path(__file__).resolve().parents[1]/'bin/omamobile-haptics'))
spec=importlib.util.spec_from_loader(loader.name,loader)
h=importlib.util.module_from_spec(spec);loader.exec_module(h)

class Haptics(unittest.TestCase):
    def test_disabled_never_opens_device(self):
        with patch.object(h,'enabled',return_value=False),patch.object(h.os,'open') as opened:
            h.pulse();opened.assert_not_called()
    def test_locked_never_opens_device(self):
        with patch.object(h,'enabled',return_value=True),patch.object(h,'safe',return_value=False),patch.object(h.os,'open') as opened:
            h.pulse();opened.assert_not_called()
    def test_burst_limit_prevents_device_access(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime=Path(directory)
            (runtime/'omamobile-haptics.lock').write_text(json.dumps([time.monotonic()-1]*6))
            with patch.object(h,'RUNTIME',runtime),patch.object(h,'enabled',return_value=True),patch.object(h,'safe',return_value=True),patch.object(h,'device',return_value='/dev/input/event1'),patch.object(h.os,'open') as opened:
                h.pulse();opened.assert_not_called()

if __name__=='__main__':unittest.main()
