#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Write one bounded stereo probe after the OEM speaker graph starts."""

import math
import os
import pathlib
import struct
import sys
import time


RATE = 48000
FREQUENCY = 300.0
AMPLITUDE = 32767
PERIOD_BYTES = 3840 * 2 * 2
PCM_START_TIMEOUT = 45.0


def payload():
    cycle_frames = round(RATE / FREQUENCY)
    samples = [round(AMPLITUDE * math.sin(2.0 * math.pi * frame / cycle_frames))
               for frame in range(cycle_frames)]
    left_cycle = b"".join(struct.pack("<hh", sample, 0) for sample in samples)
    right_cycle = b"".join(struct.pack("<hh", 0, sample) for sample in samples)
    cycles = round(1.5 * FREQUENCY)
    return (left_cycle * cycles + bytes(round(0.75 * RATE) * 4)
            + right_cycle * cycles)


def write_all(fd, data):
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise RuntimeError("speaker FIFO write made no progress")
        view = view[written:]


def write_probe(fifo, stream_ready):
    data = payload()
    fd = os.open(fifo, os.O_WRONLY)
    try:
        # The reference bridge needs one complete period before it opens the
        # OEM graph. Do not fill the pipe during that hardware transaction.
        write_all(fd, data[:PERIOD_BYTES])
        deadline = time.monotonic() + PCM_START_TIMEOUT
        while not stream_ready.is_file():
            if time.monotonic() >= deadline:
                raise RuntimeError("speaker bridge did not start the OEM PCM graph")
            time.sleep(0.05)
        write_all(fd, data[PERIOD_BYTES:])
    finally:
        os.close(fd)


def main(argv):
    if len(argv) != 3:
        print(f"usage: {argv[0]} FIFO STREAM_READY", file=sys.stderr)
        return 2
    write_probe(argv[1], pathlib.Path(argv[2]))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
