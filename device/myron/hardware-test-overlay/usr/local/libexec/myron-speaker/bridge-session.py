#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Add an exact PCM-start handshake around the pinned OEM speaker bridge.

The upstream/reference bridge must first read one complete FIFO period before
it can open and start the OEM MIPLAY PCM graph. The producer must not fill the
FIFO while that slow hardware transaction is still running. This wrapper
publishes a runtime-only marker at the bridge's stream_pcm boundary, which is
called immediately after pcm_start succeeds.
"""

import importlib.util
import os
import pathlib
import sys


DIRECTORY = pathlib.Path(__file__).resolve().parent
BRIDGE = DIRECTORY / "bridge.py"
STREAM_READY = pathlib.Path(os.environ.get(
    "MYRON_SPEAKER_STREAM_READY", "/run/myron-audio/stream-ready"))


def load_bridge():
    spec = importlib.util.spec_from_file_location("myron_speaker_bridge", BRIDGE)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load pinned speaker bridge")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    STREAM_READY.unlink(missing_ok=True)
    bridge = load_bridge()
    original_stream_pcm = bridge.stream_pcm

    def stream_pcm(*args, **kwargs):
        STREAM_READY.write_text("ready\n")
        try:
            return original_stream_pcm(*args, **kwargs)
        finally:
            STREAM_READY.unlink(missing_ok=True)

    bridge.stream_pcm = stream_pcm
    try:
        return bridge.main()
    finally:
        STREAM_READY.unlink(missing_ok=True)


if __name__ == "__main__":
    try:
        sys.exit(main() or 0)
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
