# SPDX-License-Identifier: MIT
"""Synthetic Android boot, vendor_boot and DT table image builders for the Myron tests.

Test-side and deliberately independent of every tool: the layout facts below restate the
AOSP boot image header, vendor boot image header and DT table (DTBO) documents a reviewer can
check, with their own arithmetic, so a drift in tools/lib/myron-bootchain-impl.py cannot make
these fixtures agree with it by accident. Every builder returns (bytes, meta): the bytes are
generated at runtime and exist only in a temporary directory (no binary fixture is committed),
and meta records where the builder itself placed each structure, so tests can compare the
parser's output against placements it did not compute. No real firmware, vendor byte or
identifier is used: payload bytes are repeated synthetic patterns."""

import hashlib
import struct

KIB = 1024
MIB = 1024 * KIB
MAX_SYNTHETIC_IMAGE_BYTES = 16 * MIB
MAX_VENDOR_FRAGMENTS = 64
MAX_DT_ENTRIES = 256
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
BOOT_HEADER = {0: 1632, 1: 1648, 2: 1660, 3: 1580, 4: 1584}
VENDOR_HEADER = {3: 2112, 4: 2128}
OS_VERSION = 0x7E100000
CANARY_NAME = b"canaryq7k2"
CANARY_VALUE = 0x5EEDBEEF


def align(value: int, page: int) -> int:
    return (value + page - 1) // page * page


def blob(label: str, size: int) -> bytes:
    """A deterministic synthetic payload of exactly SIZE bytes that differs per label."""
    if size < 0 or size > MAX_SYNTHETIC_IMAGE_BYTES:
        raise ValueError("synthetic fixture placement exceeds its allocation bound")
    seed = hashlib.sha256(label.encode()).digest()
    return (seed * (size // len(seed) + 1))[:size]


def component(role, index, offset, size, ramdisk_type=None) -> dict:
    return {"role": role, "index": index, "offset": offset, "size": size, "ramdisk_type": ramdisk_type}


def grow(image: bytearray, end: int) -> None:
    """Grow one synthetic image only after checking the parser's image-size ceiling."""
    if end < 0 or end > MAX_SYNTHETIC_IMAGE_BYTES:
        raise ValueError("synthetic fixture placement exceeds its allocation bound")
    if len(image) < end:
        image.extend(bytes(end - len(image)))


def place(image: bytearray, offset: int, data: bytes) -> None:
    if not data:
        return
    end = offset + len(data)
    if offset < 0:
        raise ValueError("synthetic fixture placement exceeds its allocation bound")
    grow(image, end)
    image[offset:end] = data


def boot_legacy(version, *, kernel=b"", ramdisk=b"", second=b"", dtbo=b"", dtb=b"", page=4096,
                os_version=OS_VERSION, dtbo_offset=None, header_size=None, magic=b"ANDROID!",
                pad=True, version_field=None, kernel_size=None):
    """Android boot image v0, v1 or v2: little endian, kernel at one page, then page-aligned
    ramdisk, second, recovery_dtbo and dtb."""
    size = BOOT_HEADER[version]
    header = bytearray(size)
    header[:8] = magic
    sections = [("kernel", kernel), ("ramdisk", ramdisk), ("second", second)]
    if version >= 1:
        sections.append(("recovery_dtbo", dtbo))
    if version >= 2:
        sections.append(("dtb", dtb))
    struct.pack_into("<I", header, 8, len(kernel) if kernel_size is None else kernel_size)
    struct.pack_into("<I", header, 16, len(ramdisk))
    struct.pack_into("<I", header, 24, len(second))
    struct.pack_into("<I", header, 36, page)
    struct.pack_into("<I", header, 40, version if version_field is None else version_field)
    struct.pack_into("<I", header, 44, os_version)
    cursor, components, image = page, [], bytearray(header)
    for role, data in sections:
        components.append(component(role, 0, cursor, len(data)))
        if role == "recovery_dtbo":
            stored = cursor if len(data) else 0
            struct.pack_into("<IQI", header, 1632, len(data), stored if dtbo_offset is None else dtbo_offset,
                             size if header_size is None else header_size)
        if role == "dtb":
            struct.pack_into("<I", header, 1648, len(data))
        place(image, cursor, data)
        cursor += align(len(data), page)
    image[:size] = header
    if pad:
        grow(image, cursor)
    meta = {"format": "android-boot", "version": version, "page_size": page, "os_version": os_version,
            "header": size, "table": None, "components": components}
    return bytes(image), meta


def boot_modern(version, *, kernel=b"", ramdisk=b"", signature=b"", os_version=OS_VERSION,
                header_size=None, magic=b"ANDROID!", pad=True):
    """Android boot image v3 or v4: little endian, fixed 4096-byte pages."""
    page, size = 4096, BOOT_HEADER[version]
    header = bytearray(size)
    header[:8] = magic
    struct.pack_into("<IIII", header, 8, len(kernel), len(ramdisk), os_version,
                     size if header_size is None else header_size)
    struct.pack_into("<I", header, 40, version)
    components = [component("kernel", 0, page, len(kernel))]
    ramdisk_offset = page + align(len(kernel), page)
    components.append(component("ramdisk", 0, ramdisk_offset, len(ramdisk)))
    cursor = ramdisk_offset + align(len(ramdisk), page)
    if version == 4:
        struct.pack_into("<I", header, 1580, len(signature))
        components.append(component("boot_signature", 0, cursor, len(signature)))
    image = bytearray(header)
    place(image, page, kernel)
    place(image, ramdisk_offset, ramdisk)
    if version == 4:
        place(image, cursor, signature)
        cursor += align(len(signature), page)
    if pad:
        grow(image, cursor)
    meta = {"format": "android-boot", "version": version, "page_size": page, "os_version": os_version,
            "header": size, "table": None, "components": components}
    return bytes(image), meta


def fragment(label, size, ramdisk_type=1, name=None, rel=None, entry_size=None):
    return {"data": blob(label, size), "type": ramdisk_type, "name": name, "rel": rel,
            "size": entry_size}


def vendor(version, *, page=4096, ramdisk=b"", fragments=(), dtb=b"", bootconfig=b"", header_size=None,
           magic=b"VNDRBOOT", section_size=None, table_entry_size=108, table_count=None,
           table_size=None, name_fill=None, pad=True):
    """vendor_boot v3 or v4: little endian, VNDRBOOT. v4 fragments place sequentially unless a
    `rel` offset is given; table rows keep the listed order whatever the offsets are."""
    size = VENDOR_HEADER[version]
    header = bytearray(size)
    header[:8] = magic
    span = align(size, page)
    struct.pack_into("<II", header, 8, version, page)
    struct.pack_into("<I", header, 2096, size if header_size is None else header_size)
    struct.pack_into("<I", header, 2100, len(dtb))
    components, image = [], bytearray(header)
    if version == 3:
        struct.pack_into("<I", header, 24, len(ramdisk))
        components.append(component("vendor_ramdisk", 0, span, len(ramdisk)))
        dtb_offset = span + align(len(ramdisk), page)
        components.append(component("dtb", 0, dtb_offset, len(dtb)))
        place(image, span, ramdisk)
        place(image, dtb_offset, dtb)
        cursor = dtb_offset + align(len(dtb), page)
        table = None
    else:
        entries, cursor_rel, end, fragment_count = bytearray(), 0, 0, 0
        for index, item in enumerate(fragments):
            if index >= MAX_VENDOR_FRAGMENTS:
                raise ValueError("synthetic fixture placement exceeds its allocation bound")
            rel = cursor_rel if item["rel"] is None else item["rel"]
            if item["rel"] is None:
                cursor_rel += len(item["data"])
            end = max(end, rel + len(item["data"]))
            name = (item["name"] if item["name"] is not None else b"frag%d" % index)
            if name_fill is None:
                if len(name) > VENDOR_NAME_FIELD:
                    raise ValueError("synthetic fixture placement exceeds its allocation bound")
                field = name + bytes(VENDOR_NAME_FIELD - len(name))
            else:
                field = name_fill
            entry_length = 12 + len(field) + 64
            if len(entries) + entry_length > MAX_SYNTHETIC_IMAGE_BYTES:
                raise ValueError("synthetic fixture placement exceeds its allocation bound")
            length = len(item["data"]) if item["size"] is None else item["size"]
            entry = struct.pack("<III", length, rel, item["type"]) + field + bytes(64)
            place(entries, len(entries), entry)
            place(image, span + rel, item["data"])
            components.append(component("vendor_ramdisk_fragment", index, span + rel,
                                        len(item["data"]), item["type"]))
            fragment_count += 1
        total = end if section_size is None else section_size
        struct.pack_into("<I", header, 24, total)
        dtb_offset = span + align(total, page)
        table_offset = dtb_offset + align(len(dtb), page)
        count = fragment_count if table_count is None else table_count
        tsize = len(entries) if table_size is None else table_size
        struct.pack_into("<IIII", header, 2112, tsize, count, table_entry_size, len(bootconfig))
        bootconfig_offset = table_offset + align(tsize, page)
        components.append(component("dtb", 0, dtb_offset, len(dtb)))
        components.append(component("bootconfig", 0, bootconfig_offset, len(bootconfig)))
        place(image, dtb_offset, dtb)
        place(image, table_offset, bytes(entries))
        place(image, bootconfig_offset, bootconfig)
        cursor = bootconfig_offset + align(len(bootconfig), page)
        table = {"role": "vendor_ramdisk_table", "offset": table_offset, "size": len(entries),
                 "entry_size": 108, "count": fragment_count}
    image[:size] = header
    if pad:
        grow(image, cursor)
    meta = {"format": "android-vendor-boot", "version": version, "page_size": page, "os_version": None,
            "header": size, "table": table, "components": components}
    return bytes(image), meta


VENDOR_NAME_FIELD = 32


def dt_table(payloads, *, page=2048, entries_offset=32, version=0, total_size=None, trailing=b"",
             offsets=None, entry_size=32, header_size=32, count=None, magic=0xD7B7AB1E, gap=b""):
    """DT table v0: big endian, an explicit table offset and explicit payload offsets, no page
    alignment. OFFSETS (a list) overrides the sequential payload placement of entries."""
    if len(payloads) > MAX_DT_ENTRIES:
        raise ValueError("synthetic fixture placement exceeds its allocation bound")
    table_size = len(payloads) * 32
    cursor = entries_offset + table_size
    placed = []
    for index, data in enumerate(payloads):
        offset = cursor if offsets is None or offsets[index] is None else offsets[index]
        if offsets is None or offsets[index] is None:
            cursor += len(data)
        placed.append((offset, data))
    end = max([cursor] + [offset + len(data) for offset, data in placed])
    total = end if total_size is None else total_size
    image = bytearray()
    grow(image, entries_offset + table_size)
    n = len(payloads) if count is None else count
    struct.pack_into(">IIIIIIII", image, 0, magic, total, header_size, entry_size, n, entries_offset,
                     page, version)
    components = []
    for index, (offset, data) in enumerate(placed):
        struct.pack_into(">IIIIIIII", image, entries_offset + index * 32, len(data), offset,
                         CANARY_VALUE, CANARY_VALUE + 1, 7, 8, 9, 10)
        place(image, offset, data)
        components.append(component("dt_entry", index, offset, len(data)))
    place(image, len(image), gap)
    grow(image, total)
    place(image, len(image), trailing)
    meta = {"format": "android-dt-table", "version": 0, "page_size": page, "os_version": None,
            "header": 32,
            "table": {"role": "dt_entry_table", "offset": entries_offset, "size": table_size,
                      "entry_size": 32, "count": len(payloads)},
            "components": components}
    return bytes(image), meta


# --- the independent expected evidence --------------------------------------------


def merge(extents):
    merged = []
    for offset, size in sorted(extents):
        if merged and offset <= merged[-1][0] + merged[-1][1]:
            end = max(merged[-1][0] + merged[-1][1], offset + size)
            merged[-1] = (merged[-1][0], end - merged[-1][0])
        else:
            merged.append((offset, size))
    return merged


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def expected(data: bytes, meta: dict) -> dict:
    """The R3 image object this builder's own placements imply, metadata-only."""
    header = meta["header"]
    table = meta["table"]
    extents = [(0, header)]
    if table and table["size"]:
        extents.append((table["offset"], table["size"]))
    ranges = merge(extents)
    components = []
    for item in sorted(meta["components"], key=lambda row: (row["role"], row["index"])):
        inside = item["size"] and any(a <= item["offset"] and item["offset"] + item["size"] <= a + b
                                      for a, b in ranges)
        components.append({
            "role": item["role"], "index": item["index"], "offset": item["offset"],
            "size_bytes": item["size"],
            "sha256": sha(data[item["offset"]:item["offset"] + item["size"]]) if inside else None,
            "ramdisk_type": item["ramdisk_type"],
        })
    return {
        "format": meta["format"], "version": meta["version"], "page_size": meta["page_size"],
        "os_version": meta["os_version"], "size_bytes": len(data), "sha256": None,
        "header": {"offset": 0, "size_bytes": header, "sha256": sha(data[:header])},
        "components": components,
        "table": None if table is None else {
            "role": table["role"], "offset": table["offset"], "size_bytes": table["size"],
            "sha256": sha(data[table["offset"]:table["offset"] + table["size"]]) if table["size"] else EMPTY_SHA256,
            "entry_size": table["entry_size"], "entry_count": table["count"],
        },
        "coverage": {
            "kind": "metadata-only",
            "ranges": [{"index": i, "offset": a, "size_bytes": b} for i, (a, b) in enumerate(ranges)],
            "covered_bytes": sum(b for _a, b in ranges),
        },
    }
