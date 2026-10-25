# SPDX-License-Identifier: MIT
"""Parse one synthetic GPT byte-for-byte into the exact Myron R2 operation fragment.

Offline and synthetic only. A fixed closure of six flat files (a manifest, an explicit
geometry claim and the primary and backup GPT headers and entry tables) is parsed under
one narrow profile into the R2 operation that tools/myron-collect already consumes, and
the unchanged collector validates the result. Nothing here reads a phone or a block
device, acquires evidence, authorizes anything or clears a blocker. R3 (boot image
headers) and R4 (selection) are not implemented: each is a recorded successor gate.

This file is not run directly. tools/myron-bootchain captures its bytes once and
executes them in its own namespace (so `__file__` is the loader's), and passes
the digest of those same bytes as CAPTURED_IMPLEMENTATION_SHA256."""

from __future__ import annotations

import os
import sys
import argparse
import hashlib
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import re

sys.dont_write_bytecode = True

VERSION = "0.2.0"
REPO = Path(__file__).resolve().parent.parent
COLLECT_TOOL = REPO / "tools/myron-collect"
PINNED_VERSIONS = {
    "collector": "0.2.0", "preflight": "0.3.0", "snapshot": "0.2.0", "deployment": "0.4.0",
}
BOOTCHAIN_CONTRACT_PATH = "device/myron/bootchain-contract.json"
IMPLEMENTATION_PATH = "tools/lib/myron-bootchain-impl.py"
IMPLEMENTATION_ALGORITHM = "sha256-of-captured-implementation-bytes"
CONTRACT_KIND = "myron-synthetic-bootchain-contract"
PLAN_KIND = "myron-synthetic-gpt-parse-plan"
PARSE_KIND = "myron-synthetic-gpt-parse"
READS_KIND = "myron-synthetic-gpt-reads"
GEOMETRY_KIND = "myron-synthetic-gpt-geometry"
PROFILE = "gpt-v1-128x128-primary-backup"
TRANSPORT = "synthetic-binary-gpt-fixture"
EVIDENCE_LEVEL = "synthetic-binary-parser-only"
PARSE_STATUS = "synthetic-parse-recorded"
INVENTORY_SCOPE = "one-synthetic-gpt"
DEPENDENCY_TRUST = "trusted-version-pinned-imports"
LEGACY_BOOTABLE = "legacy-bios-bootable-bit"
R2_ID = "R2-gpt-and-recovery-inventory"
R3_ID = "R3-boot-image-headers"
R4_ID = "R4-dtb-dtbo-selection"
NOT_PRODUCED = [
    "R1-identity-and-slot", R3_ID, R4_ID, "R5-module-load-order", "R6-storage-and-mount-model",
    "R7-kernel-identity-revalidation",
]

HEX256 = re.compile(r"[0-9a-f]{64}")
RECOVERY_NAME = re.compile(r"recovery(_a|_b)?")
PARTITION_NAME = re.compile(r"[a-z0-9_]{1,36}")
JSON_DEPTH = 8
PLAN_DEPTH = 8

# --- the one supported GPT profile ---------------------------------------------------
SECTOR_SIZES = [512, 4096]
EFI_SIGNATURE = b"EFI PART"
GPT_REVISION = 0x00010000
HEADER_BYTES = 92
ENTRY_COUNT = 128
ENTRY_BYTES = 128
TABLE_BYTES = ENTRY_COUNT * ENTRY_BYTES  # 16384
MAX_PARTITIONS = 128
BYTE_LIMIT = 2**50  # disk bytes and every emitted partition size
BOOTABLE_BIT = 2
ZERO_GUID = bytes(16)

# --- the exact flat input closure -----------------------------------------------------
MANIFEST_PATH = "reads.json"
GEOMETRY_PATH = "geometry.json"
PRIMARY_HEADER = "gpt-primary-header.bin"
PRIMARY_ENTRIES = "gpt-primary-entries.bin"
BACKUP_HEADER = "gpt-backup-header.bin"
BACKUP_ENTRIES = "gpt-backup-entries.bin"
# (path, min_bytes, max_bytes, role). Header files are 512..4096 at admission and exactly
# the geometry's sector_bytes once the geometry is read.
INPUT_FILES = [
    {"path": MANIFEST_PATH, "min_bytes": 1, "max_bytes": 8192, "role": "manifest"},
    {"path": GEOMETRY_PATH, "min_bytes": 1, "max_bytes": 1024, "role": "explicit-geometry-claim"},
    {"path": PRIMARY_HEADER, "min_bytes": 512, "max_bytes": 4096, "role": "gpt-primary-header"},
    {"path": PRIMARY_ENTRIES, "min_bytes": TABLE_BYTES, "max_bytes": TABLE_BYTES,
     "role": "gpt-primary-entry-table"},
    {"path": BACKUP_HEADER, "min_bytes": 512, "max_bytes": 4096, "role": "gpt-backup-header"},
    {"path": BACKUP_ENTRIES, "min_bytes": TABLE_BYTES, "max_bytes": TABLE_BYTES,
     "role": "gpt-backup-entry-table"},
]
INPUT_ROWS = {row["path"]: row for row in INPUT_FILES}
CLOSURE = sorted(INPUT_ROWS)
PAYLOAD = [path for path in CLOSURE if path != MANIFEST_PATH]
READS_ENTRIES = len(CLOSURE) + 1  # anything past the closure is overbound
TOTAL_READS_BYTES = 50176
MAX_BYTES_READ = 1024 + 2 * 4096 + 2 * TABLE_BYTES  # geometry, both headers, both tables

PARSED, GEOMETRY_DEPENDENT = "parsed-bytes", "geometry-claim-dependent"
COVERAGE_CLASSES = [PARSED, GEOMETRY_DEPENDENT]
# (field, class, source, semantics)
COVERAGE = [
    ("partitions.partition_name", PARSED, "gpt-entry-name-utf16le", "name-as-recorded"),
    ("partitions.size_bytes", GEOMETRY_DEPENDENT,
     "gpt-entry-lba-extent-times-explicit-sector-bytes", "extent-size-under-explicit-geometry-claim"),
    ("partitions.bootable_flag", PARSED, "gpt-entry-attributes-bit-2", LEGACY_BOOTABLE),
    ("partitions.slot_suffix", PARSED, "partition-name-suffix", "name-suffix-only"),
    ("recovery_present", PARSED, "partition-name-match-in-one-gpt", "name-presence-in-this-gpt-only"),
]
SEMANTIC_LIMITS = [
    "bootable_flag is the literal GPT attributes bit 2 (legacy-bios-bootable-bit)",
    "bootable_flag does NOT prove Android slot priority",
    "bootable_flag does NOT prove Android slot success",
    "bootable_flag does NOT prove the active slot",
    "bootable_flag does NOT prove bootability",
    "bootable_flag does NOT prove recovery viability",
    "slot_suffix is the partition name's _a or _b ending and nothing else",
    "recovery_present is name presence inside this one GPT, not recovery viability",
]
UNRESOLVED = [
    "geometry-provenance-not-established",
    "physical-acquisition-and-freshness-not-established",
    "complete-device-disk-inventory-not-established",
    "protective-mbr-not-parsed",
    "android-slot-semantics-not-established",
    "bootability-not-established",
    "r3-binary-parser-successor-required",
    "r4-selection-provenance-successor-required",
]
DEFERRED = [
    {
        "id": R3_ID, "state": "not-implemented", "successor_gate": "r3-binary-image-parsers",
        "requires": [
            "format-specific binary parsers for Android boot v0-v4, vendor boot v3 and v4, and DT table v0",
            "hashes and coverage recomputed from image bytes: the schema generation only represents them",
        ],
        "later_acquisition_qualification": [
            "a hardware transport that counts actual returned bytes, rereads and overreads separately: "
            "a later acquisition gate, not a prerequisite of the offline parser phase",
        ],
    },
    {
        "id": R4_ID, "state": "not-implemented", "successor_gate": "r4-selection-source-qualification",
        "requires": [
            "a concrete selected-index source: parsing a DTBO or FDT does not prove selection",
            "an actual Myron witness and contract cross-checks",
        ],
    },
]
LIMITATIONS = [
    "synthetic binary parser qualification only: the fixture bytes were never read from a phone or a block device",
    "sector_bytes and disk_lbas are explicit synthetic claims: a GPT does not describe its own sector size or disk length",
    "one GPT only: no protective MBR, no other disk or LUN, no complete device inventory",
    "revision 1.0, 92-byte headers, exactly 128 entries of 128 bytes and sectors of 512 or 4096 only; other valid GPT variants are refused as unsupported",
    "header bytes after the 92-byte header must be zero: a profile restriction, not universal GPT validity",
    "a partition name fills at most 35 UTF-16 units and must be NUL terminated (a profile restriction)",
    "bootable_flag is legacy-bios-bootable-bit and proves no Android priority, success, active slot, bootability or recovery viability",
    "R3 binary parsing and R4 selection are not implemented: each is a recorded successor gate (the R3 schema generation exists, with no parser) and the parse is an operation fragment, not a capture",
    "bytes_read is fixture payload accounting only: it counts consumed fixture bytes and is no device I/O",
    "the collector, preflight, snapshot and deployment imports are trusted version-pinned dependencies, not fully byte-pinned execution",
    "the bootchain contract pins the bootchain implementation bytes; the collector implementation is bound only through the capture contract",
    "each gather is an internally validated descriptor-read snapshot of the exact bytes consumed, not an atomic filesystem snapshot: the caller-owned source can diverge after any file's final observation, a writable shared mapping can change bytes without changing metadata, and a later verify against a changed source rejects",
    "a concurrent mutation first observable after payload traversal can consume bounded bytes (at most 50176) before rejection; zero payload bytes is promised only for a defect detected before traversal",
    "publication is durable only if the output parent's fsync succeeds; a failure there removes the just-published output by identity on a best-effort basis and, if that cleanup also fails, can leave an output while reporting failure",
]
NON_GOALS = [
    "real acquisition from a device",
    "live transport of any kind, or a raw device or storage handle",
    "hardware evidence or captured provenance",
    "authorization of any read, deployment or boot",
    "closing any blocker",
    "R3 boot image header parsing, R4 DTB or DTBO selection, or any complete R1-R7 capture",
    "Android slot, priority, success or recovery qualification",
]
SAFETY = [
    "flat-tree-only", "exact-closure-before-payload-read", "no-symlinks", "no-hardlinks",
    "no-executable-files", "no-special-files", "no-mount-crossing", "no-writable-ancestry",
    "no-aliases-of-inputs", "stable-while-read", "metadata-admitted-before-payload-read",
    "names-revalidated-after-read",
]
OUTPUT_OPERATION_PATH = f"operations/{R2_ID}.json"
OUTPUT_FILES = sorted(["SHA256SUMS", "parse.json", OUTPUT_OPERATION_PATH])


class BootchainError(Exception):
    """Synthetic input or parse differs from the reviewed bootchain contract."""


class CorruptGpt(BootchainError):
    """The GPT bytes are internally inconsistent."""

    def __str__(self) -> str:
        return f"{self.args[0]} (code gpt-corrupt)"


class UnsupportedGpt(BootchainError):
    """The GPT bytes may be valid but lie outside the one supported profile."""

    def __str__(self) -> str:
        return f"{self.args[0]} (code gpt-unsupported)"


_collect = None

# Loader exceptions carry the checkout path and the underlying errno text: never print them.
DEPENDENCY_REJECTED = "bootchain dependencies could not be loaded (code dependency-rejected)"
VERSION_MISMATCH = "bootchain dependencies are not the pinned versions (code dependency-version)"


def collect():
    global _collect
    if _collect is None:
        try:
            loader = importlib.machinery.SourceFileLoader("myron_collect", str(COLLECT_TOOL))
            spec = importlib.util.spec_from_loader(loader.name, loader)
            module = importlib.util.module_from_spec(spec)
            loader.exec_module(module)
            p = module.preflight()
            found = {
                "collector": module.VERSION,
                "preflight": p.VERSION,
                "snapshot": p.snapshot().VERSION,
                "deployment": p.deploy().VERSION,
            }
        except (Exception, SystemExit):
            # The loader boundary: any failure to load or pin is a refusal, including a
            # dependency that exits at import time. Only dependency code runs in this try, so
            # the tool's own final SystemExit is never caught here. KeyboardInterrupt passes.
            raise BootchainError(DEPENDENCY_REJECTED) from None
        if found != PINNED_VERSIONS:
            # Neither the observed nor the expected versions are printed: the observed values
            # come from dependency code and are not trusted text.
            raise BootchainError(VERSION_MISMATCH)
        _collect = module
    return _collect


def deploy():
    return collect().deploy()


def authority() -> dict:
    return collect().authority()


def blocker_rows() -> list[dict]:
    return collect().blocker_rows()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# --- implementation pin ---------------------------------------------------------
# The digest comes from the loader, which hashed and compiled one read of this file;
# nothing here reopens the path, and the source never holds its own digest.


def implementation_binding() -> dict:
    if Path(__file__).resolve() != (REPO / "tools/myron-bootchain").resolve():
        raise BootchainError("bootchain tool is not running from its pinned path")
    digest = globals().get("CAPTURED_IMPLEMENTATION_SHA256")
    if type(digest) is not str or not HEX256.fullmatch(digest):
        raise BootchainError("bootchain tool was not loaded through its trusted loader")
    return {
        "algorithm": IMPLEMENTATION_ALGORITHM,
        "path": IMPLEMENTATION_PATH,
        "sha256": digest,
    }


# --- CRC-32 (IEEE 802.3, reflected, init and final xor 0xFFFFFFFF) -----------------------


def _crc_table() -> list[int]:
    table = []
    for index in range(256):
        value = index
        for _ in range(8):
            value = (value >> 1) ^ (0xEDB88320 if value & 1 else 0)
        table.append(value)
    return table


CRC_TABLE = _crc_table()


def crc32(data: bytes) -> int:
    value = 0xFFFFFFFF
    for byte in data:
        value = (value >> 8) ^ CRC_TABLE[(value ^ byte) & 0xFF]
    return value ^ 0xFFFFFFFF


# --- fixed raw-tree schemas -----------------------------------------------------


def raw_schemas() -> dict:
    """The typed shape of the two JSON inputs, built from the collector's own spec forms."""
    c = collect()
    schema = c._int(1, 1)
    return {
        MANIFEST_PATH: {
            "fields": {
                "schema": schema, "kind": c._enum([READS_KIND]), "format_version": c._int(1, 1),
                "bootchain_contract_sha256": c._hash(), "request_sha256": c._hash(),
                "synthetic": c._bool(True),
            },
            "rows_field": "files",
            "rows": c._rows({
                "path": c._enum(sorted(PAYLOAD)),
                "bytes": c._int(1, TABLE_BYTES),
                "sha256": c._hash(),
            }, len(PAYLOAD), len(PAYLOAD), "path"),
        },
        GEOMETRY_PATH: {
            "fields": {
                "schema": schema, "kind": c._enum([GEOMETRY_KIND]),
                "sector_bytes": c._int_enum(SECTOR_SIZES),
                "disk_lbas": c._int(1, BYTE_LIMIT // min(SECTOR_SIZES)),
            },
            "rule": "disk_lbas * sector_bytes <= 2^50 and disk_lbas >= 2 * (16384 / sector_bytes) + 4",
        },
    }


def check_registry_consistency(c) -> None:
    """This registry names exactly the collector's R2 fields, patterns and bounds."""
    if PARTITION_NAME.pattern != c.PARTITION_NAME.pattern:
        raise BootchainError("bootchain partition pattern differs from the collector's")
    registry = c.policy_registry()["operations"]
    if not {R2_ID, R3_ID, R4_ID} <= set(registry):
        raise BootchainError("bootchain registry operations differ from the collector's")
    r2 = registry[R2_ID]
    if r2["recovery_pattern"] != RECOVERY_NAME.pattern:
        raise BootchainError("bootchain recovery pattern differs from the collector's")
    rows = r2["fields"]["partitions"]
    if rows["max"] != MAX_PARTITIONS or rows["min"] != 1 or rows["sorted_unique_by"] != "partition_name":
        raise BootchainError("bootchain partition bounds differ from the collector's")
    if rows["row"]["size_bytes"] != c._int(0, BYTE_LIMIT):
        raise BootchainError("bootchain size bound differs from the collector's")
    container = r2["container"]
    expected = {
        f"{container['rows_field']}.{name}" for name in container["row_fields"]
    } | {name for name in r2["fields"] if name != container["rows_field"]}
    declared = [field for field, _klass, _source, _semantics in COVERAGE]
    if sorted(declared) != sorted(expected) or len(set(declared)) != len(declared):
        raise BootchainError("bootchain coverage registry differs from the collector's fields")
    if any(klass not in COVERAGE_CLASSES for _field, klass, _source, _semantics in COVERAGE):
        raise BootchainError("bootchain coverage registry is inconsistent")
    if CLOSURE[0] != GEOMETRY_PATH or len(CLOSURE) != 6 or len(set(CLOSURE)) != len(CLOSURE):
        raise BootchainError("bootchain input closure is inconsistent")
    for row in INPUT_FILES:
        if not 1 <= row["min_bytes"] <= row["max_bytes"]:
            raise BootchainError("bootchain input bounds are inconsistent")
    if sum(row["max_bytes"] for row in INPUT_FILES) != TOTAL_READS_BYTES:
        raise BootchainError("bootchain input bounds exceed the total byte bound")
    if any(TABLE_BYTES % sector for sector in SECTOR_SIZES) or ENTRY_COUNT * ENTRY_BYTES != TABLE_BYTES:
        raise BootchainError("bootchain table geometry is inconsistent")
    limits = {row["id"]: row for row in c.preflight().requested_reads()}
    if R2_ID not in limits or limits[R2_ID]["max_fixture_input_bytes"] < MAX_BYTES_READ:
        raise BootchainError("bootchain byte accounting exceeds the operation's fixture input bound")


def coverage_rows() -> list[dict]:
    return [
        {"operation": R2_ID, "field": field, "classification": klass, "source": source,
         "semantics": semantics}
        for field, klass, source, semantics in COVERAGE
    ]


def unresolved_claims() -> list[dict]:
    return [{"claim": claim, "state": "unresolved"} for claim in UNRESOLVED]


def deferred_rows() -> list[dict]:
    return [
        {**row, **{key: list(row[key]) for key in ("requires", "later_acquisition_qualification")
                   if key in row}}
        for row in DEFERRED
    ]


def output_closure() -> dict:
    return {
        "directories": ["operations"],
        "files": list(OUTPUT_FILES),
        "extra_entries": "reject",
        "modes": {"directories": "0755", "files": "0644"},
        "checksums": {
            "path": "SHA256SUMS",
            "covers": ["parse.json", OUTPUT_OPERATION_PATH],
            "sorted": "canonical-byte-order-of-path",
            "parse_json_binds_checksums": False,
            "sufficient_for_verification": False,
        },
    }


def accounting_policy() -> dict:
    return {
        "bytes_read": "exact-consumed-fixture-payload-bytes",
        "meaning": "fixture-payload-accounting-not-device-io",
        "read_domain": "fixture",
        "includes": [GEOMETRY_PATH, PRIMARY_HEADER, PRIMARY_ENTRIES, BACKUP_HEADER, BACKUP_ENTRIES],
        "excludes": [MANIFEST_PATH, "manifest-validation-rereads", "verification-reruns",
                     "hardware-bytes"],
        "hardware_transport": "none",
        "future_hardware_accounting": [
            "actual-returned-bytes", "rereads-counted-separately", "overreads-counted-separately",
        ],
        "max": MAX_BYTES_READ,
    }


def header_layout() -> list[dict]:
    rows = [
        ("signature", 0, 8, "ascii EFI PART"), ("revision", 8, 4, "u32le 0x00010000"),
        ("header_size", 12, 4, "u32le 92"), ("header_crc32", 16, 4, "u32le over header_size bytes with this field zeroed"),
        ("reserved", 20, 4, "u32le 0"), ("my_lba", 24, 8, "u64le"), ("alternate_lba", 32, 8, "u64le"),
        ("first_usable_lba", 40, 8, "u64le"), ("last_usable_lba", 48, 8, "u64le"),
        ("disk_guid", 56, 16, "16 bytes, nonzero, never emitted"), ("entries_lba", 72, 8, "u64le"),
        ("entry_count", 80, 4, "u32le 128"), ("entry_size", 84, 4, "u32le 128"),
        ("entries_crc32", 88, 4, "u32le over the 16384-byte table"),
    ]
    return [{"field": f, "offset": o, "bytes": b, "encoding": e} for f, o, b, e in rows]


def entry_layout() -> list[dict]:
    rows = [
        ("type_guid", 0, 16, "all zero means unused; never emitted"),
        ("unique_guid", 16, 16, "nonzero and unique among occupied entries; never emitted"),
        ("first_lba", 32, 8, "u64le"), ("last_lba", 40, 8, "u64le"),
        ("attributes", 48, 8, "u64le; only bit 2 is read"),
        ("name", 56, 72, "UTF-16LE, strict, NUL terminated, zero padded"),
    ]
    return [{"field": f, "offset": o, "bytes": b, "encoding": e} for f, o, b, e in rows]


def profile_contract() -> dict:
    return {
        "name": PROFILE,
        "inventory_scope": INVENTORY_SCOPE,
        "operation": R2_ID,
        "gpt": {
            "revision": "1.0",
            "header_size": HEADER_BYTES,
            "entry_count": ENTRY_COUNT,
            "entry_size": ENTRY_BYTES,
            "entry_table_bytes": TABLE_BYTES,
            "sector_bytes": list(SECTOR_SIZES),
            "crc": "crc32-ieee-reflected-poly-0xedb88320",
            "primary_header_lba": 1,
            "primary_entries_lba": 2,
            "backup_header_lba": "disk_lbas - 1",
            "backup_entries_lba": "disk_lbas - 1 - 16384 / sector_bytes",
            "usable_range": "first_usable >= 2 + 16384 / sector_bytes, last_usable <= disk_lbas - 2 - 16384 / sector_bytes, first_usable <= last_usable",
            "header_trailing_bytes": "zero-required-profile-restriction",
            "disk_guid": "nonzero-never-emitted",
            "table_rule": "copies byte-identical, then crc32 equals the header field; no fallback, repair or preference",
            "unsupported_is_not_corrupt": [
                "revision other than 1.0", "header_size other than 92", "entry_count other than 128",
                "entry_size other than 128", "nonzero bytes after the header", "name outside the pattern",
                "no occupied entry",
            ],
            "entries": {
                "unused": "type guid all zero: every other field ignored",
                "occupied": "nonzero type guid, nonzero unique guid unique among occupied entries",
                "extent": "first_lba <= last_lba, inside the usable range, no overlap after sorting by first_lba",
                "name": "UTF-16LE strict, 1..35 units, NUL terminated, zero padded, [a-z0-9_]{1,36}, unique",
                "order": "arbitrary entry order; rows emitted sorted by partition_name",
                "guids_emitted": False,
            },
            "mappings": {
                "size_bytes": "(last_lba - first_lba + 1) * sector_bytes, 1..2^50",
                "slot_suffix": "_a or _b ending of the name, else empty",
                "recovery_present": "any name matches recovery, recovery_a or recovery_b in this one GPT",
                "bootable_flag": f"attributes bit {BOOTABLE_BIT}, semantics {LEGACY_BOOTABLE}",
            },
            "header_layout": header_layout(),
            "entry_layout": entry_layout(),
        },
    }


# --- contract -------------------------------------------------------------------


def input_contract() -> dict:
    return {
        "kind": READS_KIND,
        "format_version": 1,
        "layout": "flat",
        "closure": list(CLOSURE),
        "closure_checked_before_payload_read": True,
        "extra_entries": "reject",
        "entries_max": READS_ENTRIES,
        "total_max_bytes": TOTAL_READS_BYTES,
        "json_depth_max": JSON_DEPTH,
        "json": "strict canonical ASCII; duplicate keys, floats, booleans for integers rejected",
        "safety": list(SAFETY),
        "header_size_rule": "512..4096 at metadata admission, then exactly sector_bytes after geometry.json is read",
        "manifest": {
            "path": MANIFEST_PATH,
            "max_bytes": 8192,
            "rows_sorted_by": "path",
            "binds": ["bootchain_contract_sha256", "request_sha256"],
        },
        "files": [dict(row) for row in INPUT_FILES],
        "schemas": raw_schemas(),
        "configurable": "nothing: filenames, paths, offsets, counts, algorithms and bounds are fixed here",
    }


def expected_bootchain_contract(env) -> dict:
    """The one bootchain contract this collector, preflight and kernel reference admit."""
    c = collect()
    check_registry_consistency(c)
    p = c.preflight()
    d = p.deploy()
    preflight_value = d.strict_json(env.preflight_bytes, "preflight contract")
    components = preflight_value["components"]
    return {
        "schema": 1,
        "kind": CONTRACT_KIND,
        "format_version": VERSION,
        "components": {
            "capture_contract": {
                "path": c.CAPTURE_CONTRACT_PATH, "sha256": env.contract_sha256,
            },
            "preflight_contract": {
                "path": c.PREFLIGHT_CONTRACT_PATH, "sha256": env.preflight_sha256,
            },
        },
        "bound_contracts": {
            "deployment_contract": dict(components["deployment_contract"]),
            "kernel_reference": {
                "path": d.KERNEL_REFERENCE_PATH, "sha256": env.contracts.reference_sha256,
            },
            "snapshot_contract": dict(components["snapshot_contract"]),
        },
        "pinned_versions": dict(PINNED_VERSIONS),
        "dependencies": {
            "trust": DEPENDENCY_TRUST,
            "byte_pinned": False,
            "imports": [
                "tools/myron-collect", "tools/myron-preflight", "tools/myron-snapshot",
                "tools/myron-deployment",
            ],
            "note": (
                "imported in-process and pinned by version and by the capture and preflight "
                "contract identities above; their bytes are not pinned here, and the collector "
                "implementation digest is bound only through the capture contract"
            ),
        },
        "implementation": implementation_binding(),
        "transport": TRANSPORT,
        "synthetic": True,
        "live": False,
        "executes": False,
        "kit_snapshot_reverified": False,
        "remote_commands": [],
        "evidence_level": EVIDENCE_LEVEL,
        "status": PARSE_STATUS,
        "human_approval_required": True,
        "capture": {
            "kind": c.CAPTURE_KIND,
            "operation_kind": c.OPERATION_KIND,
            "transport": c.TRANSPORT,
            "collector_transport_label_is_not_provenance": True,
            "unchanged_for_collector": True,
            "validated_by": ["validate_operation"],
            "complete_capture": False,
            "produces": [R2_ID],
            "does_not_produce": list(NOT_PRODUCED),
        },
        "profile": profile_contract(),
        "input": input_contract(),
        "output": {
            "kind": PARSE_KIND,
            "closure": output_closure(),
            "accounting": accounting_policy(),
            "deterministic": True,
            "published": "atomic-no-replace",
            "verification": "recompute-from-request-and-reads-byte-for-byte",
        },
        "coverage": {
            "classes": list(COVERAGE_CLASSES),
            "fields": coverage_rows(),
            "semantic_limits": list(SEMANTIC_LIMITS),
            "unresolved_claims": unresolved_claims(),
        },
        "deferred": deferred_rows(),
        "qualification": qualification(),
        "identity": c.identity_values(env.contracts),
        "limitations": list(LIMITATIONS),
        "non_goals": list(NON_GOALS),
        "blockers": list(d.BLOCKERS),
        "authority": p.authority(),
    }


def qualification() -> dict:
    return {
        "binary_parser": "synthetic-fixtures-only",
        "captured_provenance": False,
        "implemented_operations": [R2_ID],
        "deferred_operations": [
            {"id": row["id"], "state": row["state"], "successor_gate": row["successor_gate"]}
            for row in DEFERRED
        ],
    }


def load_bootchain_contract(root: Path, env) -> tuple[dict, bytes, str]:
    d = deploy()
    try:
        data = d.read_file(f"{root}/{BOOTCHAIN_CONTRACT_PATH}", "bootchain contract", d.MAX_SMALL_BYTES)
        value = d.strict_json(data, "bootchain contract")
    except (*admission_errors(), RecursionError):
        # Dependency text can echo the contract's own keys or values: say only what failed.
        raise BootchainError("bootchain contract could not be admitted (code contract-rejected)") from None
    expected = expected_bootchain_contract(env)
    if not collect().kernel().strict_equal(value, expected):
        raise BootchainError("bootchain contract differs from its derived form")
    if data != d.render_json(expected):
        raise BootchainError("bootchain contract is not canonical")
    return value, data, d.sha256_bytes(data)


class Environment:
    def __init__(self, collector_env, contract, contract_bytes, contract_sha256):
        self.collector = collector_env
        self.contracts = collector_env.contracts
        self.identity = collector_env.identity
        self.contract = contract
        self.contract_bytes = contract_bytes
        self.contract_sha256 = contract_sha256


def admission_errors() -> tuple:
    """Every class the pinned dependencies raise while admitting contracts (ValueError: numbers, UTF-8)."""
    c = collect()
    p = c.preflight()
    return (c.CollectError, p.PreflightError, p.snapshot().SnapshotError, *p.deploy().handled_errors())


def load_collector_environment(root: Path):
    c = collect()
    try:
        return c.load_environment(root)
    except (*admission_errors(), RecursionError):
        raise BootchainError("bootchain environment could not be admitted (code environment-rejected)") from None


def load_environment(root: Path) -> Environment:
    collector_env = load_collector_environment(root)
    contract, contract_bytes, contract_sha256 = load_bootchain_contract(root, collector_env)
    return Environment(collector_env, contract, contract_bytes, contract_sha256)


# --- strict parsing -------------------------------------------------------------


def parse_json(raw: bytes, label: str) -> dict:
    """Strict canonical JSON; every message is free of input values."""
    c = collect()
    d = c.deploy()

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise BootchainError(f"{label} repeats a JSON key")
            result[key] = value
        return result

    def constant(_name):
        raise BootchainError(f"{label} holds a non-finite number")

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, RecursionError) as error:  # includes UnicodeDecodeError, JSONDecodeError
        raise BootchainError(f"{label} is invalid JSON") from error
    if type(value) is not dict:
        raise BootchainError(f"{label} is not a JSON object")
    c.check_json_depth(value, label, JSON_DEPTH)
    if raw != d.render_json(value):
        raise BootchainError(f"{label} is not canonical JSON")
    return value


def check_fields(document: dict, fields: dict, label: str) -> dict:
    c = collect()
    c.need_dict(document, list(fields), label)
    return {
        name: c.check_spec(spec, document[name], f"{label} {name}", {})
        for name, spec in fields.items()
    }


def table_sectors(sector: int) -> int:
    return TABLE_BYTES // sector


def parse_geometry(raw: bytes) -> dict:
    schema = raw_schemas()[GEOMETRY_PATH]
    document = parse_json(raw, "geometry.json")
    values = check_fields(document, schema["fields"], "geometry.json")
    sector, disk = values["sector_bytes"], values["disk_lbas"]
    if disk * sector > BYTE_LIMIT:
        raise BootchainError("geometry.json disk size is outside the supported range")
    if disk < 2 * table_sectors(sector) + 4:
        raise BootchainError("geometry.json disk is too small for the GPT metadata")
    return {"sector_bytes": sector, "disk_lbas": disk}


# --- reads tree -----------------------------------------------------------------


class Reads:
    def __init__(self, manifest_bytes, files, geometry, directory_ids):
        self.manifest_bytes = manifest_bytes
        self.files = files  # path -> bytes, payload only
        self.geometry = geometry
        self.directory_ids = directory_ids
        self.sha256 = sha256_hex(manifest_bytes)


class Held:
    """One closure file pinned by descriptor: its name is a closure constant, never input."""

    def __init__(self, name, pinned, descriptor, opened):
        self.name = name
        self.pinned = pinned
        self.descriptor = descriptor
        self.opened = opened


def list_names(descriptor: int) -> list[str]:
    names = []
    try:
        with os.scandir(descriptor) as children:
            for child in children:
                names.append(child.name)
                if len(names) > READS_ENTRIES:
                    raise BootchainError("synthetic GPT reads exceed the entry bound")
    except OSError:
        raise BootchainError("synthetic GPT reads cannot be listed") from None
    return names


def check_closure(names: list[str], when: str = "") -> None:
    """Diagnostics carry counts only: an unexpected name is never echoed."""
    if sorted(names) != CLOSURE:
        extra = len(set(names) - set(CLOSURE))
        missing = len(set(CLOSURE) - set(names))
        raise BootchainError(
            f"synthetic GPT reads {when}differ from the exact closure ({extra} extra, {missing} missing)"
        )


def release(held: list) -> None:
    for item in held:
        for descriptor in (item.descriptor, item.pinned):
            try:
                os.close(descriptor)
            except OSError:
                pass


def pin_reads(directory: int, root, root_mount: int) -> list:
    """Pin every closure file and judge all of its metadata; no payload byte is read here."""
    d = deploy()
    held, total = [], 0
    try:
        for name in CLOSURE:
            pinned, descriptor, opened = d.open_pinned_regular_at(
                directory, name, f"synthetic GPT reads file {name}"
            )
            held.append(Held(name, pinned, descriptor, opened))
            if opened.st_nlink != 1:
                raise BootchainError(f"synthetic GPT reads file {name} has additional hard links")
            if d.untrusted_owner_or_mode(opened):
                raise BootchainError(f"synthetic GPT reads file {name} is writable or controlled by another user")
            if opened.st_mode & 0o111:
                raise BootchainError(f"synthetic GPT reads file is executable: {name}")
            if opened.st_dev != root.st_dev:
                raise BootchainError(f"synthetic GPT reads file {name} crosses a device boundary")
            if d.kernel().mount_id_for_fd(pinned, f"synthetic GPT reads file {name}") != root_mount:
                raise BootchainError(f"synthetic GPT reads file {name} crosses a mount point")
            row = INPUT_ROWS[name]
            if not row["min_bytes"] <= opened.st_size <= row["max_bytes"]:
                raise BootchainError(
                    f"synthetic GPT reads file {name} is outside its {row['min_bytes']}..{row['max_bytes']} byte bounds"
                )
            total += opened.st_size
            if total > TOTAL_READS_BYTES:
                raise BootchainError("synthetic GPT reads exceed the total byte bound")
    except BaseException:
        release(held)
        raise
    return held


def settle_reads(directory: int, held: list, root_before: tuple, when: str) -> None:
    """The listing, the directory and every pinned file still match what admission recorded.

    The interval is sampled repeatedly: the directory and listing are checked, then every file
    (descriptor and name), then the directory again, then every file a second time, then the
    directory a last time. A difference observed by a later pass is refused. This is
    best-effort detection, not a guarantee: a change after a file's final observation is out of
    reach (any finite sequence of observations has a final one), and a
    write through a pre-existing writable shared mapping alters bytes without moving mtime,
    ctime or size. The semantics are therefore only these: every gather yields an internally
    validated snapshot of the exact bytes actually read from the pinned descriptors, and
    reads.json hashes bind every one of those bytes. The caller-owned source path is not
    claimed to equal that snapshot at return, nor to be atomic or writer-excluded; a later
    verify against a changed source rejects. Content is not rehashed here."""
    d = deploy()

    def directory_unchanged() -> None:
        check_closure(list_names(directory), f"changed {when} and ")
        if d.fingerprint(os.fstat(directory)) != root_before:
            raise BootchainError(f"synthetic GPT reads directory changed {when}")

    def files_unchanged() -> None:
        for item in held:
            pinned = d.fingerprint(item.opened)
            if d.fingerprint(os.fstat(item.descriptor)) != pinned:
                raise BootchainError(f"synthetic GPT reads file {item.name} changed {when}")
            try:
                current = os.stat(item.name, dir_fd=directory, follow_symlinks=False)
            except OSError:
                raise BootchainError(f"synthetic GPT reads file {item.name} was removed {when}") from None
            if d.fingerprint(current) != pinned:
                raise BootchainError(f"synthetic GPT reads file {item.name} was replaced {when}")

    directory_unchanged()
    files_unchanged()
    directory_unchanged()  # a directory change during the first file pass is caught here
    files_unchanged()  # a file change during the first pass or the listing is caught here
    directory_unchanged()  # a directory change during the second file pass


def read_pinned(item: Held) -> bytes:
    """Exactly the stat size from the captured descriptor, then a metadata stability check.

    A write through a shared mapping can change bytes after os.read returns without changing
    the fingerprint, so the bytes returned are the validated snapshot, not proof of the source."""
    d = deploy()
    pinned = d.fingerprint(item.opened)
    if d.fingerprint(os.fstat(item.descriptor)) != pinned:
        raise BootchainError(f"synthetic GPT reads file {item.name} changed before being read")
    chunks, remaining = [], item.opened.st_size
    while remaining:
        block = os.read(item.descriptor, min(1024 * 1024, remaining))
        if not block:
            raise BootchainError(f"synthetic GPT reads file {item.name} changed size while being read")
        chunks.append(block)
        remaining -= len(block)
    if os.read(item.descriptor, 1):
        raise BootchainError(f"synthetic GPT reads file {item.name} grew while being read")
    if d.fingerprint(os.fstat(item.descriptor)) != pinned:
        raise BootchainError(f"synthetic GPT reads file {item.name} changed while being read")
    return b"".join(chunks)


def read_payload(held: list) -> tuple[dict, dict]:
    """Read in closure order. geometry.json sorts first, so the header sizes are judged against
    the explicit sector size before any header or table byte is read."""
    data, geometry = {}, None
    for item in held:
        data[item.name] = read_pinned(item)
        if item.name == GEOMETRY_PATH:
            geometry = parse_geometry(data[item.name])
            for other in held:
                if other.name in (PRIMARY_HEADER, BACKUP_HEADER) and other.opened.st_size != geometry["sector_bytes"]:
                    raise BootchainError(
                        f"synthetic GPT reads file {other.name} is not exactly one geometry sector"
                    )
    return data, geometry


def check_manifest(raw: bytes, files: dict, env: Environment, request_sha256: str) -> None:
    c = collect()
    schema = raw_schemas()[MANIFEST_PATH]
    document = parse_json(raw, "reads.json")
    if set(document) != {*schema["fields"], "files"}:
        raise BootchainError("reads.json fields differ")
    header = check_fields(
        {key: document[key] for key in schema["fields"]}, schema["fields"], "reads.json"
    )
    if header["bootchain_contract_sha256"] != env.contract_sha256:
        raise BootchainError("reads.json bootchain contract binding differs")
    if header["request_sha256"] != request_sha256:
        raise BootchainError("reads.json request binding differs")
    rows = c.check_rows(schema["rows"], document["files"], "reads.json files", "reads.json file", {})
    if [row["path"] for row in rows] != sorted(files):
        raise BootchainError("reads.json files differ from the closure or are not sorted")
    for row in rows:
        data = files[row["path"]]
        if row["bytes"] != len(data) or row["sha256"] != sha256_hex(data):
            raise BootchainError(f"reads.json row for {row['path']} differs from the file")


def read_reads(path: str, env: Environment, request_sha256: str) -> Reads:
    """Admit the flat tree in order: exact closure, then every descriptor's metadata, then a
    re-listing, and only then the payload bytes, from the pinned descriptors, with the names
    revalidated afterwards. A missing, extra or unsafe file visible before traversal stops the read
    at zero payload bytes. A mutation first observable during or after traversal may consume
    bounded bytes and is then rejected, or, if it lands after a file's final observation, yields
    the already-hashed snapshot of the bytes actually read (see settle_reads): the source is not
    claimed current at return, and a later verification against a changed source rejects."""
    d = deploy()
    descriptor, identity = d.open_trusted_artifact(path, "synthetic GPT reads")
    held = []
    try:
        root = os.fstat(descriptor)
        if d.untrusted_owner_or_mode(root):
            raise BootchainError("synthetic GPT reads directory is writable or controlled by another user")
        root_mount = d.kernel().mount_id_for_fd(descriptor, "synthetic GPT reads root")
        root_before = d.fingerprint(root)
        check_closure(list_names(descriptor))
        held = pin_reads(descriptor, root, root_mount)
        settle_reads(descriptor, held, root_before, "during admission")
        data, geometry = read_payload(held)
        settle_reads(descriptor, held, root_before, "while being read")
    finally:
        release(held)
        os.close(descriptor)
    manifest_bytes = data[MANIFEST_PATH]
    files = {name: data[name] for name in CLOSURE if name != MANIFEST_PATH}
    check_manifest(manifest_bytes, files, env, request_sha256)
    d.recheck_trusted_artifact(path, identity, "synthetic GPT reads")
    return Reads(manifest_bytes, files, geometry, frozenset({(root.st_dev, root.st_ino)}))


# --- GPT ------------------------------------------------------------------------


def u32(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset:offset + 4], "little")


def u64(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset:offset + 8], "little")


def parse_header(raw: bytes, sector: int, which: str) -> dict:
    label = f"GPT {which} header"
    if len(raw) != sector:
        raise CorruptGpt(f"{label} is not exactly one sector")
    if raw[:8] != EFI_SIGNATURE:
        raise CorruptGpt(f"{label} signature differs")
    size = u32(raw, 12)
    if not HEADER_BYTES <= size <= sector:
        raise CorruptGpt(f"{label} size is outside the GPT range")
    if crc32(raw[:16] + bytes(4) + raw[20:size]) != u32(raw, 16):
        raise CorruptGpt(f"{label} checksum differs")
    if u32(raw, 8) != GPT_REVISION:
        raise UnsupportedGpt(f"{label} revision is unsupported")
    if size != HEADER_BYTES:
        raise UnsupportedGpt(f"{label} size is unsupported")
    if u32(raw, 20) != 0:
        raise CorruptGpt(f"{label} reserved field is not zero")
    if any(raw[HEADER_BYTES:]):
        raise UnsupportedGpt(f"{label} holds nonzero bytes after the header (profile restriction)")
    if (u32(raw, 80), u32(raw, 84)) != (ENTRY_COUNT, ENTRY_BYTES):
        raise UnsupportedGpt(f"{label} entry geometry is unsupported")
    guid = raw[56:72]
    if guid == ZERO_GUID:
        raise CorruptGpt(f"{label} disk identifier is zero")
    return {
        "my_lba": u64(raw, 24), "alternate_lba": u64(raw, 32), "first_usable": u64(raw, 40),
        "last_usable": u64(raw, 48), "disk_guid": guid, "entries_lba": u64(raw, 72),
        "table_crc": u32(raw, 88),
    }


def check_locations(header: dict, which: str, disk: int, sector: int) -> None:
    label = f"GPT {which} header"
    sectors = table_sectors(sector)
    if which == "primary":
        mine, alternate, entries = 1, disk - 1, 2
    else:
        mine, alternate, entries = disk - 1, 1, disk - 1 - sectors
    if header["my_lba"] != mine:
        raise CorruptGpt(f"{label} own location differs from the geometry")
    if header["alternate_lba"] != alternate:
        raise CorruptGpt(f"{label} alternate location differs from the geometry")
    if header["entries_lba"] != entries:
        raise CorruptGpt(f"{label} entry table location differs from the profile")
    if header["first_usable"] > header["last_usable"]:
        raise CorruptGpt(f"{label} usable range is reversed")
    if header["first_usable"] < 2 + sectors or header["last_usable"] > disk - 2 - sectors:
        raise CorruptGpt(f"{label} usable range overlaps the GPT metadata")


def decode_name(raw: bytes) -> str:
    end = next((at for at in range(0, len(raw), 2) if raw[at:at + 2] == b"\0\0"), None)
    if end is None:
        # A field filling all 36 units has no room for the terminator this profile requires; GPT
        # itself does not forbid that, so this is a profile restriction and not corruption.
        raise UnsupportedGpt("GPT entry name has no NUL terminator within its 36 units")
    if any(raw[end:]):
        raise CorruptGpt("GPT entry name padding is not zero")
    try:
        text = raw[:end].decode("utf-16-le", errors="strict")
    except UnicodeDecodeError:
        raise CorruptGpt("GPT entry name is not valid UTF-16") from None
    if not text:
        raise CorruptGpt("GPT entry name is empty")
    if not text.isascii() or not PARTITION_NAME.fullmatch(text):
        raise UnsupportedGpt("GPT entry name is outside the supported pattern")
    return text


def parse_entries(table: bytes, header: dict, sector: int) -> list[dict]:
    seen_guids, seen_names, extents, rows = set(), set(), [], []
    for index in range(ENTRY_COUNT):
        entry = table[index * ENTRY_BYTES:(index + 1) * ENTRY_BYTES]
        if entry[:16] == ZERO_GUID:
            continue  # unused: every other field is ignored
        unique = entry[16:32]
        if unique == ZERO_GUID:
            raise CorruptGpt("GPT entry unique identifier is zero")
        if unique in seen_guids:
            raise CorruptGpt("GPT entries repeat a unique identifier")
        seen_guids.add(unique)
        first, last, attributes = u64(entry, 32), u64(entry, 40), u64(entry, 48)
        if first > last:
            raise CorruptGpt("GPT entry extent is reversed")
        if first < header["first_usable"] or last > header["last_usable"]:
            raise CorruptGpt("GPT entry extent lies outside the usable range")
        name = decode_name(entry[56:128])
        if name in seen_names:
            raise CorruptGpt("GPT entries repeat a name")
        seen_names.add(name)
        size = (last - first + 1) * sector
        if not 1 <= size <= BYTE_LIMIT:
            raise CorruptGpt("GPT entry size is outside the supported range")
        extents.append((first, last))
        rows.append({
            "partition_name": name,
            "size_bytes": size,
            "bootable_flag": bool((attributes >> BOOTABLE_BIT) & 1),
            "slot_suffix": name[-2:] if name.endswith(("_a", "_b")) else "",
        })
    if not rows:
        raise UnsupportedGpt("GPT holds no occupied entry")
    extents.sort()
    for (_first, previous_last), (next_first, _last) in zip(extents, extents[1:]):
        if next_first <= previous_last:
            raise CorruptGpt("GPT entry extents overlap")
    rows.sort(key=lambda row: row["partition_name"])
    return rows


def parse_gpt(files: dict, geometry: dict) -> list[dict]:
    sector, disk = geometry["sector_bytes"], geometry["disk_lbas"]
    primary = parse_header(files[PRIMARY_HEADER], sector, "primary")
    backup = parse_header(files[BACKUP_HEADER], sector, "backup")
    check_locations(primary, "primary", disk, sector)
    check_locations(backup, "backup", disk, sector)
    if primary["disk_guid"] != backup["disk_guid"]:
        raise CorruptGpt("GPT headers disagree on the disk identifier")
    if (primary["first_usable"], primary["last_usable"]) != (backup["first_usable"], backup["last_usable"]):
        raise CorruptGpt("GPT headers disagree on the usable range")
    if primary["table_crc"] != backup["table_crc"]:
        raise CorruptGpt("GPT headers disagree on the entry table checksum")
    table = files[PRIMARY_ENTRIES]
    if len(table) != TABLE_BYTES or len(files[BACKUP_ENTRIES]) != TABLE_BYTES:
        raise CorruptGpt("GPT entry table is not exactly 16384 bytes")
    if table != files[BACKUP_ENTRIES]:
        raise CorruptGpt("GPT entry table copies differ")
    if crc32(table) != primary["table_crc"]:
        raise CorruptGpt("GPT entry table checksum differs from the headers")
    return parse_entries(table, primary, sector)


# --- request and gather ---------------------------------------------------------


class Inputs:
    def __init__(self, request, request_sha256, request_ids, reads):
        self.request = request
        self.request_sha256 = request_sha256
        self.request_ids = request_ids
        self.reads = reads


def read_request(path: str, env: Environment):
    c, d = collect(), deploy()
    p = c.preflight()
    try:
        request, request_sha256, ids = c.read_request(path, env.collector)
    except (c.CollectError, p.PreflightError, p.snapshot().SnapshotError, *d.handled_errors()):
        raise BootchainError("request tree failed safe inspection (code request-rejected)") from None
    registry = list(c.policy_registry()["operations"])
    if [row["id"] for row in request["requested_reads"]] != registry:
        raise BootchainError("request operations differ from the collector registry")
    return request, request_sha256, ids


def request_row(request: dict) -> dict:
    return next(row for row in request["requested_reads"] if row["id"] == R2_ID)


def gather(args, env: Environment) -> Inputs:
    d = deploy()
    if d.paths_overlap(args.request, args.reads):
        raise BootchainError("reads and request paths overlap")
    request, request_sha256, request_ids = read_request(args.request, env)
    reads = read_reads(args.reads, env, request_sha256)
    if request_ids & reads.directory_ids:
        raise BootchainError("reads alias the request tree")
    return Inputs(request, request_sha256, request_ids, reads)


# --- R2 operation ---------------------------------------------------------------


def adapt(inputs: Inputs) -> dict:
    """The R2 data and its fixture payload accounting, derived from the synthetic bytes alone."""
    files, geometry = inputs.reads.files, inputs.reads.geometry
    partitions = parse_gpt(files, geometry)
    return {
        "data": {
            "partitions": partitions,
            "recovery_present": any(RECOVERY_NAME.fullmatch(row["partition_name"]) for row in partitions),
        },
        "bytes_read": sum(len(files[path]) for path in PAYLOAD),
    }


def operation_document(request_sha256: str, result: dict) -> dict:
    c = collect()
    return {
        "schema": c.OPERATION_SCHEMA,
        "kind": c.OPERATION_KIND,
        "id": R2_ID,
        "request_sha256": request_sha256,
        "transport": c.TRANSPORT,
        "read_domain": c.READ_DOMAIN,
        "read_only": True,
        "bytes_read": result["bytes_read"],
        "data": result["data"],
    }


def validate_operation(env: Environment, request: dict, request_sha256: str, raw: bytes) -> dict:
    """The unchanged collector validates the fragment; its messages hold labels, never values."""
    row = request_row(request)
    if len(raw) > row["max_output_bytes"]:
        raise BootchainError("R2 operation exceeds the collector's output bound")
    document, _outcome = collect().validate_operation(raw, row, request_sha256, env.identity)
    return document


def sums_of(files: dict) -> bytes:
    d = deploy()
    return "".join(
        f"{d.sha256_bytes(files[path])}  {path}\n" for path in sorted(files, key=lambda p: p.encode())
    ).encode("ascii")


def input_rows(inputs: Inputs) -> list[dict]:
    files = {**inputs.reads.files, MANIFEST_PATH: inputs.reads.manifest_bytes}
    return [
        {"path": path, "role": INPUT_ROWS[path]["role"], "bytes": len(files[path]),
         "sha256": sha256_hex(files[path])}
        for path in sorted(files)
    ]


def parse_document(env: Environment, inputs: Inputs, result: dict, operation: bytes) -> dict:
    row = request_row(inputs.request)
    return {
        "schema": 1,
        "kind": PARSE_KIND,
        "format_version": VERSION,
        "bootchain_contract_sha256": env.contract_sha256,
        "capture_contract_sha256": env.collector.contract_sha256,
        "preflight_contract_sha256": env.collector.preflight_sha256,
        "request_sha256": inputs.request_sha256,
        "reads_sha256": inputs.reads.sha256,
        "implementation": implementation_binding(),
        "dependencies": {
            "trust": DEPENDENCY_TRUST, "byte_pinned": False, "pinned_versions": dict(PINNED_VERSIONS),
        },
        "profile": PROFILE,
        "inventory_scope": INVENTORY_SCOPE,
        "transport": TRANSPORT,
        "evidence_level": EVIDENCE_LEVEL,
        "status": PARSE_STATUS,
        "synthetic": True,
        "live": False,
        "executes": False,
        "kit_snapshot_reverified": False,
        "remote_commands": [],
        "human_approval_required": True,
        "complete_capture": False,
        "inputs": input_rows(inputs),
        "operation": {
            "id": R2_ID,
            "path": OUTPUT_OPERATION_PATH,
            "bytes": len(operation),
            "sha256": sha256_hex(operation),
            "bytes_read": result["bytes_read"],
            **{key: row[key] for key in collect().BUDGET_KEYS},
            "partition_count": len(result["data"]["partitions"]),
        },
        "accounting": {
            **accounting_policy(),
            "total_fixture_payload_bytes": sum(
                len(data) for data in {**inputs.reads.files, MANIFEST_PATH: inputs.reads.manifest_bytes}.values()
            ),
        },
        "coverage": coverage_rows(),
        "semantic_limits": list(SEMANTIC_LIMITS),
        "unresolved_claims": unresolved_claims(),
        "deferred": deferred_rows(),
        "qualification": qualification(),
        "limitations": list(LIMITATIONS),
        "non_goals": list(NON_GOALS),
        "blockers": blocker_rows(),
        "authority": authority(),
    }


def parse_spec(env: Environment, inputs: Inputs) -> list:
    d = deploy()
    result = adapt(inputs)
    operation = d.render_json(operation_document(inputs.request_sha256, result))
    validate_operation(env, inputs.request, inputs.request_sha256, operation)
    files = {
        "parse.json": d.render_json(parse_document(env, inputs, result, operation)),
        OUTPUT_OPERATION_PATH: operation,
    }
    files["SHA256SUMS"] = sums_of(files)
    if sorted(files) != OUTPUT_FILES:
        raise BootchainError("parse output closure differs from the contract")
    spec = [("operations", "dir", 0o755, None)]
    spec += [(path, "file", 0o644, data) for path, data in files.items()]
    spec.sort(key=lambda item: item[0].encode("utf-8"))
    return spec


def spec_file(spec: list, path: str) -> bytes:
    return next(data for name, kind, _mode, data in spec if name == path and kind == "file")


def result_summary(status: str, inputs: Inputs, spec: list) -> dict:
    d = deploy()
    operation = spec_file(spec, OUTPUT_OPERATION_PATH)
    document = json.loads(operation)
    return {
        "status": status,
        "evidence_level": EVIDENCE_LEVEL,
        "profile": PROFILE,
        "operation": R2_ID,
        "parse_sha256": d.sha256_bytes(spec_file(spec, "SHA256SUMS")),
        "operation_sha256": d.sha256_bytes(operation),
        "request_sha256": inputs.request_sha256,
        "reads_sha256": inputs.reads.sha256,
        "bytes_read": document["bytes_read"],
        "partition_count": len(document["data"]["partitions"]),
        "blocker_count": len(d.BLOCKERS),
        "synthetic": True,
        "live": False,
        "executes": False,
        "kit_snapshot_reverified": False,
        "complete_capture": False,
        **authority(),
    }


# --- plan -----------------------------------------------------------------------


def plan_document(env: Environment, request: dict, request_sha256: str) -> dict:
    d = deploy()
    row = request_row(request)
    return {
        "schema": 1,
        "kind": PLAN_KIND,
        "format_version": VERSION,
        "bootchain_contract_sha256": env.contract_sha256,
        "request_sha256": request_sha256,
        "request_binding": {
            "operation": R2_ID,
            **{key: row[key] for key in collect().BUDGET_KEYS},
            "emits": list(row["emits"]),
            "never_emits": list(row["never_emits"]),
            "request_sha256_is": "sha256-of-the-verified-request-SHA256SUMS-bytes",
        },
        "transport": TRANSPORT,
        "evidence_level": EVIDENCE_LEVEL,
        "implementation": implementation_binding(),
        "synthetic": True,
        "live": False,
        "executes": False,
        "kit_snapshot_reverified": False,
        "remote_commands": [],
        "complete_capture": False,
        "supported_profile": profile_contract(),
        "input_closure": {
            "manifest": MANIFEST_PATH,
            "files": [dict(item) for item in INPUT_FILES],
            "entries_max": READS_ENTRIES,
            "total_max_bytes": TOTAL_READS_BYTES,
            "json_depth_max": JSON_DEPTH,
            "extra_entries": "reject",
            "header_size_rule": "512..4096 at metadata admission, then exactly sector_bytes",
        },
        "output_closure": output_closure(),
        "accounting": accounting_policy(),
        "coverage": coverage_rows(),
        "semantic_limits": list(SEMANTIC_LIMITS),
        "unresolved_claims": unresolved_claims(),
        "deferred": deferred_rows(),
        "qualification": qualification(),
        "limitations": list(LIMITATIONS),
        "non_goals": list(NON_GOALS),
        "human_approval_required": True,
        "blockers": list(d.BLOCKERS),
        "authority": authority(),
    }


# --- untrusted parse trees ------------------------------------------------------
# A parse tree under verification is untrusted: its names, links and special files
# must never reach a diagnostic. Every failure from the shared tree reader and the
# entry comparison becomes a fixed code here.

TREE_FAILURE_CODES = (
    ("symlink", "symlink"), ("special file", "special-file"), ("hard link", "hardlink"),
    ("writable or controlled", "ownership-or-mode"), ("mount", "mount-crossing"),
    ("device boundary", "mount-crossing"), ("name", "unsafe-name"), ("exceeds", "bound"),
    ("changed", "unstable"),
)


def tree_failure_code(message: str) -> str:
    """A fixed code chosen from the reader's wording; the wording itself is never passed on."""
    for fragment, code in TREE_FAILURE_CODES:
        if fragment in message:
            return code
    return "unsafe"


def output_limits():
    return deploy().Limits(8, 2, 1024 * 1024, 4 * 1024 * 1024)


def walk_output(descriptor: int, label: str, **options):
    d = deploy()
    try:
        return d.walk_tree(descriptor, output_limits(), allow_symlinks=False, label=label, **options)
    except d.handled_errors() as error:
        raise BootchainError(
            f"{label} tree failed safe inspection (code {tree_failure_code(str(error))})"
        ) from None


def diff_output(actual: list, expected: list, label: str) -> None:
    """Compare entries; only the expected side's own paths may be named."""
    have = {entry.path: entry for entry in actual}
    want = {entry.path: entry for entry in expected}
    extra = len(set(have) - set(want))
    if extra:
        raise BootchainError(f"{label} has {extra} unexpected paths (names withheld)")
    missing = sorted(set(want) - set(have))
    if missing:
        raise BootchainError(f"{label} is missing paths: {missing}")
    for path in sorted(want):
        if have[path] != want[path]:
            raise BootchainError(f"{label} differs at {path}")


def revalidate_tree(tree, env: Environment, request: dict, request_sha256: str, label: str) -> None:
    """The collector's validate_operation on the operation bytes found in the tree itself."""
    c, d = collect(), deploy()
    try:
        validate_operation(env, request, request_sha256, tree.data[OUTPUT_OPERATION_PATH])
    except (c.CollectError, *d.handled_errors()):
        raise BootchainError(f"{label} operation was refused by the collector (code operation-rejected)") from None


# --- commands -------------------------------------------------------------------


def command_plan(env: Environment, args) -> dict:
    request, request_sha256, _ids = read_request(args.request, env)
    return plan_document(env, request, request_sha256)


def command_parse(env: Environment, args) -> dict:
    d = deploy()
    for path in (args.request, args.reads):
        if d.paths_overlap(args.out, path):
            raise BootchainError("output path overlaps an input")
    inputs = gather(args, env)
    spec = parse_spec(env, inputs)
    expected = d.spec_entries(spec)
    protected = [args.request, args.reads]
    protected_ids = frozenset(inputs.request_ids | inputs.reads.directory_ids)

    def verify_built(_temporary_path: str, descriptor: int) -> None:
        again = gather(args, env)
        if parse_spec(env, again) != spec:
            raise BootchainError("request or reads changed during the parse")
        tree = walk_output(descriptor, "parse", keep_data=True)
        diff_output(tree.entries, expected, "parse")
        revalidate_tree(tree, env, again.request, again.request_sha256, "built")

    try:
        d.publish(args.out, protected, protected_ids, spec, verify_built)
    except d.handled_errors():
        # Reviewed dependency classes only: their text can carry the caller's output path or names.
        raise BootchainError("parse could not be published safely (code publish-rejected)") from None
    return result_summary("parsed", inputs, spec)


def command_verify_parse(env: Environment, args) -> dict:
    d = deploy()
    if any(d.paths_overlap(args.parse, path) for path in (args.request, args.reads)):
        raise BootchainError("parse overlaps an input")
    inputs = gather(args, env)
    spec = parse_spec(env, inputs)
    descriptor, identity = d.open_trusted_artifact(args.parse, "parse")
    try:
        tree = walk_output(descriptor, "parse", keep_data=True, trusted_ownership=True)
    finally:
        os.close(descriptor)
    diff_output(tree.entries, d.spec_entries(spec), "parse")
    if tree.directory_ids & (inputs.request_ids | inputs.reads.directory_ids):
        raise BootchainError("parse aliases an input tree")
    revalidate_tree(tree, env, inputs.request, inputs.request_sha256, "parsed")
    d.recheck_trusted_artifact(args.parse, identity, "parse")
    again = gather(args, env)
    if parse_spec(env, again) != spec:
        raise BootchainError("request or reads changed during verification")
    return result_summary("verified", inputs, spec)


class UsageError(BootchainError):
    """The command line is not one of the fixed commands; the text never carries the arguments."""


class FixedParser(argparse.ArgumentParser):
    """argparse echoes unknown commands, options and paths: refuse with one fixed line instead."""

    def error(self, message):
        raise UsageError("invalid command line (code usage); see --help")


def build_parser() -> argparse.ArgumentParser:
    parser = FixedParser(prog="myron-bootchain", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True, parser_class=FixedParser)
    commands.add_parser("show", help="verify and print the committed bootchain contract")
    commands.add_parser(
        "derive-contract",
        help="print the contract derived from the pinned upstream contracts; writes nothing",
    )
    plan = commands.add_parser("plan", help="print the value-free offline parse plan")
    plan.add_argument("--request", required=True)
    parse = commands.add_parser("parse", help="parse the synthetic GPT reads into an R2 fragment")
    parse.add_argument("--request", required=True)
    parse.add_argument("--reads", required=True)
    parse.add_argument("--out", required=True)
    verify = commands.add_parser("verify-parse", help="recompute a parse artifact")
    verify.add_argument("--request", required=True)
    verify.add_argument("--reads", required=True)
    verify.add_argument("--parse", required=True)
    return parser


def load_dependencies():
    """Every dependency, loaded once before any input is read, inside one protected phase.

    A missing or broken collector, preflight, snapshot, deployment, kernel or GPU verifier is
    one fixed refusal. The runtime exception tuple is built here from plain types, so no
    except clause later imports or loads anything while it handles another failure."""
    try:
        c = collect()
        p = c.preflight()
        d = p.deploy()
        s = p.snapshot()
        # d.handled_errors() would add OSError and ValueError, whose text can carry paths:
        # those keep their own fixed handling in main.
        exported = (BootchainError, c.CollectError, p.PreflightError, s.SnapshotError,
                    d.DeploymentError, d.kernel().ContractError, d.gpu().ProfileError)
        # An export that is not a plain exception class would fail inside an except clause.
        if not all(type(error) is type and issubclass(error, Exception) for error in exported):
            raise BootchainError(DEPENDENCY_REJECTED)
        runtime_errors = exported
    except BootchainError:
        raise  # collect(), or the check above: fixed text, or the pinned-version refusal
    except (Exception, SystemExit):
        raise BootchainError(DEPENDENCY_REJECTED) from None
    return c, p, d, s, runtime_errors


def main(argv: list[str] | None = None, contracts_root: Path | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
    except UsageError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    try:
        c, p, d, s, runtime_errors = load_dependencies()
    except BootchainError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    root = contracts_root or REPO
    try:
        if args.command == "derive-contract":
            # No committed bootchain contract is read: the pinned upstream contracts and this
            # source alone derive the bytes that `show` verifies. Nothing is written or authorized.
            result = expected_bootchain_contract(load_collector_environment(root))
        else:
            env = load_environment(root)
            if args.command == "show":
                result = env.contract
            elif args.command == "plan":
                result = command_plan(env, args)
            elif args.command == "parse":
                result = command_parse(env, args)
            else:
                result = command_verify_parse(env, args)
    except runtime_errors as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    except OSError:
        print("ERROR: an input or output operation failed (code io-error)", file=sys.stderr)
        return 1
    except ValueError:
        # Text of an unexpected ValueError (numbers, UTF-8) is never printed. Only Exception
        # subclasses are caught: SystemExit and KeyboardInterrupt pass through.
        print("ERROR: an input could not be processed (code value-error)", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
