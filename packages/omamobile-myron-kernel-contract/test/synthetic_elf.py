# SPDX-License-Identifier: MIT
"""Synthetic AArch64 ET_REL "module" generator shared by the offline ABI tests.

Every ELF is built at test runtime from synthetic bytes; nothing here is a real
kernel module. Loaded by path (tests run with python3 -I), never installed.
"""
import struct

RELEASE = "test-release"
VERMAGIC = f"{RELEASE} SMP preempt mod_unload modversions aarch64"


def build_elf(name, imports=(), exports=(), versions=None, modinfo=None,
              vermagic=VERMAGIC, e_type=1, machine=183, ei_class=2, ei_data=1,
              fix=None, extra_sections=(), extra_symbols=()):
    entries = modinfo if modinfo is not None else [
        f"name={name}", f"vermagic={vermagic}", "license=GPL"]
    sections = [(".modinfo", 1, 2, b"".join(e.encode() + b"\0" for e in entries), 0, 0, 0)]
    for symbol, kind, _crc in exports:
        suffix = "_gpl" if kind == "EXPORT_SYMBOL_GPL" else ""
        sections.append((f"___ksymtab{suffix}+{symbol}", 1, 2, b"\0" * 8, 0, 0, 0))
    sections += list(extra_sections)
    if versions is not None:
        data = b"".join(struct.pack("<Q56s", crc, sym.encode()) for sym, crc in versions)
        sections.append(("__versions", 1, 2, data, 0, 0, 0))
    strtab = bytearray(b"\0")
    def add(text):
        offset = len(strtab)
        strtab.extend(text.encode() + b"\0")
        return offset
    symbols = [struct.pack("<IBBHQQ", 0, 0, 0, 0, 0, 0),
               struct.pack("<IBBHQQ", add("mod.c"), 4, 0, 0xFFF1, 0, 0)]
    first_global = len(symbols)
    for index, (symbol, kind, crc) in enumerate(exports):
        symbols.append(struct.pack("<IBBHQQ", add(f"__ksymtab_{symbol}"), 0x11, 0, 2 + index, 0, 8))
        if crc is not None:
            symbols.append(struct.pack("<IBBHQQ", add(f"__crc_{symbol}"), 0x10, 0, 0xFFF1, crc, 0))
    for symbol, shndx, info, value in extra_symbols:
        symbols.append(struct.pack("<IBBHQQ", add(symbol), info, 0, shndx, value, 0))
    for symbol, bind in imports:
        symbols.append(struct.pack("<IBBHQQ", add(symbol), (2 if bind == "weak" else 1) << 4, 0, 0, 0, 0))
    count = len(sections)
    symtab_index, strtab_index, shstr_index = count + 1, count + 2, count + 3
    sections.append((".symtab", 2, 0, b"".join(symbols), strtab_index, first_global, 24))
    sections.append((".strtab", 3, 0, bytes(strtab), 0, 0, 0))
    shstr = bytearray(b"\0")
    name_offsets = []
    for section in sections + [(".shstrtab",)]:
        name_offsets.append(len(shstr))
        shstr.extend(section[0].encode() + b"\0")
    sections.append((".shstrtab", 3, 0, bytes(shstr), 0, 0, 0))
    body = bytearray(64)
    headers = [struct.pack("<IIQQQQIIQQ", *([0] * 10))]
    for offset_name, (sec_name, kind, flags, data, link, info, entsize) in zip(name_offsets, sections):
        while len(body) % 8:
            body.append(0)
        headers.append(struct.pack("<IIQQQQIIQQ", offset_name, kind, flags, 0,
                                   len(body), len(data), link, info, 8, entsize))
        body.extend(data)
    while len(body) % 8:
        body.append(0)
    shoff = len(body)
    for header in headers:
        body.extend(header)
    ident = b"\x7fELF" + bytes([ei_class, ei_data, 1, 0, 0]) + bytes(7)
    body[:64] = ident + struct.pack("<HHIQQQIHHHHHH", e_type, machine, 1, 0, 0, shoff, 0,
                                    64, 0, 0, 64, len(headers), len(headers) - 1)
    if fix:
        fix(body)
    return bytes(body)
