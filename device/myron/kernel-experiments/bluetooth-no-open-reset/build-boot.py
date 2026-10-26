#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Build the exact offline slot-A Bluetooth kernel candidate."""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import subprocess
import tempfile
from pathlib import Path


BASE_SHA256 = "def61369f915cfe3327f73391056290027565d172d9786c75fe373f61e2ffe08"
KERNEL_SHA256 = "672808b1277b583fdc398986bfe8d100b2ebbf1c2cfbb9d14dd257366d1a5937"
PARTITION_SIZE = 96 * 1024 * 1024


def run(*args: str) -> str:
    return subprocess.run(args, check=True, text=True, capture_output=True).stdout


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def value(text: str, label: str) -> str:
    match = re.search(rf"^\s*{re.escape(label)}:\s+(.+)$", text, re.MULTILINE)
    if not match:
        raise SystemExit(f"base boot lacks AVB field: {label}")
    return match.group(1).strip()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-boot", type=Path, required=True)
    parser.add_argument("--kernel", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    for tool in ("avbtool", "mkbootimg", "unpack_bootimg"):
        if shutil.which(tool) is None:
            raise SystemExit(f"required tool is missing: {tool}")
    for path in (args.base_boot, args.kernel):
        if not path.is_file() or path.is_symlink():
            raise SystemExit(f"input is missing, linked or not regular: {path}")
    if args.out.exists() or args.out.is_symlink():
        raise SystemExit(f"refusing to replace output: {args.out}")
    if sha256(args.base_boot) != BASE_SHA256:
        raise SystemExit("base is not the exact reviewed postmarketOS slot-A boot image")
    if sha256(args.kernel) != KERNEL_SHA256:
        raise SystemExit("kernel is not the exact reviewed Bluetooth address candidate")
    if args.base_boot.stat().st_size != PARTITION_SIZE:
        raise SystemExit("base boot image is not 96 MiB")

    with tempfile.TemporaryDirectory(prefix="myron-bluetooth-boot-") as temp_name:
        temp = Path(temp_name)
        unpacked = temp / "base"
        boot_info = run(
            "unpack_bootimg",
            "--boot_img",
            str(args.base_boot),
            "--out",
            str(unpacked),
            "--format",
            "info",
        )
        required = (
            "boot magic: ANDROID!",
            "ramdisk size: 0",
            "boot image header version: 4",
            "command line args: \n",
            "boot.img signature size: 0",
        )
        if any(item not in boot_info for item in required):
            raise SystemExit("base boot layout differs from reviewed header-v4 image")

        avb_info = run("avbtool", "info_image", "--image", str(args.base_boot))
        if value(avb_info, "Algorithm") != "NONE":
            raise SystemExit("base boot is not the reviewed explicitly unsigned image")
        if value(avb_info, "Partition Name") != "boot":
            raise SystemExit("base AVB descriptor is not for boot")
        salt = value(avb_info, "Salt")
        hash_algorithm = value(avb_info, "Hash Algorithm")
        rollback_index = value(avb_info, "Rollback Index")
        rollback_location = value(avb_info, "Rollback Index Location")
        flags = value(avb_info, "Flags")
        properties = re.findall(r"^\s+Prop: (\S+) -> '(.*)'$", avb_info, re.MULTILINE)

        raw = temp / "boot.img"
        run(
            "mkbootimg",
            "--header_version",
            "4",
            "--kernel",
            str(args.kernel),
            "--ramdisk",
            str(unpacked / "ramdisk"),
            "--cmdline",
            "",
            "--output",
            str(raw),
        )
        avb_args = [
            "avbtool",
            "add_hash_footer",
            "--image",
            str(raw),
            "--partition_size",
            str(PARTITION_SIZE),
            "--partition_name",
            "boot",
            "--hash_algorithm",
            hash_algorithm,
            "--salt",
            salt,
            "--algorithm",
            "NONE",
            "--rollback_index",
            rollback_index,
            "--rollback_index_location",
            rollback_location,
            "--flags",
            flags,
        ]
        for key, prop_value in properties:
            avb_args.extend(("--prop", f"{key}:{prop_value}"))
        run(*avb_args)
        run("avbtool", "verify_image", "--image", str(raw))

        verify = temp / "verify"
        verify_info = run(
            "unpack_bootimg",
            "--boot_img",
            str(raw),
            "--out",
            str(verify),
            "--format",
            "info",
        )
        if "boot image header version: 4" not in verify_info:
            raise SystemExit("candidate header verification failed")
        if (verify / "kernel").read_bytes() != args.kernel.read_bytes():
            raise SystemExit("candidate kernel readback differs")
        if (verify / "ramdisk").stat().st_size != 0:
            raise SystemExit("candidate unexpectedly contains a ramdisk")
        if raw.stat().st_size != PARTITION_SIZE:
            raise SystemExit("candidate partition size differs")
        candidate_avb = run("avbtool", "info_image", "--image", str(raw))
        for field, expected in (
            ("Algorithm", "NONE"),
            ("Rollback Index", rollback_index),
            ("Rollback Index Location", rollback_location),
            ("Flags", flags),
            ("Salt", salt),
        ):
            if value(candidate_avb, field) != expected:
                raise SystemExit(f"candidate changed AVB field: {field}")

        args.out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(raw, args.out)

    print(f"status=built\nimage={args.out}\nsha256={sha256(args.out)}")


if __name__ == "__main__":
    main()
