# SPDX-License-Identifier: MIT
"""Synthetic R3 image-summary builders shared by the Myron tests.

Test-side and deliberately independent of every tool: the profile tables below restate the
AOSP boot, vendor_boot and DT table header facts a reviewer can check against the format
documents, so a drift in a tool's profile cannot make these fixtures agree with it by
accident. They build claims only. No image bytes exist, nothing is parsed and no hash is
the digest of real content."""

import copy
import hashlib

MIB = 1024 * 1024
PAGE = 4096
SUFFIXES = ["", "_a", "_b"]
ROLES = ["boot", "init_boot", "vendor_boot", "vendor_kernel_boot", "dtbo", "recovery"]
NAMES = sorted(role + suffix for role in ROLES for suffix in SUFFIXES)
ROLE_FORMAT = {
    "boot": "android-boot", "recovery": "android-boot", "init_boot": "android-boot",
    "vendor_boot": "android-vendor-boot", "vendor_kernel_boot": "android-vendor-boot",
    "dtbo": "android-dt-table",
}
ROLE_VERSIONS = {
    "boot": [0, 1, 2, 3, 4], "recovery": [0, 1, 2, 3, 4], "init_boot": [4],
    "vendor_boot": [3, 4], "vendor_kernel_boot": [3, 4], "dtbo": [0],
}
HEADER_BYTES = {
    ("android-boot", 0): 1632, ("android-boot", 1): 1648, ("android-boot", 2): 1660,
    ("android-boot", 3): 1580, ("android-boot", 4): 1584,
    ("android-vendor-boot", 3): 2112, ("android-vendor-boot", 4): 2128,
    ("android-dt-table", 0): 32,
}
SLOTS = {
    ("android-boot", 0): ["kernel", "ramdisk", "second"],
    ("android-boot", 1): ["kernel", "ramdisk", "second", "recovery_dtbo"],
    ("android-boot", 2): ["kernel", "ramdisk", "second", "recovery_dtbo", "dtb"],
    ("android-boot", 3): ["kernel", "ramdisk"],
    ("android-boot", 4): ["kernel", "ramdisk", "boot_signature"],
    ("android-vendor-boot", 3): ["vendor_ramdisk", "dtb"],
    ("android-vendor-boot", 4): ["vendor_ramdisk_fragment", "dtb", "bootconfig"],
    ("android-dt-table", 0): ["dt_entry"],
}
COUNTED = {"vendor_ramdisk_fragment", "dt_entry"}  # one component per table entry
TABLES = {
    ("android-vendor-boot", 4): ("vendor_ramdisk_table", 108),
    ("android-dt-table", 0): ("dt_entry_table", 32),
}
ZERO_ROLES = {"second", "bootconfig"}  # emitted with size zero by default
FIXED_PAGE = {("android-boot", 3): 4096, ("android-boot", 4): 4096}
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


def digest(label) -> str:
    return hashlib.sha256(str(label).encode()).hexdigest()


def role_of(name: str) -> str:
    return name[:-2] if name.endswith(("_a", "_b")) else name


def round_up(value: int, unit: int = PAGE) -> int:
    return (value + unit - 1) // unit * unit


def normalize(extents) -> list:
    """Sorted, merged (overlapping and adjacent) coverage ranges, indexed from zero."""
    merged = []
    for offset, size in sorted(extents):
        if merged and offset <= merged[-1][0] + merged[-1][1]:
            end = max(merged[-1][0] + merged[-1][1], offset + size)
            merged[-1] = (merged[-1][0], end - merged[-1][0])
        else:
            merged.append((offset, size))
    return [{"index": i, "offset": o, "size_bytes": s} for i, (o, s) in enumerate(merged)]


def covers(ranges, offset: int, size: int) -> bool:
    return any(
        item["offset"] <= offset and offset + size <= item["offset"] + item["size_bytes"]
        for item in ranges
    )


def make_image(name, version, kind="metadata-only", *, entries=2, page=None, os_version=None,
               cover=(), zero=None, component_bytes=PAGE):
    """One canonical image summary. COVER names components `(role, index)` that a
    metadata-only coverage reaches in full (so they carry a hash)."""
    role = role_of(name)
    fmt = ROLE_FORMAT[role]
    header = HEADER_BYTES[(fmt, version)]
    table_role, entry_bytes = TABLES.get((fmt, version), (None, 0))
    table_size = entries * entry_bytes if table_role else 0
    table_offset = header
    keys = []
    for slot in SLOTS[(fmt, version)]:
        keys += [(slot, i) for i in range(entries)] if slot in COUNTED else [(slot, 0)]
    keys.sort()
    zero_roles = ZERO_ROLES | ({"kernel"} if role == "init_boot" else set()) if zero is None else zero
    cursor = round_up(header + table_size)
    components = []
    for component_role, index in keys:
        size = 0 if component_role in zero_roles else component_bytes
        components.append({
            "role": component_role, "index": index, "offset": cursor, "size_bytes": size,
            "sha256": None,
            "ramdisk_type": index % 4 if component_role == "vendor_ramdisk_fragment" else None,
        })
        cursor += size
    size_bytes = cursor + PAGE
    if kind == "full-image":
        extents = [(0, size_bytes)]
    else:
        extents = [(0, header + table_size)]
        for item in components:
            if (item["role"], item["index"]) in set(cover) and item["size_bytes"]:
                extents.append((item["offset"], item["size_bytes"]))
    ranges = normalize(extents)
    for item in components:
        if item["size_bytes"] and covers(ranges, item["offset"], item["size_bytes"]):
            item["sha256"] = digest(f"{name}/{item['role']}/{item['index']}")
    table = None
    if table_role:
        table = {
            "role": table_role, "offset": table_offset, "size_bytes": table_size,
            "sha256": digest(f"{name}/table") if table_size else EMPTY_SHA256,
            "entry_size": entry_bytes, "entry_count": entries,
        }
    if os_version is None and fmt == "android-boot":
        os_version = 0x7E100000
    return {
        "format": fmt, "version": version,
        "page_size": FIXED_PAGE.get((fmt, version), page or PAGE),
        "os_version": os_version if fmt == "android-boot" else None,
        "size_bytes": size_bytes,
        "sha256": digest(f"{name}/image") if kind == "full-image" else None,
        "header": {"offset": 0, "size_bytes": header, "sha256": digest(f"{name}/header")},
        "components": components,
        "table": table,
        "coverage": {
            "kind": kind, "ranges": ranges,
            "covered_bytes": sum(item["size_bytes"] for item in ranges),
        },
    }


def image_rows(images: dict) -> list:
    """All 18 rows in canonical order; a name missing from IMAGES is a null image."""
    return [
        {"partition_name": name, "role": role_of(name), "image": images.get(name)}
        for name in NAMES
    ]


def default_images() -> dict:
    """A representative present set: a mix of formats, versions and both coverage kinds."""
    return {
        "boot_a": make_image("boot_a", 4),
        "boot_b": make_image("boot_b", 2, "full-image"),
        "dtbo_a": make_image("dtbo_a", 0),
        "init_boot_a": make_image("init_boot_a", 4),
        "recovery_a": make_image("recovery_a", 3, "full-image"),
        "vendor_boot_a": make_image("vendor_boot_a", 4, cover=[("dtb", 0)]),
    }


def default_rows() -> list:
    return image_rows(default_images())


def partition_rows(rows, extra=(), capacity=None) -> list:
    """R2 partition dicts matching ROWS: every name with an image, plus EXTRA (name, size)."""
    sizes = {
        row["partition_name"]: (capacity or {}).get(row["partition_name"], 96 * MIB)
        for row in rows if row["image"] is not None
    }
    sizes.update(dict(extra))
    return [
        {
            "partition_name": name, "size_bytes": size, "bootable_flag": name == "boot_a",
            "slot_suffix": name[-2:] if name.endswith(("_a", "_b")) else "",
        }
        for name, size in sorted(sizes.items())
    ]


def clone(value):
    return copy.deepcopy(value)
