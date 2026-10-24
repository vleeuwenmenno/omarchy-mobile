# SPDX-License-Identifier: MIT
"""Synthetic AArch64 ET_REL "module" generator shared by the offline ABI tests.

Every ELF is built at test runtime from synthetic bytes; nothing here is a real
kernel module. Loaded by path (tests run with python3 -I), never installed.
"""
import struct

RELEASE = "test-release"
VERMAGIC = f"{RELEASE} SMP preempt mod_unload modversions aarch64"


def build_elf(name, imports=(), exports=(), versions=None, extended_versions=None,
              modinfo=None, vermagic=VERMAGIC, e_type=1, machine=183,
              ei_class=2, ei_data=1, fix=None, extra_sections=(),
              extra_symbols=(), ksymtab_size=8, export_symbols="global-object",
              crc_layout="absolute", relocations=(), merged_exports=False,
              crc_symbol_offsets=None, sort_merged_exports=True,
              real_export_names=False, export_name_targets=None,
              runtime_name_values=None, runtime_name_addends=None,
              export_namespaces=None,
              runtime_namespace_relocations=True,
              runtime_name_symbol_style="named",
              runtime_name_relocation_kind="rela"):
    entries = modinfo if modinfo is not None else [
        f"name={name}", f"vermagic={vermagic}", "license=GPL"]
    sections = [(".modinfo", 1, 2, b"".join(e.encode() + b"\0" for e in entries), 0, 0, 0)]
    suffixes = {
        "EXPORT_SYMBOL": "", "EXPORT_SYMBOL_GPL": "_gpl",
        "EXPORT_UNUSED_SYMBOL": "_unused",
        "EXPORT_UNUSED_SYMBOL_GPL": "_unused_gpl",
    }
    export_section_indexes = {}
    export_offsets = {}
    crc_section_indexes = {}
    crc_offsets = {}
    if merged_exports:
        groups = {}
        for export in exports:
            groups.setdefault(suffixes[export[1]], []).append(export)
        for suffix, group in groups.items():
            if sort_merged_exports:
                group = sorted(group, key=lambda export: export[0])
            section_index = len(sections) + 1
            sections.append((f"__ksymtab{suffix}", 1, 2,
                             b"\0" * (ksymtab_size * len(group)), 0, 0, 0))
            for position, (symbol, _kind, _crc) in enumerate(group):
                export_section_indexes[symbol] = section_index
                export_offsets[symbol] = position * ksymtab_size
            crc_group = [export for export in group if export[2] is not None]
            if crc_layout == "section" and crc_group:
                crc_index = len(sections) + 1
                sections.append((f"__kcrctab{suffix}", 1, 2,
                                 b"".join(struct.pack("<I", export[2])
                                          for export in crc_group), 0, 0, 0))
                for position, (symbol, _kind, _crc) in enumerate(crc_group):
                    crc_section_indexes[symbol] = crc_index
                    crc_offsets[symbol] = position * 4
    else:
        for symbol, kind, crc in exports:
            suffix = suffixes[kind]
            export_section_indexes[symbol] = len(sections) + 1
            export_offsets[symbol] = 0
            sections.append((f"___ksymtab{suffix}+{symbol}", 1, 2,
                             b"\0" * ksymtab_size, 0, 0, 0))
            if crc is not None and crc_layout == "section":
                crc_section_indexes[symbol] = len(sections) + 1
                crc_offsets[symbol] = 0
                sections.append((f"___kcrctab{suffix}+{symbol}", 1, 2,
                                 struct.pack("<I", crc), 0, 0, 0))
    runtime_name_offsets = {}
    runtime_namespace_offsets = {}
    runtime_name_section = None
    if real_export_names:
        runtime_name_section = len(sections) + 1
        runtime_names = bytearray()
        for symbol in sorted({export[0] for export in exports}):
            runtime_name_offsets[symbol] = len(runtime_names)
            value = (runtime_name_values or {}).get(symbol, symbol)
            runtime_names.extend(value.encode() + b"\0")
            runtime_namespace_offsets[symbol] = len(runtime_names)
            namespace = (export_namespaces or {}).get(symbol, "")
            runtime_names.extend(namespace.encode() + b"\0")
        sections.append(("__ksymtab_strings", 1, 2, bytes(runtime_names), 0, 0, 0))
    sections += list(extra_sections)
    if versions is not None:
        data = b"".join(struct.pack("<Q56s", crc, sym.encode()) for sym, crc in versions)
        sections.append(("__versions", 1, 2, data, 0, 0, 0))
    if extended_versions is not None:
        names = b"".join(sym.encode() + b"\0" for sym, _crc in extended_versions) + b"\0"
        crcs = b"".join(struct.pack("<I", crc) for _sym, crc in extended_versions)
        sections.append(("__version_ext_names", 1, 2, names, 0, 0, 0))
        sections.append(("__version_ext_crcs", 1, 2, crcs, 0, 0, 0))
    relocation_indexes = []
    for section_name, target_name, kind, records in relocations:
        if kind == "rel":
            data = b"".join(struct.pack("<QQ", offset, symbol << 32 | rel_type)
                            for offset, symbol, rel_type in records)
            section_kind, entsize = 9, 16
        elif kind == "rela":
            data = b"".join(struct.pack("<QQq", offset, symbol << 32 | rel_type, addend)
                            for offset, symbol, rel_type, addend in records)
            section_kind, entsize = 4, 24
        else:
            raise ValueError(f"unknown relocation kind: {kind}")
        relocation_indexes.append((len(sections), target_name))
        sections.append((section_name, section_kind, 0x40, data, 0, 0, entsize))
    strtab = bytearray(b"\0")
    def add(text):
        offset = len(strtab)
        strtab.extend(text.encode() + b"\0")
        return offset
    local_symbols = [struct.pack("<IBBHQQ", 0, 0, 0, 0, 0, 0),
                     struct.pack("<IBBHQQ", add("mod.c"), 4, 0, 0xFFF1, 0, 0)]
    global_symbols = []
    runtime_name_symbols = {}
    runtime_namespace_symbols = {}
    if real_export_names:
        if runtime_name_symbol_style == "named":
            for symbol in sorted(runtime_name_offsets):
                runtime_name_symbols[symbol] = len(local_symbols)
                local_symbols.append(struct.pack(
                    "<IBBHQQ", add(f"__kstrtab_{symbol}"), 0x00, 0,
                    runtime_name_section, runtime_name_offsets[symbol], 0))
                runtime_namespace_symbols[symbol] = len(local_symbols)
                local_symbols.append(struct.pack(
                    "<IBBHQQ", add(f"__kstrtabns_{symbol}"), 0x00, 0,
                    runtime_name_section, runtime_namespace_offsets[symbol], 0))
        elif runtime_name_symbol_style == "section":
            section_symbol = len(local_symbols)
            local_symbols.append(struct.pack(
                "<IBBHQQ", 0, 0x03, 0, runtime_name_section, 0, 0))
            runtime_name_symbols = {
                symbol: section_symbol for symbol in runtime_name_offsets
            }
            runtime_namespace_symbols = dict(runtime_name_symbols)
        else:
            raise ValueError(
                f"unknown runtime-name symbol style: {runtime_name_symbol_style}"
            )
    for symbol, _kind, crc in exports:
        if export_symbols == "local-label":
            local_symbols.append(struct.pack(
                "<IBBHQQ", add(f"__ksymtab_{symbol}"), 0x00, 0,
                export_section_indexes[symbol], export_offsets[symbol], 0))
        elif export_symbols == "global-object":
            global_symbols.append(struct.pack(
                "<IBBHQQ", add(f"__ksymtab_{symbol}"), 0x11, 0,
                export_section_indexes[symbol], export_offsets[symbol], ksymtab_size))
        else:
            raise ValueError(f"unknown export symbol style: {export_symbols}")
        if crc is not None:
            if crc_layout == "absolute":
                global_symbols.append(struct.pack(
                    "<IBBHQQ", add(f"__crc_{symbol}"), 0x10, 0, 0xFFF1, crc, 0))
            elif crc_layout == "section":
                target = crc_section_indexes[symbol]
                destination = local_symbols if export_symbols == "local-label" else global_symbols
                value = (crc_symbol_offsets or {}).get(symbol, crc_offsets[symbol])
                destination.append(struct.pack(
                    "<IBBHQQ", add(f"__crc_{symbol}"),
                    0x00 if export_symbols == "local-label" else 0x10,
                    0, target, value, 0))
            else:
                raise ValueError(f"unknown CRC layout: {crc_layout}")
    first_global = len(local_symbols)
    for symbol, shndx, info, value in extra_symbols:
        global_symbols.append(struct.pack("<IBBHQQ", add(symbol), info, 0, shndx, value, 0))
    for symbol, bind in imports:
        global_symbols.append(struct.pack(
            "<IBBHQQ", add(symbol), (2 if bind == "weak" else 1) << 4, 0, 0, 0, 0))
    if real_export_names:
        records_by_section = {}
        for symbol, _kind, _crc in exports:
            target_symbol = (export_name_targets or {}).get(symbol, symbol)
            entry_size = ksymtab_size
            name_delta, relocation_type = (
                (8, 257) if entry_size == 24 else (4, 261)
            )
            default_addend = (
                runtime_name_offsets[target_symbol]
                if runtime_name_symbol_style == "section" else 0
            )
            addend = (runtime_name_addends or {}).get(symbol, default_addend)
            records_by_section.setdefault(export_section_indexes[symbol], []).append(
                (export_offsets[symbol] + name_delta,
                 runtime_name_symbols[target_symbol], relocation_type, addend)
            )
            if entry_size in (12, 24) and runtime_namespace_relocations:
                namespace_delta = 16 if entry_size == 24 else 8
                namespace_addend = (
                    runtime_namespace_offsets[symbol]
                    if runtime_name_symbol_style == "section" else 0
                )
                records_by_section[export_section_indexes[symbol]].append(
                    (export_offsets[symbol] + namespace_delta,
                     runtime_namespace_symbols[symbol], relocation_type,
                     namespace_addend)
                )
        for target_index, records in records_by_section.items():
            if runtime_name_relocation_kind == "rela":
                data = b"".join(struct.pack(
                    "<QQq", offset, symbol_index << 32 | relocation_type, addend
                ) for offset, symbol_index, relocation_type, addend in records)
                section_kind, entsize = 4, 24
            elif runtime_name_relocation_kind == "rel":
                target = list(sections[target_index - 1])
                target_data = bytearray(target[3])
                for offset, _symbol_index, relocation_type, addend in records:
                    addend_format = "<q" if relocation_type == 257 else "<i"
                    struct.pack_into(addend_format, target_data, offset, addend)
                target[3] = bytes(target_data)
                sections[target_index - 1] = tuple(target)
                data = b"".join(struct.pack(
                    "<QQ", offset, symbol_index << 32 | relocation_type
                ) for offset, symbol_index, relocation_type, _addend in records)
                section_kind, entsize = 9, 16
            else:
                raise ValueError(
                    f"unknown runtime-name relocation kind: {runtime_name_relocation_kind}"
                )
            relocation_indexes.append((len(sections), sections[target_index - 1][0]))
            sections.append((f".{runtime_name_relocation_kind}.runtime-names.{target_index}",
                             section_kind, 0x40, data, 0, 0, entsize))
    symbols = local_symbols + global_symbols
    count = len(sections)
    symtab_index, strtab_index, shstr_index = count + 1, count + 2, count + 3
    names_to_indexes = {section[0]: index + 1 for index, section in enumerate(sections)}
    for index, target_name in relocation_indexes:
        section = sections[index]
        sections[index] = (*section[:4], symtab_index, names_to_indexes[target_name], section[6])
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
