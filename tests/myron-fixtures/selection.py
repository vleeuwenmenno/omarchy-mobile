# SPDX-License-Identifier: MIT
"""Synthetic flattened device tree and DT table builders for the Myron R4 selection tests.

Test-side and deliberately independent of every tool: the layout facts below restate the
devicetree specification's flattened device tree (version 17) format and the AOSP DT table
(DTBO) format with their own arithmetic, so a drift in tools/lib/myron-bootchain-impl.py cannot
make these fixtures agree with it by accident. Every builder returns bytes generated at runtime
(no binary fixture is committed). No real firmware, vendor byte or identifier is used: every
compatible string is the contract constant or an obviously synthetic token."""

import struct

COMPATIBLE = b"qcom,canoe-mtp"
FDT_MAGIC = 0xD00DFEED
BEGIN_NODE, END_NODE, PROP, NOP, END = 1, 2, 3, 4, 9
HEADER_FIELDS = ("magic", "totalsize", "off_dt_struct", "off_dt_strings", "off_mem_rsvmap", "version",
                 "last_comp_version", "boot_cpuid_phys", "size_dt_strings", "size_dt_struct")


def be32(value: int) -> bytes:
    return struct.pack(">I", value)


def pad4(data: bytes) -> bytes:
    return data + bytes(-len(data) % 4)


def strlist(*tokens: bytes) -> bytes:
    return b"".join(token + b"\0" for token in tokens)


def node(name: bytes, props=(), children=()) -> dict:
    return {"name": name, "props": list(props), "children": list(children)}


class Strings:
    def __init__(self):
        self.blob = bytearray()
        self.offsets = {}

    def add(self, name: bytes) -> int:
        if name not in self.offsets:
            self.offsets[name] = len(self.blob)
            self.blob += name + b"\0"
        return self.offsets[name]


def emit(item: dict, strings: Strings, depth_nops: int = 0) -> bytes:
    out = bytearray(be32(BEGIN_NODE) + pad4(item["name"] + b"\0"))
    for name, value in item["props"]:
        out += be32(PROP) + be32(len(value)) + be32(strings.add(name)) + pad4(value)
    for child in item["children"]:
        out += emit(child, strings)
    out += be32(END_NODE)
    return bytes(out)


def chain(depth: int, leaf_name: bytes = b"leaf") -> dict:
    """A single-child chain DEPTH nodes deep below the root: root depth 1, deepest node depth + 1."""
    item = node(leaf_name)
    for level in range(depth - 1, 0, -1):
        item = node(b"n%d" % level, children=[item])
    return item


def fdt(compatible=(COMPATIBLE,), *, root_props=(), children=(), reserve=(), version=17, last_comp=16, pad=0,
        header=None, struct_raw=None, strings_raw=None, root_compatible=None, nops=0, root_name=b"",
        extra_after_end=b"", gap=0, align=True) -> bytes:
    """One v17 blob: header, reserve map, structure block, strings block, then PAD zero bytes.
    COMPATIBLE is the root stringlist (None omits the property); ROOT_COMPATIBLE overrides the raw value."""
    strings = Strings()
    props = list(root_props)
    if root_compatible is not None:
        props.insert(0, (b"compatible", root_compatible))
    elif compatible is not None:
        props.insert(0, (b"compatible", strlist(*compatible)))
    root = node(root_name, props, children)
    structure = emit(root, strings) + be32(NOP) * nops + be32(END) + extra_after_end if struct_raw is None else struct_raw
    string_block = bytes(strings.blob) if strings_raw is None else strings_raw
    reserve_map = b"".join(struct.pack(">QQ", address, size) for address, size in reserve) + bytes(16)
    off_reserve = 40
    off_struct = off_reserve + len(reserve_map) + gap
    off_strings = off_struct + len(structure)
    pad += -(off_strings + len(string_block) + pad) % 8 if align else 0
    total = off_strings + len(string_block) + pad
    fields = {"magic": FDT_MAGIC, "totalsize": total, "off_dt_struct": off_struct, "off_dt_strings": off_strings,
              "off_mem_rsvmap": off_reserve, "version": version, "last_comp_version": last_comp,
              "boot_cpuid_phys": 0, "size_dt_strings": len(string_block), "size_dt_struct": len(structure)}
    fields.update(header or {})
    head = b"".join(be32(fields[name]) for name in HEADER_FIELDS)
    blob = bytearray(off_strings + len(string_block) + pad)
    blob[:40] = head
    blob[off_reserve:off_reserve + len(reserve_map)] = reserve_map
    blob[off_struct:off_struct + len(structure)] = structure
    blob[off_strings:off_strings + len(string_block)] = string_block
    return bytes(blob)


def sized_fdt(size: int, compatible=(COMPATIBLE,), **kwargs) -> bytes:
    """A valid blob whose total size is exactly SIZE: the slack is zero padding inside the blob."""
    base = fdt(compatible, align=False, **kwargs)
    assert len(base) <= size, (len(base), size)
    return fdt(compatible, pad=size - len(base), align=False, **kwargs)


def many_properties(count: int) -> list:
    return [(b"p%d" % index, be32(index)) for index in range(count)]


def many_nodes(count: int) -> list:
    """COUNT children below the root: the blob then holds COUNT + 1 nodes."""
    return [node(b"c%d" % index) for index in range(count)]


def dtbo(entries, *, page=2048) -> bytes:
    """DT table v0: header, entry table at offset 32, payloads placed back to back after it.
    ENTRIES: dicts with payload, id, rev and optional custom (four words)."""
    table = 32 + 32 * len(entries)
    cursor, rows, payloads = table, bytearray(), bytearray()
    for item in entries:
        custom = item.get("custom", (0, 0, 0, 0))
        rows += struct.pack(">IIII4I", len(item["payload"]), cursor, item["id"], item["rev"], *custom)
        payloads += item["payload"]
        cursor += len(item["payload"])
    head = struct.pack(">IIIIIIII", 0xD7B7AB1E, cursor, 32, 32, len(entries), 32, page, 0)
    return head + bytes(rows) + bytes(payloads)


def entry(payload: bytes, ident: int, revision: int, custom=(0, 0, 0, 0)) -> dict:
    return {"payload": payload, "id": ident, "rev": revision, "custom": custom}
