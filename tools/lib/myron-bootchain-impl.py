# SPDX-License-Identifier: MIT
"""Parse synthetic bytes into the exact Myron R2, R3 and R4 operation fragments.

Offline and synthetic only. Three independent command families share one trust root.
`parse` reads a fixed closure of six flat files (a manifest, an explicit geometry claim and
the primary and backup GPT headers and entry tables) into the R2 operation. `parse-images`
reads one flat directory of synthetic Android boot (v0-v4), vendor_boot (v3, v4) and DT table
(v0) images, bound to a validated R2 operation, into the metadata-only R3 operation.
`parse-selection` reparses the same exact R3 fixture bytes, counts the flattened device tree
blobs of one fixed base partition and the entries of one DT table, checks a synthetic index
witness for membership and binding only, and emits an R4 operation whose selected board id,
revision and selection source are always null. All fragments are validated by the unchanged
tools/myron-collect. Nothing here reads a phone or a block device, acquires evidence,
authorizes anything or clears a blocker. Which board a real device selects is not
established: that is the recorded hardware-witness successor gate.

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

VERSION = "0.4.0"
REPO = Path(__file__).resolve().parent.parent
COLLECT_TOOL = REPO / "tools/myron-collect"
PINNED_VERSIONS = {
    "collector": "0.3.0", "preflight": "0.4.0", "snapshot": "0.2.0", "deployment": "0.4.0",
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
    "r3-acquisition-provenance-not-established",
    "r3-image-freshness-not-established",
    "r3-hardware-transport-not-established",
    "r4-selection-provenance-not-established",
    "r4-selection-source-semantics-not-established",
    "r4-actual-myron-witness-not-established",
    "r4-selection-freshness-not-established",
    "r4-multi-overlay-ordering-not-established",
]
DEFERRED = [
    {
        "id": R4_ID, "state": "hardware-witness-required",
        "successor_gate": "r4-selection-source-qualification",
        "requires": [
            "a concrete selected-index source: parsing a DTBO or FDT does not prove selection",
            "an actual Myron witness and contract cross-checks",
            "captured provenance and freshness of the witness and of the images it indexes",
            "a qualified source semantics: which partition, format and field names the live selection",
            "an ordering model for more than one overlay: this synthetic gate binds one base and one overlay index",
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
    "the GPT parse produces only the R2 operation fragment, the image parse only the R3 operation fragment and the selection parse only an R4 fragment with a null selection triple: none is a capture, and which board a real device selects stays a recorded hardware-witness successor gate",
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
    "an actual R4 DTB or DTBO selection, a selected board id, revision or source, hardware acquisition of images, or any complete R1-R7 capture",
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
    check_image_registry_consistency(c)
    check_selection_registry_consistency(c)
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
        "image_parser": image_parser_contract(),
        "selection_parser": selection_parser_contract(),
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
        "hardware_qualified": False,
        "implemented_operations": [R2_ID, R3_ID, R4_ID],
        "command_scope": {
            "parse": [R2_ID], "parse-images": [R3_ID], "parse-selection": [R4_ID],
        },
        "r4_capability": {
            "counts_from_synthetic_bytes": True,
            "synthetic_index_binding": True,
            "selected_board_fields_produced": False,
            "captured_provenance": False,
            "hardware_qualified": False,
        },
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


def operation_document(request_sha256: str, result: dict, operation_id: str = R2_ID) -> dict:
    c = collect()
    return {
        "schema": c.OPERATION_SCHEMA,
        "kind": c.OPERATION_KIND,
        "id": operation_id,
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


# --- R3 synthetic image parsers (image parser contract 1.0.0) ---------------------
# Android boot v0-v4, vendor_boot v3-v4 and DT table v0 bytes, held in one flat synthetic
# fixture directory, are parsed into the metadata-only R3 operation that the unchanged
# collector validates. The parsers recompute every offset, size, hash and coverage range from
# the admitted immutable buffers. Nothing here reads a phone, a block device or any firmware:
# the fixtures are generated by tests at runtime and never committed.
#
# Accounting (per complete gather; verification and publication re-gather separately):
#   S = canonical images.json bytes + the bytes of every present image file
#   M = union bytes of the exact header structures and nonempty tables (represented
#       metadata coverage only: hardware_bytes_read is 0 and no transport exists)
#   O = canonical serialized R3 operation bytes, newline and whitespace included
# S is the operation's bytes_read (<= the collector's max_fixture_input_bytes), M is bounded
# by the collector's max_hardware_read_bytes, and O by this parser's own
# max_output_metadata_bytes: three distinct limits that are never conflated.

IMAGE_PARSER_VERSION = "1.0.0"
IMAGES_KIND = "myron-synthetic-r3-images"
IMAGE_PLAN_KIND = "myron-synthetic-r3-image-parse-plan"
IMAGE_PARSE_KIND = "myron-synthetic-r3-image-parse"
IMAGE_PROFILE = "r3-android-boot-v0-v4-vendor-v3-v4-dt-table-v0-metadata-only"
IMAGE_TRANSPORT = "synthetic-binary-image-fixture"
IMAGE_EVIDENCE_LEVEL = "synthetic-binary-image-parser-only"
IMAGE_PARSE_STATUS = "synthetic-r3-parse-recorded"
IMAGE_ACCOUNTING_SCOPE = "one-admitted-fixture-snapshot"
IMAGE_MANIFEST_PATH = "images.json"
IMAGE_OPERATION_PATH = f"operations/{R3_ID}.json"
IMAGE_OUTPUT_FILES = sorted(["SHA256SUMS", "parse.json", IMAGE_OPERATION_PATH])
IMAGE_ROLES = ["boot", "init_boot", "vendor_boot", "vendor_kernel_boot", "dtbo", "recovery"]
IMAGE_SUFFIXES = ["", "_a", "_b"]
IMAGE_NAMES = sorted(role + suffix for role in IMAGE_ROLES for suffix in IMAGE_SUFFIXES)
IMAGE_FILE_SUFFIX = ".img"
BOOT_ROLES = ("boot", "init_boot", "recovery")
VENDOR_ROLES = ("vendor_boot", "vendor_kernel_boot")
MAX_IMAGE_BYTES = 16 * 1024 * 1024
MIN_IMAGE_BYTES = 32
IMAGE_MANIFEST_MAX_BYTES = 16384
IMAGE_LISTING_MAX = len(IMAGE_NAMES) + 2  # the manifest and one entry past the 18 images
MAX_FIXTURE_INPUT_BYTES = 64 * 1024 * 1024  # S, per gather: the collector's R3 bound
MAX_REPRESENTED_METADATA_BYTES = 65536  # M: the collector's max_hardware_read_bytes for R3
MAX_OUTPUT_METADATA_BYTES = 65536  # O: this parser's own bound, not the collector's
MAX_VENDOR_FRAGMENTS = 64
MAX_DT_ENTRIES = 256
IMAGE_PAGE_SIZES = [2048, 4096, 8192, 16384]
EXTENT_LIMIT = 2**32
BOOT_FORMAT, VENDOR_FORMAT, DT_FORMAT = "android-boot", "android-vendor-boot", "android-dt-table"
BOOT_MAGIC, VENDOR_MAGIC, DT_MAGIC = b"ANDROID!", b"VNDRBOOT", 0xD7B7AB1E
BOOT_HEADERS = {0: 1632, 1: 1648, 2: 1660, 3: 1580, 4: 1584}
VENDOR_HEADERS = {3: 2112, 4: 2128}
VENDOR_TABLE_ENTRY = 108
VENDOR_NAME_BYTES = 32
DT_HEADER = DT_ENTRY = 32
IMAGE_CODES = {
    "image-input-rejected": "the image fixture, request or inventory failed safe admission",
    "image-identity-mismatch": "the image fixture disagrees with its bindings, the R2 inventory or its role",
    "image-unstable": "an input changed while it was admitted or read",
    "image-corrupt": "the image bytes are internally inconsistent",
    "image-unsupported": "the image bytes may be valid but lie outside the supported profile",
    "image-budget": "a count, size or accounting bound was exceeded",
    "image-operation-rejected": "the collector refused the R2 inventory or the produced R3 operation",
    "publish-rejected": "the output could not be published safely",
}
IMAGE_NOT_PRODUCED = [
    "R1-identity-and-slot", R2_ID, R4_ID, "R5-module-load-order", "R6-storage-and-mount-model",
    "R7-kernel-identity-revalidation",
]
IMAGE_SAFETY = SAFETY + [
    "closure-derived-from-admitted-manifest", "immutable-captured-buffers", "value-free-diagnostics",
    "trusted-inventory-file",
]
IMAGE_SEMANTIC_LIMITS = [
    "evidence is metadata-only: header and table hashes are recomputed from the admitted bytes, image sha256 is always null",
    "coverage is the exact header structures plus nonempty tables with adjacent ranges merged: never page padding, payload, EOF or the full image",
    "component sha256 is null unless a component lies wholly inside covered metadata (payload normally does not)",
    "a boot_signature extent is a structure extent only: no cryptographic or verified-boot claim",
    "os_version is the literal packed header value, zero included: no version text is derived",
    "recovery_dtbo offsets are checked against the computed layout and never used to derive the dtb offset",
    "vendor ramdisk fragment order is the table index order: no load order, selection or R4 inference",
    "vendor ramdisk names, DT ids, revisions, custom values and board ids are never emitted",
    "image: null means absence from the bound R2 inventory, never mere file absence and never proof about the device",
]
IMAGE_LIMITATIONS = [
    "synthetic binary parser qualification only: the fixture bytes were never read from a phone or a block device and carry no captured provenance",
    "the parser establishes no hardware qualification, freshness, slot semantics, bootability or flash safety",
    "metadata-only evidence: no image hash, no payload hash and no full-image coverage is ever produced",
    "boot v0-v4, vendor_boot v3 and v4 and DT table v0 only, with the page sizes, counts and limits of the collector's R3 profile; other valid variants are refused as unsupported",
    "DT table payload extents that are shared, reused or overlapping are valid AOSP but outside the collector's disjoint-extent profile: refused as unsupported, not corrupt",
    "a metadata-only image whose covered metadata equals the whole image is refused as unsupported (the collector would reject it as full coverage)",
    "an image shorter than its aligned layout is refused as corrupt: components past the file end are never emitted",
    "operation bytes_read is S (images.json plus every present image file) and is fixture payload accounting, no device I/O; hardware_bytes_read is 0 with hardware_transport none",
    "each complete gather admits at most 64 MiB (S): parse-images gathers three times (admission, temporary and published verification) and verify-images twice, so total invocation I/O exceeds S",
    "each gather is an internally validated descriptor-read snapshot of the exact bytes consumed, not an atomic filesystem snapshot and not writer exclusion; a later verify against a changed source rejects",
    "the R2 inventory is bound by its exact bytes after separate collector validation; it proves nothing about a device",
    "the collector, preflight, snapshot and deployment imports are trusted version-pinned dependencies, not fully byte-pinned execution",
    "publication is durable only if the output parent's fsync succeeds; a failure there removes the just-published output by identity on a best-effort basis",
]


class ImageError(BootchainError):
    """A fixed-category refusal. The reason is a literal written in this file, never input."""

    def __init__(self, code: str, reason: str):
        super().__init__(reason)
        self.code = code

    def __str__(self) -> str:
        return f"{self.args[0]} (code {self.code})"


class ImageCorrupt(ImageError):
    def __init__(self, reason: str):
        super().__init__("image-corrupt", reason)


class ImageUnsupported(ImageError):
    def __init__(self, reason: str):
        super().__init__("image-unsupported", reason)


class ImageBudget(ImageError):
    def __init__(self, reason: str):
        super().__init__("image-budget", reason)


def role_of_name(name: str) -> str:
    return name[:-2] if name.endswith(("_a", "_b")) else name


def image_file_name(name: str) -> str:
    """The fixed fixture filename of one logical partition name."""
    return name + IMAGE_FILE_SUFFIX


IMAGE_FILE_NAMES = {image_file_name(name): name for name in IMAGE_NAMES}


# --- exact-length readers and checked arithmetic -------------------------------------


def read_int(data: bytes, offset: int, width: int, order: str) -> int:
    end = offset + width
    if offset < 0 or end > len(data):
        raise ImageCorrupt("a header field lies past the end of the image")
    return int.from_bytes(data[offset:end], order)


def le32(data: bytes, offset: int) -> int:
    return read_int(data, offset, 4, "little")


def le64(data: bytes, offset: int) -> int:
    return read_int(data, offset, 8, "little")


def be32(data: bytes, offset: int) -> int:
    return read_int(data, offset, 4, "big")


def bounded(value: int) -> int:
    """Every emitted offset and extent end stays inside 32 bits."""
    if value > EXTENT_LIMIT:
        raise ImageCorrupt("an extent overflows 32 bits")
    return value


def check_page(page: int) -> None:
    """The page size is judged before any alignment arithmetic uses it."""
    if page in IMAGE_PAGE_SIZES:
        return
    if page > 0 and page & (page - 1) == 0:
        raise ImageUnsupported("the page size lies outside the supported profile")
    raise ImageCorrupt("the page size is not a power of two")


def align(value: int, page: int) -> int:
    return bounded((value + page - 1) // page * page)


# --- format parsers ------------------------------------------------------------------
# Each parser returns the layout of one image: the format facts, an optional table and
# component slots as (role, index, offset, size, ramdisk_type). Offsets of zero-size
# components are the computed layout positions. No parser hashes anything.


def layout(fmt, version, page, os_version, header, table, components) -> dict:
    return {
        "format": fmt, "version": version, "page_size": page, "os_version": os_version,
        "header_bytes": header, "table": table, "components": components,
    }


def parse_boot(role: str, data: bytes) -> dict:
    if len(data) < 48:
        raise ImageCorrupt("the boot header is truncated")
    if data[:8] != BOOT_MAGIC:
        raise ImageError("image-identity-mismatch", "the boot image magic differs from its partition role")
    version = le32(data, 40)
    if version not in BOOT_HEADERS:
        raise ImageUnsupported("the boot header version lies outside the supported profile")
    if role == "init_boot" and version != 4:
        raise ImageUnsupported("init_boot requires boot header version 4")
    header = BOOT_HEADERS[version]
    if len(data) < header:
        raise ImageCorrupt("the boot header is truncated")
    if version >= 3:
        if le32(data, 20) != header:
            raise ImageCorrupt("the boot header_size differs from its version")
        page = 4096
        kernel, ramdisk, os_version = le32(data, 8), le32(data, 12), le32(data, 16)
        if role == "init_boot" and kernel != 0:
            raise ImageUnsupported("init_boot requires a zero-size kernel")
        kernel_offset = page
        ramdisk_offset = bounded(kernel_offset + align(kernel, page))
        components = [("kernel", 0, kernel_offset, kernel, None),
                      ("ramdisk", 0, ramdisk_offset, ramdisk, None)]
        if version == 4:
            signature = le32(data, 1580)
            components.append(
                ("boot_signature", 0, bounded(ramdisk_offset + align(ramdisk, page)), signature, None))
        return layout(BOOT_FORMAT, version, page, os_version, header, None, components)
    page = le32(data, 36)
    check_page(page)
    kernel, ramdisk, second = le32(data, 8), le32(data, 16), le32(data, 24)
    os_version = le32(data, 44)
    kernel_offset = page
    ramdisk_offset = bounded(kernel_offset + align(kernel, page))
    second_offset = bounded(ramdisk_offset + align(ramdisk, page))
    next_offset = bounded(second_offset + align(second, page))
    components = [("kernel", 0, kernel_offset, kernel, None), ("ramdisk", 0, ramdisk_offset, ramdisk, None),
                  ("second", 0, second_offset, second, None)]
    if version >= 1:
        dtbo_size, dtbo_stored = le32(data, 1632), le64(data, 1636)
        if le32(data, 1644) != header:
            raise ImageCorrupt("the boot header_size differs from its version")
        if dtbo_size and dtbo_stored != next_offset:
            raise ImageCorrupt("the recovery_dtbo offset differs from the computed layout")
        if not dtbo_size and dtbo_stored not in (0, next_offset):
            raise ImageCorrupt("the empty recovery_dtbo offset is neither zero nor the layout position")
        components.append(("recovery_dtbo", 0, next_offset, dtbo_size, None))
        next_offset = bounded(next_offset + align(dtbo_size, page))
    if version >= 2:
        components.append(("dtb", 0, next_offset, le32(data, 1648), None))
    return layout(BOOT_FORMAT, version, page, os_version, header, None, components)


def parse_vendor(role: str, data: bytes) -> dict:
    if len(data) < 16:
        raise ImageCorrupt("the vendor boot header is truncated")
    if data[:8] != VENDOR_MAGIC:
        raise ImageError("image-identity-mismatch", "the vendor boot magic differs from its partition role")
    version = le32(data, 8)
    if version not in VENDOR_HEADERS:
        raise ImageUnsupported("the vendor boot header version lies outside the supported profile")
    page = le32(data, 12)
    check_page(page)
    header = VENDOR_HEADERS[version]
    if len(data) < header:
        raise ImageCorrupt("the vendor boot header is truncated")
    if le32(data, 2096) != header:
        raise ImageCorrupt("the vendor boot header_size differs from its version")
    ramdisk_size, dtb_size = le32(data, 24), le32(data, 2100)
    section = align(header, page)
    dtb_offset = bounded(section + align(ramdisk_size, page))
    if version == 3:
        components = [("vendor_ramdisk", 0, section, ramdisk_size, None), ("dtb", 0, dtb_offset, dtb_size, None)]
        return layout(VENDOR_FORMAT, 3, page, None, header, None, components)
    table_size, count, entry_size, bootconfig_size = (le32(data, at) for at in (2112, 2116, 2120, 2124))
    if entry_size != VENDOR_TABLE_ENTRY:
        raise ImageUnsupported("the vendor ramdisk table entry size lies outside the supported profile")
    if count > MAX_VENDOR_FRAGMENTS:
        raise ImageBudget("the vendor ramdisk table holds more entries than the profile allows")
    if table_size != count * VENDOR_TABLE_ENTRY:
        raise ImageCorrupt("the vendor ramdisk table size is not entry count times entry size")
    if count == 0 and ramdisk_size != 0:
        raise ImageCorrupt("an empty vendor ramdisk table needs a zero-size ramdisk section")
    table_offset = bounded(dtb_offset + align(dtb_size, page))
    bootconfig_offset = bounded(table_offset + align(table_size, page))
    if bounded(table_offset + table_size) > len(data):
        raise ImageCorrupt("the vendor ramdisk table runs past the end of the image")
    fragments, names, positive = [], set(), []
    for index in range(count):
        base = table_offset + index * VENDOR_TABLE_ENTRY
        size, relative, ramdisk_type = le32(data, base), le32(data, base + 4), le32(data, base + 8)
        name = data[base + 12:base + 12 + VENDOR_NAME_BYTES]
        end = name.find(b"\0")
        if end < 0:
            raise ImageUnsupported("a vendor ramdisk name has no NUL terminator within its field")
        if name[:end] in names:  # compared as bytes before the first NUL, never emitted
            raise ImageCorrupt("vendor ramdisk names repeat")
        names.add(name[:end])
        if ramdisk_type > 3:
            raise ImageUnsupported("a vendor ramdisk type lies outside the supported profile")
        if relative > ramdisk_size or relative + size > ramdisk_size:
            raise ImageCorrupt("a vendor ramdisk fragment lies outside its section")
        if size:
            positive.append((relative, size))
        fragments.append((FRAGMENT, index, bounded(section + relative), size, ramdisk_type))
    cursor = 0
    for relative, size in sorted(positive):
        if relative < cursor:
            raise ImageCorrupt("vendor ramdisk fragments overlap")
        if relative > cursor:
            raise ImageCorrupt("vendor ramdisk fragments leave a gap")
        cursor = relative + size
    if cursor != ramdisk_size:
        raise ImageCorrupt("vendor ramdisk fragments do not cover their section")
    table = {"role": "vendor_ramdisk_table", "offset": table_offset, "size": table_size,
             "entry_size": VENDOR_TABLE_ENTRY, "count": count}
    components = [*fragments, ("dtb", 0, dtb_offset, dtb_size, None),
                  ("bootconfig", 0, bootconfig_offset, bootconfig_size, None)]
    return layout(VENDOR_FORMAT, 4, page, None, header, table, components)


FRAGMENT = "vendor_ramdisk_fragment"


def parse_dt_table(role: str, data: bytes) -> dict:
    if len(data) < DT_HEADER:
        raise ImageCorrupt("the DT table header is truncated")
    if be32(data, 0) != DT_MAGIC:
        raise ImageError("image-identity-mismatch", "the DT table magic differs from its partition role")
    total, header_size, entry_size, count, entries_offset, page, version = (
        be32(data, at) for at in (4, 8, 12, 16, 20, 24, 28))
    if version != 0:
        raise ImageUnsupported("the DT table version lies outside the supported profile")
    if header_size != DT_HEADER or entry_size != DT_ENTRY:
        raise ImageUnsupported("the DT table header or entry stride lies outside the supported profile")
    if count == 0:
        raise ImageUnsupported("an empty DT table lies outside the supported profile")
    if count > MAX_DT_ENTRIES:
        raise ImageBudget("the DT table holds more entries than the profile allows")
    check_page(page)
    if total < DT_HEADER or total > len(data):
        raise ImageCorrupt("the DT table total size does not fit the image")
    if entries_offset < DT_HEADER:
        raise ImageCorrupt("the DT entry table overlaps the header")
    table_size = count * DT_ENTRY
    if bounded(entries_offset + table_size) > total:
        raise ImageCorrupt("the DT entry table runs past the total size")
    components, positive = [], []
    for index in range(count):
        base = entries_offset + index * DT_ENTRY
        size, offset = be32(data, base), be32(data, base + 4)
        if bounded(offset + size) > total:
            raise ImageCorrupt("a DT payload runs past the total size")
        if size:
            positive.append((offset, size))
        components.append(("dt_entry", index, offset, size, None))
    for offset, size in positive:
        if offset < DT_HEADER or (offset < entries_offset + table_size and entries_offset < offset + size):
            raise ImageCorrupt("a DT payload overlaps the header or the entry table")
    positive.sort()
    for (first, first_size), (second, _size) in zip(positive, positive[1:]):
        if second < first + first_size:
            raise ImageUnsupported("shared, reused or overlapping DT payload extents lie outside the supported profile")
    table = {"role": "dt_entry_table", "offset": entries_offset, "size": table_size,
             "entry_size": DT_ENTRY, "count": count}
    return layout(DT_FORMAT, 0, page, None, DT_HEADER, table, components)


def parse_layout(name: str, data: bytes) -> dict:
    role = role_of_name(name)
    if role in BOOT_ROLES:
        return parse_boot(role, data)
    if role in VENDOR_ROLES:
        return parse_vendor(role, data)
    return parse_dt_table(role, data)


# --- evidence ------------------------------------------------------------------------


def merge_ranges(extents: list) -> list[tuple[int, int]]:
    merged = []
    for offset, size in sorted(extents):
        if merged and offset <= merged[-1][0] + merged[-1][1]:
            end = max(merged[-1][0] + merged[-1][1], offset + size)
            merged[-1] = (merged[-1][0], end - merged[-1][0])
        else:
            merged.append((offset, size))
    return merged


def image_summary(name: str, data: bytes) -> dict:
    """The collector's R3 image object for one admitted buffer, metadata-only."""
    found = parse_layout(name, data)
    size = len(data)
    header = found["header_bytes"]
    if size < header:
        raise ImageCorrupt("the image is shorter than its header")
    table = found["table"]
    extents = [(0, header)]
    if table is not None and table["size"]:
        extents.append((table["offset"], table["size"]))
    empty_offsets = [table["offset"]] if table is not None and not table["size"] else []
    for _role, _index, offset, length, _type in found["components"]:
        if length:
            if bounded(offset + length) > size:
                raise ImageCorrupt("a component runs past the end of the image")
            extents.append((offset, length))
        else:
            empty_offsets.append(offset)
    if any(offset > size for offset in empty_offsets):
        raise ImageCorrupt("an empty component lies past the end of the image")
    if found["format"] != DT_FORMAT:
        _role, _index, final_offset, final_size, _type = found["components"][-1]
        minimum_size = bounded(final_offset + align(final_size, found["page_size"]))
        if size < minimum_size:
            raise ImageCorrupt("the image ends before its final page padding")
    previous_end = 0
    for offset, length in sorted(extents):
        if offset < previous_end:
            raise ImageCorrupt("image extents overlap")
        previous_end = offset + length
    ranges = merge_ranges([(0, header)] + ([(table["offset"], table["size"])] if table is not None and table["size"] else []))
    covered = sum(length for _offset, length in ranges)
    if covered >= size:
        raise ImageUnsupported("metadata coverage equals the whole image, which the collector treats as full-image evidence")

    def inside(offset: int, length: int) -> bool:
        return any(first <= offset and offset + length <= first + span for first, span in ranges)

    components = []
    for role, index, offset, length, ramdisk_type in sorted(found["components"], key=lambda item: (item[0], item[1])):
        components.append({
            "role": role, "index": index, "offset": offset, "size_bytes": length,
            "sha256": sha256_hex(data[offset:offset + length]) if length and inside(offset, length) else None,
            "ramdisk_type": ramdisk_type,
        })
    table_value = None
    if table is not None:
        table_value = {
            "role": table["role"], "offset": table["offset"], "size_bytes": table["size"],
            "sha256": sha256_hex(data[table["offset"]:table["offset"] + table["size"]]),
            "entry_size": table["entry_size"], "entry_count": table["count"],
        }
    return {
        "format": found["format"], "version": found["version"], "page_size": found["page_size"],
        "os_version": found["os_version"], "size_bytes": size, "sha256": None,
        "header": {"offset": 0, "size_bytes": header, "sha256": sha256_hex(data[:header])},
        "components": components,
        "table": table_value,
        "coverage": {
            "kind": "metadata-only",
            "ranges": [{"index": index, "offset": offset, "size_bytes": length}
                       for index, (offset, length) in enumerate(ranges)],
            "covered_bytes": covered,
        },
    }


# --- contract ------------------------------------------------------------------------


def check_image_registry_consistency(c) -> None:
    """These constants are exactly the collector's R3 profile and budgets."""
    registry = c.policy_registry()["operations"][R3_ID]
    profile = registry["profile"]
    if profile["row_count"] != len(IMAGE_NAMES) or sorted(c.IMAGE_PARTITION_NAMES) != IMAGE_NAMES:
        raise BootchainError("image parser rows differ from the collector's")
    if profile["page_sizes"] != IMAGE_PAGE_SIZES or profile["max_image_bytes"] != MAX_IMAGE_BYTES:
        raise BootchainError("image parser page sizes or image bound differ from the collector's")
    if (profile["max_vendor_fragments"], profile["max_dt_entries"]) != (MAX_VENDOR_FRAGMENTS, MAX_DT_ENTRIES):
        raise BootchainError("image parser counts differ from the collector's")
    if profile["empty_bytes_sha256"] != sha256_hex(b"") or profile["fragment_role"] != FRAGMENT:
        raise BootchainError("image parser empty hash or fragment role differs from the collector's")
    sizes = {(item["format"], item["version"]): item["header_bytes"] for item in profile["layouts"]}
    expected = {(BOOT_FORMAT, v): n for v, n in BOOT_HEADERS.items()}
    expected |= {(VENDOR_FORMAT, v): n for v, n in VENDOR_HEADERS.items()} | {(DT_FORMAT, 0): DT_HEADER}
    if sizes != expected:
        raise BootchainError("image parser header sizes differ from the collector's")
    tables = {(item["format"], item["version"]): item["table"] for item in profile["layouts"] if item["table"]}
    if tables != {
        (VENDOR_FORMAT, 4): {"role": "vendor_ramdisk_table", "entry_bytes": VENDOR_TABLE_ENTRY,
                             "min_entries": 0, "max_entries": MAX_VENDOR_FRAGMENTS},
        (DT_FORMAT, 0): {"role": "dt_entry_table", "entry_bytes": DT_ENTRY, "min_entries": 1,
                         "max_entries": MAX_DT_ENTRIES},
    }:
        raise BootchainError("image parser tables differ from the collector's")
    budgets = registry["budgets"]
    if budgets["max_fixture_input_bytes"] != MAX_FIXTURE_INPUT_BYTES or (
        budgets["max_hardware_read_bytes"] != MAX_REPRESENTED_METADATA_BYTES
    ):
        raise BootchainError("image parser input or metadata bounds differ from the collector's")
    if MAX_OUTPUT_METADATA_BYTES > budgets["max_output_bytes"]:
        raise BootchainError("image parser output bound exceeds the collector's")
    if BOOT_MAGIC + VENDOR_MAGIC != b"ANDROID!VNDRBOOT" or MAX_IMAGE_BYTES * 2 < MAX_IMAGE_BYTES:
        raise BootchainError("image parser magic constants are inconsistent")


def image_accounting_policy() -> dict:
    return {
        "scope": IMAGE_ACCOUNTING_SCOPE,
        "S": "canonical images.json bytes plus every present image file's bytes: operation bytes_read, fixture_payload_bytes and fixture_payload_read_bytes",
        "M": "union bytes of exact header structures and nonempty tables represented as metadata coverage: represented_metadata_bytes, no hardware read",
        "O": "canonical serialized R3 operation bytes including newline and whitespace",
        "bounds": {
            "S_max_bytes_per_gather": MAX_FIXTURE_INPUT_BYTES,
            "image_max_bytes": MAX_IMAGE_BYTES,
            "M_max_bytes": MAX_REPRESENTED_METADATA_BYTES,
            "O_max_bytes": MAX_OUTPUT_METADATA_BYTES,
        },
        "bound_sources": {
            "S": "collector R3 max_fixture_input_bytes",
            "M": "collector R3 max_hardware_read_bytes",
            "O": "image parser max_output_metadata_bytes only: the collector's max_output_bytes is unchanged",
        },
        "fixture_image_hash_bytes": "sum of the present image sizes",
        "hardware_bytes_read": 0,
        "hardware_transport": "none",
        "full_image_evidence": False,
        "rereads": "parse-images gathers three times and verify-images twice: each gather is bounded by S separately",
    }


def image_layout_rows() -> list[dict]:
    """The structure facts, as plain JSON values (field tables are [name, offset, bytes])."""
    return json.loads(json.dumps(_image_layout_rows()))


def _image_layout_rows() -> list[dict]:
    boot = [("magic", 0, 8), ("version", 40, 4)]
    return [
        {"format": BOOT_FORMAT, "versions": [0, 1, 2], "endian": "little", "header_bytes": [1632, 1648, 1660],
         "fields": boot + [("kernel_size", 8, 4), ("ramdisk_size", 16, 4), ("second_size", 24, 4),
                           ("page_size", 36, 4), ("os_version", 44, 4), ("recovery_dtbo_size", 1632, 4),
                           ("recovery_dtbo_offset", 1636, 8), ("header_size", 1644, 4), ("dtb_size", 1648, 4)],
         "layout": "kernel at one page, then page-aligned ramdisk, second, recovery_dtbo and dtb"},
        {"format": BOOT_FORMAT, "versions": [3, 4], "endian": "little", "header_bytes": [1580, 1584],
         "fields": boot + [("kernel_size", 8, 4), ("ramdisk_size", 12, 4), ("os_version", 16, 4),
                           ("header_size", 20, 4), ("signature_size", 1580, 4)],
         "layout": "page 4096: header page, kernel, ramdisk, then the v4 boot_signature"},
        {"format": VENDOR_FORMAT, "versions": [3, 4], "endian": "little", "header_bytes": [2112, 2128],
         "fields": [("magic", 0, 8), ("version", 8, 4), ("page_size", 12, 4), ("vendor_ramdisk_size", 24, 4),
                    ("header_size", 2096, 4), ("dtb_size", 2100, 4), ("table_size", 2112, 4),
                    ("table_entry_count", 2116, 4), ("table_entry_size", 2120, 4), ("bootconfig_size", 2124, 4)],
         "layout": "header span, vendor ramdisk section, dtb, v4 vendor ramdisk table, v4 bootconfig; each page-aligned",
         "table_entry": {"bytes": 108, "fields": [("ramdisk_size", 0, 4), ("ramdisk_offset", 4, 4),
                                                   ("ramdisk_type", 8, 4), ("name", 12, 32)]}},
        {"format": DT_FORMAT, "versions": [0], "endian": "big", "header_bytes": [32],
         "fields": [("magic", 0, 4), ("total_size", 4, 4), ("header_size", 8, 4), ("dt_entry_size", 12, 4),
                    ("dt_entry_count", 16, 4), ("dt_entries_offset", 20, 4), ("page_size", 24, 4),
                    ("version", 28, 4)],
         "layout": "explicit table offset, explicit payload offsets, no page alignment",
         "table_entry": {"bytes": 32, "fields": [("dt_size", 0, 4), ("dt_offset", 4, 4)]}},
    ]


def image_parser_contract() -> dict:
    c = collect()
    return {
        "version": IMAGE_PARSER_VERSION,
        "independently_versioned": True,
        "profile": IMAGE_PROFILE,
        "operation": R3_ID,
        "commands": ["plan-images", "parse-images", "verify-images"],
        "kinds": {"manifest": IMAGES_KIND, "plan": IMAGE_PLAN_KIND, "parse": IMAGE_PARSE_KIND},
        "transport": IMAGE_TRANSPORT,
        "evidence_level": IMAGE_EVIDENCE_LEVEL,
        "status": IMAGE_PARSE_STATUS,
        "synthetic": True,
        "live": False,
        "executes": False,
        "capture": {
            "operation_kind": c.OPERATION_KIND,
            "transport": c.TRANSPORT,
            "read_domain": c.READ_DOMAIN,
            "operation_schema": c.OPERATION_SCHEMA,
            "collector_transport_label_is_not_provenance": True,
            "validated_by": ["validate_operation", "check_r3_against_r2"],
            "produces": [R3_ID],
            "does_not_produce": list(IMAGE_NOT_PRODUCED),
            "complete_capture": False,
        },
        "inventory": {
            "operand": "a separately validated request-bound R2 operation file",
            "bound_by": "exact bytes (inventory_sha256 in images.json and parse.json)",
            "validated_by": "validate_operation for the R2 request row, before any image byte is read",
            "image_null_means": "absence from the bound R2 inventory, never mere file absence",
        },
        "input": {
            "layout": "flat",
            "manifest": {
                "path": IMAGE_MANIFEST_PATH, "kind": IMAGES_KIND, "format_version": 1,
                "max_bytes": IMAGE_MANIFEST_MAX_BYTES, "json": "strict canonical ASCII",
                "binds": ["bootchain_contract_sha256", "request_sha256", "inventory_sha256"],
                "rows": {"count": len(IMAGE_NAMES), "sorted_by": "partition_name",
                         "fields": ["partition_name", "present", "size_bytes", "fixture_sha256"],
                         "absent": "present false, size_bytes null, fixture_sha256 null, no file",
                         "present_rule": "present true, size_bytes 1..16777216 exact, fixture_sha256 exact, one fixed regular file"},
            },
            "partition_names": list(IMAGE_NAMES),
            "file_name_rule": "partition_name plus .img: derived internally, never an input path",
            "closure": "images.json plus one fixed file per present row: derived from the admitted manifest and checked exactly before any image byte is read",
            "entries_max": IMAGE_LISTING_MAX,
            "safety": list(IMAGE_SAFETY),
            "capture": "pin every closure file, read each once into a bounded immutable buffer, hash and parse those same bytes",
            "snapshot_claim": "descriptor-read snapshot only: not atomic, no writer exclusion",
        },
        "formats": image_layout_rows(),
        "evidence": {
            "metadata_only": True,
            "image_sha256": None,
            "header_sha256": "recomputed from the admitted buffer",
            "table_sha256": "recomputed from the admitted buffer; SHA-256 of empty bytes for an empty table",
            "component_sha256": "null unless the whole component lies inside covered metadata",
            "coverage": "exact header structures plus nonempty tables, adjacent ranges merged, no padding, payload, EOF or full image",
            "full_image_coverage": "refused",
            "rows": "exactly 18 sorted rows, zero-size component slots preserved",
        },
        "accounting": image_accounting_policy(),
        "diagnostics": {
            "codes": dict(IMAGE_CODES),
            "value_free": "fixed categories only: untrusted paths, names, bytes, sizes, hashes, board ids, command lines, addresses and exception text are never echoed",
        },
        "output": {
            "kind": IMAGE_PARSE_KIND,
            "directories": ["operations"],
            "files": list(IMAGE_OUTPUT_FILES),
            "extra_entries": "reject",
            "binary_copies": False,
            "modes": {"directories": "0755", "files": "0644"},
            "checksums": {"path": "SHA256SUMS", "covers": ["parse.json", IMAGE_OPERATION_PATH],
                          "sorted": "canonical-byte-order-of-path"},
            "deterministic": True,
            "published": "atomic-no-replace",
            "verification": "recompute-from-request-inventory-and-images-byte-for-byte",
        },
        "semantic_limits": list(IMAGE_SEMANTIC_LIMITS),
        "limitations": list(IMAGE_LIMITATIONS),
    }


# --- image inputs: the R2 inventory and the flat image fixture ------------------------
# Every diagnostic below is a literal: no path, name, byte, size, hash or exception text of an
# input is ever formatted into it.


def image_input_error(reason: str) -> ImageError:
    return ImageError("image-input-rejected", reason)


def image_unstable(reason: str) -> ImageError:
    return ImageError("image-unstable", reason)


def image_manifest_schema() -> dict:
    c = collect()
    return {
        "fields": {
            "schema": c._int(1, 1), "kind": c._enum([IMAGES_KIND]), "format_version": c._int(1, 1),
            "bootchain_contract_sha256": c._hash(), "request_sha256": c._hash(),
            "inventory_sha256": c._hash(), "synthetic": c._bool(True),
        },
        "rows": c._rows({
            "partition_name": c._enum(IMAGE_NAMES), "present": c._bool(),
            "size_bytes": c._nullable(c._int(1, MAX_IMAGE_BYTES)),
            "fixture_sha256": c._nullable(c._hash()),
        }, len(IMAGE_NAMES), len(IMAGE_NAMES), "partition_name"),
    }


class Inventory:
    def __init__(self, raw, partitions, handle):
        self.raw = raw
        self.sha256 = sha256_hex(raw)
        self.partitions = partitions  # the validated R2 partition rows
        self.sizes = {row["partition_name"]: row["size_bytes"] for row in partitions}
        self.handle = handle


class ImageFixture:
    def __init__(self, manifest_bytes, rows, files, directory_ids):
        self.manifest_bytes = manifest_bytes
        self.sha256 = sha256_hex(manifest_bytes)
        self.rows = rows  # partition_name -> manifest row
        self.files = files  # partition_name -> immutable image bytes, present images only
        self.directory_ids = directory_ids


class ImageInputs:
    def __init__(self, request, request_sha256, request_ids, inventory, fixture):
        self.request = request
        self.request_sha256 = request_sha256
        self.request_ids = request_ids
        self.inventory = inventory
        self.fixture = fixture


def r3_request_row(request: dict) -> dict:
    return next(row for row in request["requested_reads"] if row["id"] == R3_ID)


def read_inventory(path: str, env: Environment, request: dict, request_sha256: str) -> Inventory:
    """One bounded, trusted read of the R2 operation file, validated by the unchanged collector
    against the R2 request row before any image byte is read. The pinned inode stays open for
    a final identity recheck."""
    c, d = collect(), deploy()
    try:
        raw, handle = d.capture_trusted_file(
            path, "R2 inventory", "R2 inventory", request_row(request)["max_output_bytes"]
        )
    except (*d.handled_errors(), OSError):
        raise image_input_error("the R2 inventory failed safe admission") from None
    try:
        if handle.identity[3] & 0o111:
            raise image_input_error("the R2 inventory is executable")
        try:
            document = validate_operation(env, request, request_sha256, raw)
        except (BootchainError, c.CollectError, *d.handled_errors(), RecursionError):
            raise ImageError("image-operation-rejected", "the collector refused the R2 inventory") from None
    except BaseException:
        os.close(handle.pinned)
        raise
    return Inventory(raw, document["data"]["partitions"], handle)


def parse_image_manifest(raw: bytes, env: Environment, request_sha256: str, inventory: Inventory) -> dict:
    c, d = collect(), deploy()
    schema = image_manifest_schema()
    try:
        document = parse_json(raw, "images.json")
        if set(document) != {*schema["fields"], "images"}:
            raise image_input_error("images.json fields differ")
        header = check_fields({key: document[key] for key in schema["fields"]}, schema["fields"], "images.json")
        rows = c.check_rows(schema["rows"], document["images"], "images.json images", "images.json image", {})
    except ImageError:
        raise
    except (BootchainError, *admission_errors(), RecursionError, KeyError, TypeError):
        raise image_input_error("images.json is not the exact canonical manifest") from None
    if header["bootchain_contract_sha256"] != env.contract_sha256 or (
        header["request_sha256"] != request_sha256 or header["inventory_sha256"] != inventory.sha256
    ):
        raise ImageError("image-identity-mismatch", "images.json bindings differ from the contract, request or inventory")
    result = {}
    for row in rows:
        name, present = row["partition_name"], row["present"]
        if present != (row["size_bytes"] is not None) or present != (row["fixture_sha256"] is not None):
            raise image_input_error("images.json presence disagrees with its size and hash")
        if present != (name in inventory.sizes):
            raise ImageError("image-identity-mismatch", "images.json presence differs from the R2 inventory")
        if present and row["size_bytes"] > inventory.sizes[name]:
            raise ImageError("image-identity-mismatch", "an image is larger than its R2 partition")
        result[name] = row
    if [row["partition_name"] for row in rows] != IMAGE_NAMES:
        raise image_input_error("images.json rows differ from the 18 partition names")
    return result


def list_image_names(descriptor: int) -> list[str]:
    names = []
    try:
        with os.scandir(descriptor) as children:
            for child in children:
                names.append(child.name)
                if len(names) > IMAGE_LISTING_MAX:
                    raise image_input_error("the image fixture holds too many entries")
    except OSError:
        raise image_input_error("the image fixture cannot be listed") from None
    return names


def check_image_closure(names: list, closure: list, error) -> None:
    if sorted(names) != closure:
        raise error("the image fixture differs from its exact closure")


def pin_image(directory: int, name: str, root, root_mount: int, low: int, high: int) -> Held:
    """Pin one closure file and judge all of its metadata; no payload byte is read here."""
    d = deploy()
    try:
        pinned, descriptor, opened = d.open_pinned_regular_at(directory, name, "image fixture file")
    except (*d.handled_errors(), OSError):
        raise image_input_error("an image fixture file cannot be opened safely") from None
    item = Held(name, pinned, descriptor, opened)
    try:
        if opened.st_nlink != 1:
            raise image_input_error("an image fixture file has additional hard links")
        if d.untrusted_owner_or_mode(opened):
            raise image_input_error("an image fixture file is writable or controlled by another user")
        if opened.st_mode & 0o111:
            raise image_input_error("an image fixture file is executable")
        if opened.st_dev != root.st_dev:
            raise image_input_error("an image fixture file crosses a device boundary")
        try:
            mount = d.kernel().mount_id_for_fd(pinned, "image fixture file")
        except (*d.handled_errors(), OSError):
            raise image_input_error("an image fixture file mount cannot be determined") from None
        if mount != root_mount:
            raise image_input_error("an image fixture file crosses a mount point")
        if not low <= opened.st_size <= high:
            raise ImageError("image-identity-mismatch", "an image fixture file size differs from its bound")
    except BaseException:
        release([item])
        raise
    return item


def settle_images(directory: int, held: list, root_before: tuple, closure: list) -> None:
    """Directory, listing and every pinned file still match admission: the same repeated
    best-effort passes as the GPT gather. Detection only, never a claim of atomicity."""
    d = deploy()

    def directory_unchanged() -> None:
        check_image_closure(list_image_names(directory), closure, image_unstable)
        if d.fingerprint(os.fstat(directory)) != root_before:
            raise image_unstable("the image fixture directory changed")

    def files_unchanged() -> None:
        for item in held:
            pinned = d.fingerprint(item.opened)
            if d.fingerprint(os.fstat(item.descriptor)) != pinned:
                raise image_unstable("an image fixture file changed")
            try:
                current = os.stat(item.name, dir_fd=directory, follow_symlinks=False)
            except OSError:
                raise image_unstable("an image fixture file was removed") from None
            if d.fingerprint(current) != pinned:
                raise image_unstable("an image fixture file was replaced")

    directory_unchanged()
    files_unchanged()
    directory_unchanged()
    files_unchanged()
    directory_unchanged()


def read_image_pinned(item: Held) -> bytes:
    """Exactly the admitted size from the pinned descriptor, once, into an immutable buffer."""
    d = deploy()
    pinned = d.fingerprint(item.opened)
    if d.fingerprint(os.fstat(item.descriptor)) != pinned:
        raise image_unstable("an image fixture file changed before being read")
    chunks, remaining = [], item.opened.st_size
    while remaining:
        block = os.read(item.descriptor, min(1024 * 1024, remaining))
        if not block:
            raise image_unstable("an image fixture file changed size while being read")
        chunks.append(block)
        remaining -= len(block)
    if os.read(item.descriptor, 1):
        raise image_unstable("an image fixture file grew while being read")
    if d.fingerprint(os.fstat(item.descriptor)) != pinned:
        raise image_unstable("an image fixture file changed while being read")
    return b"".join(chunks)


def read_image_fixture(path: str, env: Environment, request_sha256: str, inventory: Inventory) -> ImageFixture:
    """Admit images.json first (it is JSON, not an image), derive the exact closure from it,
    check the listing against that closure, pin and admit every present image, and only then read
    image bytes: each file once, from its pinned descriptor, into the buffer that is hashed and
    parsed. A mutation first observable during or after traversal can consume bounded bytes and
    is rejected, or, after a file's final observation, yields the already-hashed buffer: the
    source is not claimed current at return."""
    d = deploy()
    try:
        descriptor, identity = d.open_trusted_artifact(path, "image fixture")
    except (*d.handled_errors(), OSError):
        raise image_input_error("the image fixture directory failed safe admission") from None
    held = []
    try:
        root = os.fstat(descriptor)
        if d.untrusted_owner_or_mode(root):
            raise image_input_error("the image fixture directory is writable or controlled by another user")
        try:
            root_mount = d.kernel().mount_id_for_fd(descriptor, "image fixture root")
        except (*d.handled_errors(), OSError):
            raise image_input_error("the image fixture mount cannot be determined") from None
        root_before = d.fingerprint(root)
        names = list_image_names(descriptor)
        if IMAGE_MANIFEST_PATH not in names or any(
            name != IMAGE_MANIFEST_PATH and name not in IMAGE_FILE_NAMES for name in names
        ):
            raise image_input_error("the image fixture differs from its exact closure")
        manifest_item = pin_image(descriptor, IMAGE_MANIFEST_PATH, root, root_mount, 1, IMAGE_MANIFEST_MAX_BYTES)
        held.append(manifest_item)
        manifest_bytes = read_image_pinned(manifest_item)
        rows = parse_image_manifest(manifest_bytes, env, request_sha256, inventory)
        present = [name for name in IMAGE_NAMES if rows[name]["present"]]
        closure = sorted([IMAGE_MANIFEST_PATH, *(image_file_name(name) for name in present)])
        check_image_closure(names, closure, image_input_error)
        if len(manifest_bytes) + sum(rows[name]["size_bytes"] for name in present) > MAX_FIXTURE_INPUT_BYTES:
            raise ImageBudget("the admitted fixture exceeds the per-gather input bound")
        for name in present:
            size = rows[name]["size_bytes"]
            held.append(pin_image(descriptor, image_file_name(name), root, root_mount, size, size))
        settle_images(descriptor, held, root_before, closure)
        files = {}
        for item in held[1:]:
            name = IMAGE_FILE_NAMES[item.name]
            data = read_image_pinned(item)
            if sha256_hex(data) != rows[name]["fixture_sha256"]:
                raise ImageError("image-identity-mismatch", "an image fixture file differs from its manifest hash")
            files[name] = data
        settle_images(descriptor, held, root_before, closure)
    finally:
        release(held)
        os.close(descriptor)
    try:
        d.recheck_trusted_artifact(path, identity, "image fixture")
    except (*d.handled_errors(), OSError):
        raise image_unstable("the image fixture directory changed") from None
    return ImageFixture(manifest_bytes, rows, files, frozenset({(root.st_dev, root.st_ino)}))


def recheck_inventory(path: str, inventory: Inventory) -> None:
    d = deploy()
    try:
        d.recheck_trusted_file(path, inventory.handle, "R2 inventory", "R2 inventory")
    except (*d.handled_errors(), OSError):
        raise image_unstable("the R2 inventory changed") from None


def gather_inventory(args, env: Environment):
    """The request and the validated inventory, with its inode rechecked before it is released."""
    d = deploy()
    for first, second in ((args.request, args.inventory), (args.request, getattr(args, "images", None)),
                          (args.inventory, getattr(args, "images", None))):
        if second is not None and d.paths_overlap(first, second):
            raise image_input_error("an input path overlaps another input")
    request, request_sha256, request_ids = read_request(args.request, env)
    return request, request_sha256, request_ids, read_inventory(args.inventory, env, request, request_sha256)


def gather_images(args, env: Environment) -> ImageInputs:
    request, request_sha256, request_ids, inventory = gather_inventory(args, env)
    try:
        fixture = read_image_fixture(args.images, env, request_sha256, inventory)
        recheck_inventory(args.inventory, inventory)
    finally:
        os.close(inventory.handle.pinned)
    if request_ids & fixture.directory_ids or inventory.handle.parent_identity in (
        request_ids | fixture.directory_ids
    ):
        raise image_input_error("an input aliases another input tree")
    return ImageInputs(request, request_sha256, request_ids, inventory, fixture)


# --- R3 operation ---------------------------------------------------------------


def image_result(inputs: ImageInputs) -> dict:
    fixture = inputs.fixture
    rows, represented = [], 0
    for name in IMAGE_NAMES:
        image = None
        if fixture.rows[name]["present"]:
            image = image_summary(name, fixture.files[name])
            represented += image["coverage"]["covered_bytes"]
        rows.append({"partition_name": name, "role": role_of_name(name), "image": image})
    if represented > MAX_REPRESENTED_METADATA_BYTES:
        raise ImageBudget("represented metadata coverage exceeds its bound")
    image_bytes = sum(len(data) for data in fixture.files.values())
    payload = len(fixture.manifest_bytes) + image_bytes
    if payload > MAX_FIXTURE_INPUT_BYTES:
        raise ImageBudget("the admitted fixture exceeds the per-gather input bound")
    return {
        "data": {"images": rows}, "bytes_read": payload, "represented_metadata_bytes": represented,
        "image_hash_bytes": image_bytes,
    }


def validate_r3_operation(env: Environment, request: dict, request_sha256: str, raw: bytes,
                          partitions: list) -> dict:
    """The unchanged collector validates the R3 operation and its cross-check against the bound R2 rows."""
    c, d = collect(), deploy()
    if len(raw) > MAX_OUTPUT_METADATA_BYTES:
        raise ImageBudget("the R3 operation exceeds the image parser's output bound")
    try:
        document, _outcome = c.validate_operation(raw, r3_request_row(request), request_sha256, env.identity)
        c.check_r3_against_r2(
            document["data"]["images"], partitions, c.policy_registry()["operations"][R3_ID]
        )
    except (BootchainError, c.CollectError, *d.handled_errors(), RecursionError):
        raise ImageError("image-operation-rejected", "the collector refused the R3 operation") from None
    return document


def image_input_rows(fixture: ImageFixture) -> list[dict]:
    rows = [{"path": IMAGE_MANIFEST_PATH, "role": "images-manifest", "bytes": len(fixture.manifest_bytes),
             "sha256": fixture.sha256}]
    for name in IMAGE_NAMES:
        if name in fixture.files:
            rows.append({"path": image_file_name(name), "role": "image-fixture",
                         "bytes": len(fixture.files[name]), "sha256": sha256_hex(fixture.files[name])})
    return sorted(rows, key=lambda row: row["path"].encode())


def image_accounting(result: dict, operation: bytes) -> dict:
    return {
        "scope": IMAGE_ACCOUNTING_SCOPE,
        "fixture_payload_bytes": result["bytes_read"],
        "fixture_payload_read_bytes": result["bytes_read"],
        "fixture_image_hash_bytes": result["image_hash_bytes"],
        "represented_metadata_bytes": result["represented_metadata_bytes"],
        "operation_output_bytes": len(operation),
        "hardware_bytes_read": 0,
        "hardware_transport": "none",
        "full_image_evidence": False,
        "definitions": image_accounting_policy(),
    }


def image_parse_document(env: Environment, inputs: ImageInputs, result: dict, operation: bytes) -> dict:
    row = r3_request_row(inputs.request)
    fixture = inputs.fixture
    images = result["data"]["images"]
    return {
        "schema": 1,
        "kind": IMAGE_PARSE_KIND,
        "format_version": VERSION,
        "image_parser_version": IMAGE_PARSER_VERSION,
        "bootchain_contract_sha256": env.contract_sha256,
        "capture_contract_sha256": env.collector.contract_sha256,
        "preflight_contract_sha256": env.collector.preflight_sha256,
        "request_sha256": inputs.request_sha256,
        "inventory_sha256": inputs.inventory.sha256,
        "images_sha256": fixture.sha256,
        "implementation": implementation_binding(),
        "dependencies": {
            "trust": DEPENDENCY_TRUST, "byte_pinned": False, "pinned_versions": dict(PINNED_VERSIONS),
        },
        "profile": IMAGE_PROFILE,
        "provenance": {
            "kind": "synthetic-parser-provenance", "captured": False, "hardware_qualified": False,
            "collector_labels_are_not_provenance": True,
        },
        "transport": IMAGE_TRANSPORT,
        "evidence_level": IMAGE_EVIDENCE_LEVEL,
        "status": IMAGE_PARSE_STATUS,
        "synthetic": True,
        "live": False,
        "executes": False,
        "kit_snapshot_reverified": False,
        "remote_commands": [],
        "human_approval_required": True,
        "complete_capture": False,
        "inputs": image_input_rows(fixture),
        "operation": {
            "id": R3_ID,
            "path": IMAGE_OPERATION_PATH,
            "bytes": len(operation),
            "sha256": sha256_hex(operation),
            "bytes_read": result["bytes_read"],
            **{key: row[key] for key in collect().BUDGET_KEYS},
            "max_output_metadata_bytes": MAX_OUTPUT_METADATA_BYTES,
            "image_count": sum(1 for item in images if item["image"] is not None),
            "absent_count": sum(1 for item in images if item["image"] is None),
            "collector_transport": collect().TRANSPORT,
            "read_domain": collect().READ_DOMAIN,
        },
        "accounting": image_accounting(result, operation),
        "semantic_limits": list(IMAGE_SEMANTIC_LIMITS),
        "unresolved_claims": unresolved_claims(),
        "deferred": deferred_rows(),
        "qualification": qualification(),
        "limitations": list(IMAGE_LIMITATIONS),
        "non_goals": list(NON_GOALS),
        "blockers": blocker_rows(),
        "authority": authority(),
    }


def image_parse_spec(env: Environment, inputs: ImageInputs, result: dict | None = None) -> list:
    d = deploy()
    result = image_result(inputs) if result is None else result
    operation = d.render_json(operation_document(inputs.request_sha256, result, R3_ID))
    validate_r3_operation(env, inputs.request, inputs.request_sha256, operation, inputs.inventory.partitions)
    files = {
        "parse.json": d.render_json(image_parse_document(env, inputs, result, operation)),
        IMAGE_OPERATION_PATH: operation,
    }
    files["SHA256SUMS"] = sums_of(files)
    if sorted(files) != IMAGE_OUTPUT_FILES:
        raise ImageError("image-operation-rejected", "the image parse output closure differs from the contract")
    spec = [("operations", "dir", 0o755, None)]
    spec += [(path, "file", 0o644, data) for path, data in files.items()]
    spec.sort(key=lambda item: item[0].encode("utf-8"))
    return spec


def image_result_summary(status: str, inputs: ImageInputs, spec: list) -> dict:
    d = deploy()
    operation = spec_file(spec, IMAGE_OPERATION_PATH)
    document = json.loads(operation)
    parse = json.loads(spec_file(spec, "parse.json"))
    accounting = parse["accounting"]
    return {
        "status": status,
        "evidence_level": IMAGE_EVIDENCE_LEVEL,
        "profile": IMAGE_PROFILE,
        "operation": R3_ID,
        "parse_sha256": d.sha256_bytes(spec_file(spec, "SHA256SUMS")),
        "operation_sha256": d.sha256_bytes(operation),
        "request_sha256": inputs.request_sha256,
        "inventory_sha256": inputs.inventory.sha256,
        "images_sha256": inputs.fixture.sha256,
        "bytes_read": document["bytes_read"],
        "represented_metadata_bytes": accounting["represented_metadata_bytes"],
        "operation_output_bytes": accounting["operation_output_bytes"],
        "hardware_bytes_read": 0,
        "image_count": parse["operation"]["image_count"],
        "blocker_count": len(d.BLOCKERS),
        "synthetic": True,
        "live": False,
        "executes": False,
        "kit_snapshot_reverified": False,
        "complete_capture": False,
        **authority(),
    }


def image_plan_document(env: Environment, request: dict, request_sha256: str, inventory: Inventory) -> dict:
    d = deploy()
    row = r3_request_row(request)
    expected = [name for name in IMAGE_NAMES if name in inventory.sizes]
    return {
        "schema": 1,
        "kind": IMAGE_PLAN_KIND,
        "format_version": VERSION,
        "image_parser_version": IMAGE_PARSER_VERSION,
        "bootchain_contract_sha256": env.contract_sha256,
        "request_sha256": request_sha256,
        "inventory_sha256": inventory.sha256,
        "request_binding": {
            "operation": R3_ID,
            **{key: row[key] for key in collect().BUDGET_KEYS},
            "max_output_metadata_bytes": MAX_OUTPUT_METADATA_BYTES,
            "emits": list(row["emits"]),
            "never_emits": list(row["never_emits"]),
            "request_sha256_is": "sha256-of-the-verified-request-SHA256SUMS-bytes",
        },
        "expected_images": {
            "present": expected,
            "absent": [name for name in IMAGE_NAMES if name not in inventory.sizes],
            "files": [IMAGE_MANIFEST_PATH, *(image_file_name(name) for name in expected)],
            "note": "the fixture must hold exactly images.json and one fixed file per present row",
        },
        "transport": IMAGE_TRANSPORT,
        "evidence_level": IMAGE_EVIDENCE_LEVEL,
        "implementation": implementation_binding(),
        "synthetic": True,
        "live": False,
        "executes": False,
        "kit_snapshot_reverified": False,
        "remote_commands": [],
        "complete_capture": False,
        "image_parser": image_parser_contract(),
        "output_closure": image_parser_contract()["output"],
        "qualification": qualification(),
        "unresolved_claims": unresolved_claims(),
        "deferred": deferred_rows(),
        "non_goals": list(NON_GOALS),
        "human_approval_required": True,
        "blockers": list(d.BLOCKERS),
        "authority": authority(),
    }


def revalidate_image_tree(tree, env: Environment, inputs: ImageInputs, label: str) -> None:
    validate_r3_operation(env, inputs.request, inputs.request_sha256, tree.data[IMAGE_OPERATION_PATH],
                          inputs.inventory.partitions)


def command_plan_images(env: Environment, args) -> dict:
    request, request_sha256, _ids, inventory = gather_inventory(args, env)
    try:
        recheck_inventory(args.inventory, inventory)
    finally:
        os.close(inventory.handle.pinned)
    return image_plan_document(env, request, request_sha256, inventory)


def command_parse_images(env: Environment, args) -> dict:
    d = deploy()
    for path in (args.request, args.inventory, args.images):
        if d.paths_overlap(args.out, path):
            raise image_input_error("the output path overlaps an input")
    inputs = gather_images(args, env)
    spec = image_parse_spec(env, inputs)
    expected = d.spec_entries(spec)
    protected = [args.request, args.inventory, args.images]
    protected_ids = frozenset(inputs.request_ids | inputs.fixture.directory_ids)

    def verify_built(_temporary_path: str, descriptor: int) -> None:
        again = gather_images(args, env)
        if image_parse_spec(env, again) != spec:
            raise image_unstable("the request, inventory or images changed during the parse")
        tree = walk_output(descriptor, "parse", keep_data=True)
        diff_output(tree.entries, expected, "parse")
        revalidate_image_tree(tree, env, again, "built")

    try:
        d.publish(args.out, protected, protected_ids, spec, verify_built)
    except d.handled_errors():
        raise ImageError("publish-rejected", "the image parse could not be published safely") from None
    return image_result_summary("parsed", inputs, spec)


def command_verify_images(env: Environment, args) -> dict:
    d = deploy()
    if any(d.paths_overlap(args.parse, path) for path in (args.request, args.inventory, args.images)):
        raise image_input_error("the parse overlaps an input")
    inputs = gather_images(args, env)
    spec = image_parse_spec(env, inputs)
    try:
        descriptor, identity = d.open_trusted_artifact(args.parse, "parse")
    except (*d.handled_errors(), OSError):
        raise image_input_error("the parse artifact failed safe admission") from None
    try:
        tree = walk_output(descriptor, "parse", keep_data=True, trusted_ownership=True)
    finally:
        os.close(descriptor)
    diff_output(tree.entries, d.spec_entries(spec), "parse")
    if tree.directory_ids & (inputs.request_ids | inputs.fixture.directory_ids):
        raise image_input_error("the parse aliases an input tree")
    revalidate_image_tree(tree, env, inputs, "parsed")
    try:
        d.recheck_trusted_artifact(args.parse, identity, "parse")
    except (*d.handled_errors(), OSError):
        raise image_unstable("the parse artifact changed during verification") from None
    again = gather_images(args, env)
    if image_parse_spec(env, again) != spec:
        raise image_unstable("the request, inventory or images changed during verification")
    return image_result_summary("verified", inputs, spec)


# --- R4 synthetic selection mechanism (selection parser contract 1.0.0) -------------------
# The same exact R3 image fixture bytes that the R3 parser admitted are reparsed here: the
# flattened device tree (FDT) blobs of one fixed base partition's dtb component are counted and
# validated, and the entries of one DT table are counted. A synthetic witness holds either no
# claim or one (dtb index, DT table entry index) pair; the pair is checked for membership in the
# parsed sets and for binding only. The R4 operation this emits ALWAYS carries a null selected
# board id, a null selected board revision and a null selection source: nothing here can
# establish which board a real device selects, from where, or how fresh that is. Which source
# and semantics a real Myron uses is the recorded hardware-witness successor gate
# (r4-selection-source-qualification).
#
# Accounting (per complete gather; verification and publication re-gather separately):
#   S = complete R3 fixture bytes (images.json plus every present image) + selection.json
#       + witness.json: the R4 operation's bytes_read
#   M = per image, the union of the reused R3 metadata coverage and (for the one base image)
#       the complete parsed base-DTB component range, overlap counted once, summed
#   O = canonical serialized R4 operation bytes, newline included
# The request tree, the R2 inventory and the R3 parse artifact are dependency reads, reported
# separately and never part of S.

SELECTION_PARSER_VERSION = "1.0.0"
SELECTION_KIND = "myron-synthetic-r4-selection"
WITNESS_KIND = "myron-synthetic-r4-witness"
SELECTION_PLAN_KIND = "myron-synthetic-r4-selection-parse-plan"
SELECTION_PARSE_KIND = "myron-synthetic-r4-selection-parse"
SELECTION_PROFILE = "r4-synthetic-fdt-v17-dt-table-v0-index-membership-only"
SELECTION_TRANSPORT = "synthetic-binary-selection-fixture"
SELECTION_EVIDENCE_LEVEL = "synthetic-binary-selection-count-and-index-membership-only"
SELECTION_PARSE_STATUS = "synthetic-r4-parse-recorded"
SELECTION_ACCOUNTING_SCOPE = "one-admitted-fixture-snapshot"
SELECTION_MANIFEST_PATH = "selection.json"
WITNESS_PATH = "witness.json"
SELECTION_CLOSURE = sorted([SELECTION_MANIFEST_PATH, WITNESS_PATH])
SELECTION_LISTING_MAX = len(SELECTION_CLOSURE) + 1  # the closure and one entry past it
SELECTION_MANIFEST_MAX_BYTES = 8192
WITNESS_MAX_BYTES = 4096
SELECTION_OPERATION_PATH = f"operations/{R4_ID}.json"
SELECTION_OUTPUT_FILES = sorted(["SHA256SUMS", "parse.json", SELECTION_OPERATION_PATH])
SELECTION_MAX_FIXTURE_INPUT_BYTES = MAX_FIXTURE_INPUT_BYTES + SELECTION_MANIFEST_MAX_BYTES + WITNESS_MAX_BYTES
SELECTION_MAX_REPRESENTED_METADATA_BYTES = 65536  # M: the collector's max_hardware_read_bytes for R4
SELECTION_MAX_OPERATION_BYTES = 65536  # O: the collector's max_output_bytes for R4
SELECTION_MAX_PARSE_BYTES = 131072
SELECTION_MAX_SUMS_BYTES = 1024
SELECTION_MAX_OUTPUT_BYTES = SELECTION_MAX_PARSE_BYTES + SELECTION_MAX_OPERATION_BYTES + SELECTION_MAX_SUMS_BYTES
BASE_ROLES = ("boot", "recovery", "vendor_boot", "vendor_kernel_boot")
BASE_SOURCES = sorted(role + suffix for role in BASE_ROLES for suffix in IMAGE_SUFFIXES)
DTBO_SOURCES = sorted("dtbo" + suffix for suffix in IMAGE_SUFFIXES)
FDT_MAGIC = 0xD00DFEED
FDT_HEADER = 40
FDT_VERSION = 17
FDT_LAST_COMP_VERSION = 16
FDT_BEGIN_NODE, FDT_END_NODE, FDT_PROP, FDT_NOP, FDT_END = 1, 2, 3, 4, 9
MAX_FDT_BLOBS = 64
MAX_FDT_DEPTH = 64
MAX_FDT_NODES = 4096
MAX_FDT_PROPERTIES = 8192
MAX_FDT_NAME_BYTES = 128
MAX_COMPATIBLE_TOKENS = 16
MAX_COMPATIBLE_TOKEN_BYTES = 64
MAX_WITNESS_DTB_INDEX = MAX_FDT_BLOBS - 1
MAX_WITNESS_DTBO_INDEX = MAX_DT_ENTRIES - 1
DT_ENTRY_ID_OFFSET, DT_ENTRY_REVISION_OFFSET = 8, 12
FDT_NODE_NAME_BYTES = frozenset(b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789,._+-@")
FDT_PROPERTY_NAME_BYTES = frozenset(b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789,._+*#?-")
SELECTION_CODES = {
    "selection-input-rejected": "the selection fixture, an input path or a dependency artifact failed safe admission",
    "selection-binding-mismatch": "the selection fixture, witness or R3 parse disagrees with its bindings or the exact R3 fixture",
    "selection-unstable": "an input changed while it was admitted or read",
    "selection-corrupt": "the device tree or DT table bytes are internally inconsistent",
    "selection-unsupported": "the bytes may be valid but lie outside the supported selection profile",
    "selection-budget": "a count, size or accounting bound was exceeded",
    "selection-witness-rejected": "the witness is malformed or its claim is not a member of the parsed sets",
    "selection-operation-rejected": "the collector or this parser refused the produced R4 operation",
    "publish-rejected": "the output could not be published safely",
}
SELECTION_NOT_PRODUCED = [
    "R1-identity-and-slot", R2_ID, R3_ID, "R5-module-load-order", "R6-storage-and-mount-model",
    "R7-kernel-identity-revalidation",
]
SELECTION_SAFETY = IMAGE_SAFETY + ["exact-r3-fixture-reparse", "witness-hashed-one-way"]
SELECTION_NOT_ESTABLISHED = [
    "actual-selected-board-id", "actual-selected-board-revision", "actual-selection-source",
    "selection-provenance", "selection-freshness", "selection-source-semantics",
    "board-semantics", "multi-overlay-ordering",
]
SELECTION_SEMANTIC_LIMITS = [
    "dtb_count and dtbo_entry_count are counts parsed from the admitted synthetic bytes: FDT blobs in the one chosen base partition's dtb component and entries of the one chosen DT table",
    "selected_board_id, selected_board_revision and selection_source are always null: no actual selection, source, provenance or freshness is established",
    "the witness indexes are unverified synthetic claims: membership is a computed check that the claimed indexes lie inside the parsed sets and that the claimed base candidate carries the exact contract compatible token",
    "a decoded DT table entry id and revision appear only in the parse sidecar as the claimed entry's raw big-endian words: never an operation field and never a selected board",
    "no selection is inferred from an id, a singleton, the highest revision or entry 0; duplicate ids and revisions are valid",
    "DT table custom words are opaque and a DTBO payload is never parsed as a device tree",
    "the root compatible check matches one exact token and implies no board, SoC variant or boot behavior",
    "one base source and one overlay index only: no multi-overlay ordering, no live merged tree and no complete-device claim",
    "bootconfig is not parsed: an extra bootconfig.txt is refused and no androidboot key or board semantics are interpreted",
    "the matching slot suffix of the two source partitions is a synthetic profile restriction, not an active-slot claim",
]
SELECTION_LIMITATIONS = [
    "synthetic binary parser qualification only: the fixture bytes were never read from a phone or a block device and carry no captured provenance",
    "the mechanism establishes counts and index membership only: it never produces a selected board id, revision or selection source, and closes no hardware-witness gate",
    "hardware discovery may reveal another source or format: this is the final planned synthetic gate, not guaranteed final parser work",
    "one base DTB partition (boot, recovery, vendor_boot or vendor_kernel_boot, with a boot v2 or a vendor_boot dtb component) and one dtbo partition with the same slot suffix; no active-slot claim",
    "FDT v17 with last_comp_version 16 only, at most 64 tightly concatenated blobs, depth 64, 4096 nodes, 8192 properties, 128-byte names and a 1..16 token root compatible list; other valid variants are refused as unsupported, numeric overruns as budget, malformed bytes as corrupt",
    "an empty dtb component and a dtb component without a root compatible are refused as unsupported: the parser never invents a candidate",
    "DT table v0 with the R3 layout rules; a table with more than 256 entries is refused by the shared R3 admission under its image-budget code before any R4 code runs",
    "the R3 fixture is reparsed and the R3 artifact recomputed from the exact admitted buffers; the R3 artifact's metadata hashes alone would not bind the payload and are never trusted without that recomputation",
    "operation bytes_read is S and is fixture payload accounting, no device I/O; the request, R2 inventory and R3 artifact dependency reads are reported separately",
    "each complete gather admits at most 64 MiB plus 12 KiB (S): parse-selection gathers three times (admission, temporary and published verification) and verify-selection twice, so total invocation I/O exceeds S",
    "each gather is an internally validated descriptor-read snapshot of the exact bytes consumed, not an atomic filesystem snapshot and not writer exclusion; a later verify against a changed source rejects",
    "the collector, preflight, snapshot and deployment imports are trusted version-pinned dependencies, not fully byte-pinned execution",
    "publication is durable only if the output parent's fsync succeeds; a failure there removes the just-published output by identity on a best-effort basis",
]


class SelectionError(BootchainError):
    """A fixed-category refusal. The reason is a literal written in this file, never input."""

    def __init__(self, code: str, reason: str):
        super().__init__(reason)
        self.code = code

    def __str__(self) -> str:
        return f"{self.args[0]} (code {self.code})"


def selection_input_error(reason: str) -> SelectionError:
    return SelectionError("selection-input-rejected", reason)


def selection_unstable(reason: str) -> SelectionError:
    return SelectionError("selection-unstable", reason)


def selection_binding(reason: str) -> SelectionError:
    return SelectionError("selection-binding-mismatch", reason)


def selection_corrupt(reason: str) -> SelectionError:
    return SelectionError("selection-corrupt", reason)


def selection_unsupported(reason: str) -> SelectionError:
    return SelectionError("selection-unsupported", reason)


def selection_budget(reason: str) -> SelectionError:
    return SelectionError("selection-budget", reason)


def selection_witness_rejected(reason: str) -> SelectionError:
    return SelectionError("selection-witness-rejected", reason)


def selection_operation_rejected(reason: str) -> SelectionError:
    return SelectionError("selection-operation-rejected", reason)


def suffix_of(name: str) -> str:
    return name[-2:] if name.endswith(("_a", "_b")) else ""


# --- flattened device tree -------------------------------------------------------------


def fdt_u32(data: bytes, offset: int, end: int) -> int:
    if offset < 0 or offset + 4 > end:
        raise selection_corrupt("a device tree field lies outside its block")
    return int.from_bytes(data[offset:offset + 4], "big")


def fdt_padded(length: int) -> int:
    return (length + 3) // 4 * 4


def fdt_node_name_ok(name: bytes) -> bool:
    return (bool(name) and name[0] != ord("@") and name[-1] != ord("@") and name.count(b"@") <= 1
            and all(byte in FDT_NODE_NAME_BYTES for byte in name))


def fdt_property_name_ok(name: bytes) -> bool:
    return bool(name) and all(byte in FDT_PROPERTY_NAME_BYTES for byte in name)


def compatible_tokens(raw: bytes) -> list[bytes]:
    """A root compatible property is a NUL-terminated stringlist of 1..16 printable ASCII tokens of
    1..64 bytes. Malformed shapes are corrupt; the numeric limits are budget refusals."""
    if not raw or raw[-1] != 0:
        raise selection_corrupt("the root compatible is not a NUL-terminated string list")
    tokens = raw[:-1].split(b"\0")
    if len(tokens) > MAX_COMPATIBLE_TOKENS:
        raise selection_budget("the root compatible holds more tokens than the profile allows")
    for token in tokens:
        if not token:
            raise selection_corrupt("the root compatible holds an empty token")
        if len(token) > MAX_COMPATIBLE_TOKEN_BYTES:
            raise selection_budget("a root compatible token is longer than the profile allows")
        if not all(0x20 <= byte <= 0x7E for byte in token):
            raise selection_corrupt("a root compatible token is not printable ASCII")
    return tokens


def parse_fdt_blob(component: bytes, base: int) -> dict:
    """One v17 blob that starts exactly at BASE. Every offset in its header is blob-relative."""
    available = len(component) - base
    if available < FDT_HEADER:
        raise selection_corrupt("a device tree blob is shorter than its header")
    end = len(component)
    (magic, total, off_struct, off_strings, off_reserve, version, last_comp, _cpu, size_strings,
     size_struct) = (fdt_u32(component, base + 4 * index, end) for index in range(10))
    if magic != FDT_MAGIC:
        raise selection_corrupt("a device tree blob magic differs")
    if total < FDT_HEADER or total > available:
        raise selection_corrupt("a device tree blob total size does not fit its component")
    if last_comp > version:
        raise selection_corrupt("a device tree blob last_comp_version exceeds its version")
    if version != FDT_VERSION or last_comp != FDT_LAST_COMP_VERSION:
        raise selection_unsupported("a device tree blob version lies outside the supported profile")
    if off_struct % 4 or size_struct % 4 or off_reserve % 8:
        raise selection_corrupt("a device tree block is misaligned")
    if off_struct < FDT_HEADER or off_strings < FDT_HEADER or off_reserve < FDT_HEADER:
        raise selection_corrupt("a device tree block overlaps the header")
    if off_struct + size_struct > total or off_strings + size_strings > total:
        raise selection_corrupt("a device tree block runs past the blob")
    if size_struct < 16:
        raise selection_corrupt("the structure block is too short for a root node")
    position = off_reserve
    reservations = []
    while True:
        if position + 16 > total:
            raise selection_corrupt("the reserve map has no terminator within the blob")
        address = int.from_bytes(component[base + position:base + position + 8], "big")
        size = int.from_bytes(component[base + position + 8:base + position + 16], "big")
        if address == 0 and size == 0:
            break
        if size:
            reserved_end = address + size
            if reserved_end > 1 << 64:
                raise selection_corrupt("a memory reservation runs past the address space")
            reservations.append((address, reserved_end))
        position += 16
    reservations.sort()
    for previous, current in zip(reservations, reservations[1:]):
        if current[0] < previous[1]:
            raise selection_corrupt("memory reservations overlap")
    blocks = [(0, FDT_HEADER), (off_reserve, position + 16), (off_struct, off_struct + size_struct)]
    if size_strings:
        blocks.append((off_strings, off_strings + size_strings))
    blocks.sort()
    cursor = 0
    for start, stop in blocks:
        if start < cursor:
            raise selection_corrupt("device tree blocks overlap")
        if any(component[base + cursor:base + start]):
            raise selection_corrupt("a device tree gap holds nonzero bytes")
        cursor = stop
    if cursor > total or any(component[base + cursor:base + total]):
        raise selection_corrupt("a device tree blob has nonzero bytes after its last block")
    strings_start, strings_end = base + off_strings, base + off_strings + size_strings
    pointer, stop = base + off_struct, base + off_struct + size_struct
    depth = nodes = properties = deepest = 0
    child_sections = []
    property_names = []
    child_names = []
    saw_root = False
    root_compatible = None
    while True:
        if pointer + 4 > stop:
            raise selection_corrupt("the structure block ends without FDT_END")
        token = fdt_u32(component, pointer, stop)
        pointer += 4
        if token == FDT_BEGIN_NODE:
            if depth == 0 and saw_root:
                raise selection_corrupt("the structure block holds a second root node")
            nul = component.find(b"\0", pointer, stop)
            if nul < 0:
                raise selection_corrupt("a node name has no terminator inside the structure block")
            name = component[pointer:nul]
            if len(name) > MAX_FDT_NAME_BYTES:
                raise selection_budget("a node name is longer than the profile allows")
            if depth == 0 and name:
                raise selection_corrupt("the root node name is not empty")
            if depth > 0 and not fdt_node_name_ok(name):
                raise selection_corrupt("a node name is empty or holds an unsupported byte")
            if depth:
                if name in child_names[-1]:
                    raise selection_corrupt("a node repeats a sibling name")
                child_names[-1].add(name)
                child_sections[-1] = True
            following = pointer + fdt_padded(len(name) + 1)
            if following > stop or any(component[nul + 1:following]):
                raise selection_corrupt("a node name padding is not zero or runs past the structure block")
            pointer = following
            saw_root = True
            depth += 1
            child_sections.append(False)
            property_names.append(set())
            child_names.append(set())
            nodes += 1
            deepest = max(deepest, depth)
            if nodes > MAX_FDT_NODES:
                raise selection_budget("the blob holds more nodes than the profile allows")
            if depth > MAX_FDT_DEPTH:
                raise selection_budget("the blob nests deeper than the profile allows")
        elif token == FDT_END_NODE:
            if depth == 0:
                raise selection_corrupt("the structure block closes a node it never opened")
            depth -= 1
            child_sections.pop()
            property_names.pop()
            child_names.pop()
        elif token == FDT_PROP:
            if depth == 0:
                raise selection_corrupt("the structure block holds a property outside a node")
            if child_sections[-1]:
                raise selection_corrupt("a node property appears after its child nodes")
            if pointer + 8 > stop:
                raise selection_corrupt("a property header runs past the structure block")
            length, name_offset = fdt_u32(component, pointer, stop), fdt_u32(component, pointer + 4, stop)
            pointer += 8
            if length > stop - pointer:
                raise selection_corrupt("a property value runs past the structure block")
            data_start = pointer
            following = pointer + fdt_padded(length)
            if following > stop or any(component[data_start + length:following]):
                raise selection_corrupt("a property padding is not zero or runs past the structure block")
            pointer = following
            properties += 1
            if properties > MAX_FDT_PROPERTIES:
                raise selection_budget("the blob holds more properties than the profile allows")
            if name_offset >= size_strings:
                raise selection_corrupt("a property name lies outside the strings block")
            nul = component.find(b"\0", strings_start + name_offset, strings_end)
            if nul < 0:
                raise selection_corrupt("a property name has no terminator inside the strings block")
            property_name = component[strings_start + name_offset:nul]
            if len(property_name) > MAX_FDT_NAME_BYTES:
                raise selection_budget("a property name is longer than the profile allows")
            if not fdt_property_name_ok(property_name):
                raise selection_corrupt("a property name is empty or holds an unsupported byte")
            if property_name in property_names[-1]:
                raise selection_corrupt("a node repeats a property name")
            property_names[-1].add(property_name)
            if depth == 1 and property_name == b"compatible":
                if root_compatible is not None:
                    raise selection_corrupt("the root node repeats its compatible property")
                root_compatible = component[data_start:data_start + length]
        elif token == FDT_NOP:
            continue
        elif token == FDT_END:
            if depth != 0 or not saw_root:
                raise selection_corrupt("the structure block ends unbalanced or without a root node")
            break
        else:
            raise selection_corrupt("the structure block holds an unknown token")
    if pointer != stop:
        raise selection_corrupt("the structure block holds bytes after FDT_END")
    if root_compatible is None:
        raise selection_unsupported("a device tree blob has no root compatible property")
    return {
        "bytes": total, "nodes": nodes, "properties": properties, "max_depth": deepest,
        "compatible": compatible_tokens(root_compatible),
    }


def parse_fdt_component(component: bytes) -> list[dict]:
    """Exactly one blob or tightly concatenated blobs covering the whole component: no scan for a
    magic, no gap between blobs and no trailing byte."""
    blobs, position = [], 0
    while position < len(component):
        if len(blobs) >= MAX_FDT_BLOBS:
            raise selection_budget("the dtb component holds more blobs than the profile allows")
        blob = parse_fdt_blob(component, position)
        blob["offset"] = position
        blobs.append(blob)
        position += blob["bytes"]
    if not blobs:
        raise selection_unsupported("an empty dtb component carries no device tree blob")
    return blobs


# --- selection manifest and witness ----------------------------------------------------


def selection_manifest_schema() -> dict:
    c = collect()
    return {
        "fields": {
            "schema": c._int(1, 1), "kind": c._enum([SELECTION_KIND]), "format_version": c._int(1, 1),
            "bootchain_contract_sha256": c._hash(), "request_sha256": c._hash(),
            "inventory_sha256": c._hash(), "r3_parse_sha256": c._hash(),
            "r3_operation_sha256": c._hash(), "images_sha256": c._hash(),
            "base_source_partition": c._enum(BASE_SOURCES), "dtbo_source_partition": c._enum(DTBO_SOURCES),
            "witness_bytes": c._int(1, WITNESS_MAX_BYTES), "witness_sha256": c._hash(),
            "synthetic": c._bool(True),
        },
    }


def witness_schema() -> dict:
    c = collect()
    return {
        "fields": {
            "schema": c._int(1, 1), "kind": c._enum([WITNESS_KIND]), "format_version": c._int(1, 1),
            "request_sha256": c._hash(), "r3_operation_sha256": c._hash(),
            "base_source_partition": c._enum(BASE_SOURCES), "dtbo_source_partition": c._enum(DTBO_SOURCES),
            "synthetic": c._bool(True),
            "claim": c._nullable(c._object({
                "dtb_index": c._int(0, MAX_WITNESS_DTB_INDEX),
                "dtbo_entry_index": c._int(0, MAX_WITNESS_DTBO_INDEX),
            })),
        },
    }


def check_selection_scope(base: str, dtbo: str) -> None:
    if suffix_of(base) != suffix_of(dtbo):
        raise selection_unsupported("the base and dtbo source partitions do not share one slot suffix")


def parse_selection_manifest(raw: bytes) -> dict:
    schema = selection_manifest_schema()
    try:
        document = parse_json(raw, "selection.json")
        values = check_fields(document, schema["fields"], "selection.json")
    except (BootchainError, *admission_errors(), RecursionError, KeyError, TypeError):
        raise selection_input_error("selection.json is not the exact canonical manifest") from None
    check_selection_scope(values["base_source_partition"], values["dtbo_source_partition"])
    return values


def parse_witness(raw: bytes) -> dict:
    schema = witness_schema()
    try:
        document = parse_json(raw, "witness.json")
        values = check_fields(document, schema["fields"], "witness.json")
    except (BootchainError, *admission_errors(), RecursionError, KeyError, TypeError):
        raise selection_witness_rejected("witness.json is not the exact canonical witness") from None
    check_selection_scope(values["base_source_partition"], values["dtbo_source_partition"])
    return values


# --- the selection fixture directory (selection.json and witness.json only) ------------


class SelectionFixture:
    def __init__(self, manifest_bytes, witness_bytes, directory_ids):
        self.manifest_bytes = manifest_bytes
        self.witness_bytes = witness_bytes
        self.directory_ids = directory_ids
        self.manifest_sha256 = sha256_hex(manifest_bytes)
        self.witness_sha256 = sha256_hex(witness_bytes)


def list_selection_names(descriptor: int) -> list[str]:
    names = []
    try:
        with os.scandir(descriptor) as children:
            for child in children:
                names.append(child.name)
                if len(names) > SELECTION_LISTING_MAX:
                    raise selection_input_error("the selection fixture holds too many entries")
    except OSError:
        raise selection_input_error("the selection fixture cannot be listed") from None
    return names


def check_selection_closure(names: list, error) -> None:
    if sorted(names) != SELECTION_CLOSURE:
        raise error("the selection fixture differs from its exact closure")


def pin_selection_file(directory: int, name: str, root, root_mount: int, low: int, high: int) -> Held:
    """Pin one closure file and judge all of its metadata; no payload byte is read here."""
    d = deploy()
    try:
        pinned, descriptor, opened = d.open_pinned_regular_at(directory, name, "selection fixture file")
    except (*d.handled_errors(), OSError):
        raise selection_input_error("a selection fixture file cannot be opened safely") from None
    item = Held(name, pinned, descriptor, opened)
    try:
        if opened.st_nlink != 1:
            raise selection_input_error("a selection fixture file has additional hard links")
        if d.untrusted_owner_or_mode(opened):
            raise selection_input_error("a selection fixture file is writable or controlled by another user")
        if opened.st_mode & 0o111:
            raise selection_input_error("a selection fixture file is executable")
        if opened.st_dev != root.st_dev:
            raise selection_input_error("a selection fixture file crosses a device boundary")
        try:
            mount = d.kernel().mount_id_for_fd(pinned, "selection fixture file")
        except (*d.handled_errors(), OSError):
            raise selection_input_error("a selection fixture file mount cannot be determined") from None
        if mount != root_mount:
            raise selection_input_error("a selection fixture file crosses a mount point")
        if not low <= opened.st_size <= high:
            raise selection_input_error("a selection fixture file is outside its byte bounds")
    except BaseException:
        release([item])
        raise
    return item


def settle_selection(directory: int, held: list, root_before: tuple) -> None:
    """The same repeated best-effort passes as the other gathers: detection only, never a claim of
    atomicity or writer exclusion."""
    d = deploy()

    def directory_unchanged() -> None:
        check_selection_closure(list_selection_names(directory), selection_unstable)
        if d.fingerprint(os.fstat(directory)) != root_before:
            raise selection_unstable("the selection fixture directory changed")

    def files_unchanged() -> None:
        for item in held:
            pinned = d.fingerprint(item.opened)
            if d.fingerprint(os.fstat(item.descriptor)) != pinned:
                raise selection_unstable("a selection fixture file changed")
            try:
                current = os.stat(item.name, dir_fd=directory, follow_symlinks=False)
            except OSError:
                raise selection_unstable("a selection fixture file was removed") from None
            if d.fingerprint(current) != pinned:
                raise selection_unstable("a selection fixture file was replaced")

    directory_unchanged()
    files_unchanged()
    directory_unchanged()
    files_unchanged()
    directory_unchanged()


def read_selection_pinned(item: Held) -> bytes:
    d = deploy()
    pinned = d.fingerprint(item.opened)
    if d.fingerprint(os.fstat(item.descriptor)) != pinned:
        raise selection_unstable("a selection fixture file changed before being read")
    chunks, remaining = [], item.opened.st_size
    while remaining:
        block = os.read(item.descriptor, min(1024 * 1024, remaining))
        if not block:
            raise selection_unstable("a selection fixture file changed size while being read")
        chunks.append(block)
        remaining -= len(block)
    if os.read(item.descriptor, 1):
        raise selection_unstable("a selection fixture file grew while being read")
    if d.fingerprint(os.fstat(item.descriptor)) != pinned:
        raise selection_unstable("a selection fixture file changed while being read")
    return b"".join(chunks)


def read_selection_fixture(path: str, r3_bytes: int) -> SelectionFixture:
    """Admit the exact two-file closure from the listing before any payload read, pin and judge
    both files' metadata (including the S bound, computed from the R3 fixture bytes and the two
    sizes), and only then read each file once from its pinned descriptor."""
    d = deploy()
    try:
        descriptor, identity = d.open_trusted_artifact(path, "selection fixture")
    except (*d.handled_errors(), OSError):
        raise selection_input_error("the selection fixture directory failed safe admission") from None
    held = []
    try:
        root = os.fstat(descriptor)
        if d.untrusted_owner_or_mode(root):
            raise selection_input_error("the selection fixture directory is writable or controlled by another user")
        try:
            root_mount = d.kernel().mount_id_for_fd(descriptor, "selection fixture root")
        except (*d.handled_errors(), OSError):
            raise selection_input_error("the selection fixture mount cannot be determined") from None
        root_before = d.fingerprint(root)
        check_selection_closure(list_selection_names(descriptor), selection_input_error)
        bounds = {SELECTION_MANIFEST_PATH: SELECTION_MANIFEST_MAX_BYTES, WITNESS_PATH: WITNESS_MAX_BYTES}
        for name in SELECTION_CLOSURE:
            held.append(pin_selection_file(descriptor, name, root, root_mount, 1, bounds[name]))
        if r3_bytes + sum(item.opened.st_size for item in held) > SELECTION_MAX_FIXTURE_INPUT_BYTES:
            raise selection_budget("the admitted selection input exceeds the per-gather input bound")
        settle_selection(descriptor, held, root_before)
        data = {item.name: read_selection_pinned(item) for item in held}
        settle_selection(descriptor, held, root_before)
    finally:
        release(held)
        os.close(descriptor)
    try:
        d.recheck_trusted_artifact(path, identity, "selection fixture")
    except (*d.handled_errors(), OSError):
        raise selection_unstable("the selection fixture directory changed") from None
    return SelectionFixture(data[SELECTION_MANIFEST_PATH], data[WITNESS_PATH], frozenset({(root.st_dev, root.st_ino)}))


# --- inputs ----------------------------------------------------------------------------


class SelectionInputs:
    def __init__(self, image_inputs, r3_result, r3_spec, r3_parse_sha256, r3_operation_sha256,
                 r3_artifact_bytes, r3_directory_ids, fixture, manifest, witness):
        self.image_inputs = image_inputs
        self.request = image_inputs.request
        self.request_sha256 = image_inputs.request_sha256
        self.request_ids = image_inputs.request_ids
        self.inventory = image_inputs.inventory
        self.images = image_inputs.fixture
        self.r3_result = r3_result
        self.r3_spec = r3_spec
        self.r3_parse_sha256 = r3_parse_sha256
        self.r3_operation_sha256 = r3_operation_sha256
        self.r3_artifact_bytes = r3_artifact_bytes
        self.r3_directory_ids = r3_directory_ids
        self.fixture = fixture
        self.manifest = manifest
        self.witness = witness


def selection_request_row(request: dict) -> dict:
    return next(row for row in request["requested_reads"] if row["id"] == R4_ID)


def selection_paths(args) -> list:
    return [args.request, args.inventory, args.images, args.r3_parse, args.selection]


def check_selection_paths(args, extra=()) -> None:
    d = deploy()
    paths = selection_paths(args)
    for index, first in enumerate(paths):
        for second in paths[index + 1:]:
            if d.paths_overlap(first, second):
                raise selection_input_error("an input path overlaps another input")
    for output in extra:
        if any(d.paths_overlap(output, path) for path in paths):
            raise selection_input_error("the output path overlaps an input")


def admit_r3_parse(args, env: Environment, image_inputs: ImageInputs, r3_result: dict) -> tuple:
    """The R3 artifact is never trusted by its hashes: it is recomputed from the exact admitted image
    buffers and the admitted tree must equal that recomputation entry for entry and byte for byte."""
    d = deploy()
    r3_spec = image_parse_spec(env, image_inputs, r3_result)
    try:
        descriptor, identity = d.open_trusted_artifact(args.r3_parse, "R3 parse")
    except (*d.handled_errors(), OSError):
        raise selection_input_error("the R3 parse failed safe admission") from None
    try:
        tree = walk_output(descriptor, "R3 parse", keep_data=True, trusted_ownership=True)
    except BootchainError:
        raise selection_input_error("the R3 parse tree failed safe inspection") from None
    finally:
        os.close(descriptor)
    try:
        diff_output(tree.entries, d.spec_entries(r3_spec), "R3 parse")
    except BootchainError:
        raise selection_binding("the R3 parse differs from the artifact recomputed from the exact R3 fixture") from None
    try:
        d.recheck_trusted_artifact(args.r3_parse, identity, "R3 parse")
    except (*d.handled_errors(), OSError):
        raise selection_unstable("the R3 parse changed while it was admitted") from None
    return r3_spec, tree


def bind_selection(env: Environment, inputs: SelectionInputs) -> None:
    manifest, witness, fixture = inputs.manifest, inputs.witness, inputs.fixture
    if manifest["bootchain_contract_sha256"] != env.contract_sha256 or (
        manifest["request_sha256"] != inputs.request_sha256
        or manifest["inventory_sha256"] != inputs.inventory.sha256
        or manifest["images_sha256"] != inputs.images.sha256
        or manifest["r3_parse_sha256"] != inputs.r3_parse_sha256
        or manifest["r3_operation_sha256"] != inputs.r3_operation_sha256
    ):
        raise selection_binding("selection.json bindings differ from the contract, request, inventory, images or R3 parse")
    if manifest["witness_bytes"] != len(fixture.witness_bytes) or manifest["witness_sha256"] != fixture.witness_sha256:
        raise selection_binding("selection.json witness size or hash differs from witness.json")
    if witness["request_sha256"] != inputs.request_sha256 or (
        witness["r3_operation_sha256"] != inputs.r3_operation_sha256
        or witness["base_source_partition"] != manifest["base_source_partition"]
        or witness["dtbo_source_partition"] != manifest["dtbo_source_partition"]
    ):
        raise selection_binding("witness.json bindings differ from the request, R3 operation or scope")
    for name in (manifest["base_source_partition"], manifest["dtbo_source_partition"]):
        if name not in inputs.images.files:
            raise selection_binding("a selection source partition is absent from the bound R3 fixture")


def gather_selection(args, env: Environment) -> SelectionInputs:
    check_selection_paths(args)
    image_inputs = gather_images(args, env)
    r3_result = image_result(image_inputs)
    r3_spec, tree = admit_r3_parse(args, env, image_inputs, r3_result)
    fixture = read_selection_fixture(args.selection, r3_result["bytes_read"])
    manifest = parse_selection_manifest(fixture.manifest_bytes)
    witness = parse_witness(fixture.witness_bytes)
    r3_files = {path: data for path, _kind, _mode, data in r3_spec if data is not None}
    inputs = SelectionInputs(
        image_inputs, r3_result, r3_spec,
        sha256_hex(r3_files["SHA256SUMS"]), sha256_hex(r3_files[IMAGE_OPERATION_PATH]),
        sum(len(data) for data in r3_files.values()), tree.directory_ids, fixture, manifest, witness,
    )
    bind_selection(env, inputs)
    others = [inputs.request_ids, image_inputs.fixture.directory_ids, tree.directory_ids,
              fixture.directory_ids, frozenset({image_inputs.inventory.handle.parent_identity})]
    for index, first in enumerate(others):
        if any(first & second for second in others[index + 1:]):
            raise selection_input_error("an input aliases another input tree")
    return inputs


# --- the selection facts ----------------------------------------------------------------


def dtb_component(name: str, data: bytes) -> tuple[int, int]:
    found = parse_layout(name, data)
    for role, _index, offset, size, _type in found["components"]:
        if role == "dtb":
            if not size:
                raise selection_unsupported("the base partition's dtb component is empty")
            return offset, size
    raise selection_unsupported("the base partition's format carries no dtb component")


def selection_result(env: Environment, inputs: SelectionInputs) -> dict:
    manifest, witness = inputs.manifest, inputs.witness
    base, dtbo = manifest["base_source_partition"], manifest["dtbo_source_partition"]
    files = inputs.images.files
    offset, size = dtb_component(base, files[base])
    blobs = parse_fdt_component(files[base][offset:offset + size])
    token = env.identity["device.compatible"].encode("ascii")
    for blob in blobs:
        blob["has_profile_token"] = token in blob["compatible"]
    table = parse_layout(dtbo, files[dtbo])["table"]
    claim = witness["claim"]
    membership = {"claim_present": claim is not None, "dtb_index": None, "dtbo_entry_index": None,
                  "base_candidate_has_contract_token": None, "decoded_table_entry": None}
    if claim is not None:
        dtb_index, entry_index = claim["dtb_index"], claim["dtbo_entry_index"]
        if dtb_index >= len(blobs):
            raise selection_witness_rejected("the witness dtb index is not a member of the parsed blobs")
        if entry_index >= table["count"]:
            raise selection_witness_rejected("the witness dtbo entry index is not a member of the parsed table")
        if not blobs[dtb_index]["has_profile_token"]:
            raise selection_witness_rejected("the claimed base candidate does not carry the contract compatible token")
        entry = table["offset"] + entry_index * table["entry_size"]
        membership.update({
            "dtb_index": dtb_index, "dtbo_entry_index": entry_index,
            "base_candidate_has_contract_token": True,
            "decoded_table_entry": {
                "id": be32(files[dtbo], entry + DT_ENTRY_ID_OFFSET),
                "revision": be32(files[dtbo], entry + DT_ENTRY_REVISION_OFFSET),
            },
        })
    represented = 0
    for row in inputs.r3_result["data"]["images"]:
        image = row["image"]
        if image is None:
            continue
        extents = [(item["offset"], item["size_bytes"]) for item in image["coverage"]["ranges"]]
        if row["partition_name"] == base:
            extents.append((offset, size))
        represented += sum(length for _start, length in merge_ranges(extents))
    if represented > SELECTION_MAX_REPRESENTED_METADATA_BYTES:
        raise selection_budget("represented metadata coverage exceeds its bound")
    payload = inputs.r3_result["bytes_read"] + len(inputs.fixture.manifest_bytes) + len(inputs.fixture.witness_bytes)
    if payload > SELECTION_MAX_FIXTURE_INPUT_BYTES:
        raise selection_budget("the admitted selection input exceeds the per-gather input bound")
    return {
        "base": base, "dtbo": dtbo, "dtb_offset": offset, "dtb_bytes": size, "blobs": blobs,
        "dtbo_entry_count": table["count"], "membership": membership,
        "represented_metadata_bytes": represented, "bytes_read": payload,
        "data": {
            "dtb_count": len(blobs), "selected_board_id": None, "selected_board_revision": None,
            "dtbo_entry_count": table["count"],
            "compatible_prefix": env.identity["device.compatible"], "selection_source": None,
        },
    }


def validate_selection_operation(env: Environment, request: dict, request_sha256: str, raw: bytes) -> dict:
    """The unchanged collector validates the R4 fragment; this parser additionally refuses any
    operation whose selection triple is not null, whatever the collector would accept."""
    c, d = collect(), deploy()
    if len(raw) > SELECTION_MAX_OPERATION_BYTES:
        raise selection_budget("the R4 operation exceeds the selection parser's output bound")
    try:
        document, _outcome = c.validate_operation(raw, selection_request_row(request), request_sha256, env.identity)
    except (BootchainError, c.CollectError, *d.handled_errors(), RecursionError):
        raise selection_operation_rejected("the collector refused the R4 operation") from None
    data = document["data"]
    if any(data[name] is not None for name in ("selected_board_id", "selected_board_revision", "selection_source")):
        raise selection_operation_rejected("the R4 operation carries a selection this parser never produces")
    return document


def selection_input_rows(inputs: SelectionInputs) -> list[dict]:
    fixture = inputs.fixture
    return [
        {"path": SELECTION_MANIFEST_PATH, "role": "selection-manifest", "bytes": len(fixture.manifest_bytes),
         "sha256": fixture.manifest_sha256},
        {"path": WITNESS_PATH, "role": "synthetic-witness", "bytes": len(fixture.witness_bytes),
         "sha256": fixture.witness_sha256},
    ]


def selection_accounting_policy() -> dict:
    return {
        "scope": SELECTION_ACCOUNTING_SCOPE,
        "S": "complete R3 fixture bytes (images.json plus every present image) plus selection.json plus witness.json: operation bytes_read, fixture_payload_bytes and fixture_payload_read_bytes",
        "M": "per image the union of the reused R3 metadata coverage and, for the one base image, the complete parsed base-DTB component range, overlap counted once, summed: represented_metadata_bytes, no hardware read",
        "O": "canonical serialized R4 operation bytes including newline and whitespace",
        "bounds": {
            "S_max_bytes_per_gather": SELECTION_MAX_FIXTURE_INPUT_BYTES,
            "image_max_bytes": MAX_IMAGE_BYTES,
            "M_max_bytes": SELECTION_MAX_REPRESENTED_METADATA_BYTES,
            "O_max_bytes": SELECTION_MAX_OPERATION_BYTES,
            "hardware_read_max_bytes": SELECTION_MAX_REPRESENTED_METADATA_BYTES,
            "parse_json_max_bytes": SELECTION_MAX_PARSE_BYTES,
            "sha256sums_max_bytes": SELECTION_MAX_SUMS_BYTES,
            "output_total_max_bytes": SELECTION_MAX_OUTPUT_BYTES,
        },
        "bound_sources": {
            "S": "collector R4 max_fixture_input_bytes",
            "M": "collector R4 max_hardware_read_bytes",
            "O": "collector R4 max_output_bytes",
        },
        "dependency_reads": "the request tree, the R2 inventory and the R3 parse artifact are dependency reads reported separately and never counted in S",
        "hardware_bytes_read": 0,
        "hardware_transport": "none",
        "rereads": "parse-selection gathers three times and verify-selection twice: each gather is bounded by S separately",
    }


def selection_accounting(inputs: SelectionInputs, result: dict, operation: bytes) -> dict:
    return {
        "scope": SELECTION_ACCOUNTING_SCOPE,
        "fixture_payload_bytes": result["bytes_read"],
        "fixture_payload_read_bytes": result["bytes_read"],
        "r3_fixture_bytes": inputs.r3_result["bytes_read"],
        "selection_input_bytes": len(inputs.fixture.manifest_bytes) + len(inputs.fixture.witness_bytes),
        "represented_metadata_bytes": result["represented_metadata_bytes"],
        "operation_output_bytes": len(operation),
        "dependency_reads": {
            "counted_in_S": False,
            "r2_inventory_bytes": len(inputs.inventory.raw),
            "r3_parse_artifact_bytes": inputs.r3_artifact_bytes,
            "request_tree": "read by the shared request reader: bytes not accounted here",
        },
        "hardware_bytes_read": 0,
        "hardware_transport": "none",
        "definitions": selection_accounting_policy(),
    }


def selection_classification() -> list[dict]:
    rows = [
        ("dtb_count", "parsed-bytes", "fdt-blob-count-of-the-base-dtb-component"),
        ("dtbo_entry_count", "parsed-bytes", "dt-table-entry-count-of-the-dtbo-image"),
        ("witness.dtb_index", "unverified-synthetic-witness-claim", "witness.json"),
        ("witness.dtbo_entry_index", "unverified-synthetic-witness-claim", "witness.json"),
        ("membership", "computed-membership-result", "claimed-indexes-inside-parsed-sets-and-exact-compatible-token"),
        ("decoded_table_entry", "parse-sidecar-only-raw-words", "dt-table-entry-offsets-8-and-12-big-endian"),
        ("compatible_prefix", "contract-constant", "capture-contract-identity-device.compatible"),
    ]
    rows += [(item, "not-established", "no-source-in-this-gate") for item in (
        "selected_board_id", "selected_board_revision", "selection_source",
        "selection_provenance", "selection_freshness", "board_semantics")]
    return [{"item": item, "class": klass, "source": source} for item, klass, source in rows]


def selection_parse_document(env: Environment, inputs: SelectionInputs, result: dict, operation: bytes) -> dict:
    row = selection_request_row(inputs.request)
    membership = result["membership"]
    return {
        "schema": 1,
        "kind": SELECTION_PARSE_KIND,
        "format_version": VERSION,
        "selection_parser_version": SELECTION_PARSER_VERSION,
        "bootchain_contract_sha256": env.contract_sha256,
        "capture_contract_sha256": env.collector.contract_sha256,
        "preflight_contract_sha256": env.collector.preflight_sha256,
        "request_sha256": inputs.request_sha256,
        "inventory_sha256": inputs.inventory.sha256,
        "images_sha256": inputs.images.sha256,
        "r3_parse_sha256": inputs.r3_parse_sha256,
        "r3_operation_sha256": inputs.r3_operation_sha256,
        "selection_sha256": inputs.fixture.manifest_sha256,
        "witness_sha256": inputs.fixture.witness_sha256,
        "implementation": implementation_binding(),
        "dependencies": {
            "trust": DEPENDENCY_TRUST, "byte_pinned": False, "pinned_versions": dict(PINNED_VERSIONS),
        },
        "profile": SELECTION_PROFILE,
        "provenance": {
            "kind": "synthetic-parser-provenance", "captured": False, "hardware_qualified": False,
            "collector_labels_are_not_provenance": True,
        },
        "transport": SELECTION_TRANSPORT,
        "evidence_level": SELECTION_EVIDENCE_LEVEL,
        "status": SELECTION_PARSE_STATUS,
        "synthetic": True,
        "live": False,
        "executes": False,
        "kit_snapshot_reverified": False,
        "remote_commands": [],
        "human_approval_required": True,
        "complete_capture": False,
        "inputs": selection_input_rows(inputs),
        "scope": {
            "base_source_partition": result["base"], "dtbo_source_partition": result["dtbo"],
            "slot_suffix_match": "synthetic-profile-restriction-not-an-active-slot-claim",
        },
        "parsed": {
            "dtb_component": {"offset": result["dtb_offset"], "bytes": result["dtb_bytes"]},
            "dtb_count": len(result["blobs"]),
            "dtb_blobs": [
                {"index": index, "offset": blob["offset"], "bytes": blob["bytes"], "version": FDT_VERSION,
                 "node_count": blob["nodes"], "property_count": blob["properties"],
                 "max_depth": blob["max_depth"], "compatible_token_count": len(blob["compatible"]),
                 "has_contract_token": blob["has_profile_token"]}
                for index, blob in enumerate(result["blobs"])
            ],
            "dtbo_entry_count": result["dtbo_entry_count"],
        },
        "witness": {
            "classification": "unverified-synthetic-witness-claim",
            "claim_present": membership["claim_present"],
            "dtb_index": membership["dtb_index"],
            "dtbo_entry_index": membership["dtbo_entry_index"],
        },
        "membership": {
            "computed": True,
            "result": "claimed-indexes-are-members" if membership["claim_present"] else "no-claim",
            "base_candidate_has_contract_token": membership["base_candidate_has_contract_token"],
            "decoded_table_entry": None if membership["decoded_table_entry"] is None else {
                **membership["decoded_table_entry"],
                "encoding": "dt-table-entry-offsets-8-and-12-big-endian",
                "scope": "parse-sidecar-only",
            },
            "promoted_to_selection": False,
        },
        "classification": selection_classification(),
        "not_established": list(SELECTION_NOT_ESTABLISHED),
        "operation": {
            "id": R4_ID,
            "path": SELECTION_OPERATION_PATH,
            "bytes": len(operation),
            "sha256": sha256_hex(operation),
            "bytes_read": result["bytes_read"],
            **{key: row[key] for key in collect().BUDGET_KEYS},
            "dtb_count": result["data"]["dtb_count"],
            "dtbo_entry_count": result["data"]["dtbo_entry_count"],
            "selected_board_id": None,
            "selected_board_revision": None,
            "selection_source": None,
            "compatible_prefix": result["data"]["compatible_prefix"],
            "collector_transport": collect().TRANSPORT,
            "read_domain": collect().READ_DOMAIN,
        },
        "accounting": selection_accounting(inputs, result, operation),
        "semantic_limits": list(SELECTION_SEMANTIC_LIMITS),
        "unresolved_claims": unresolved_claims(),
        "deferred": deferred_rows(),
        "qualification": qualification(),
        "limitations": list(SELECTION_LIMITATIONS),
        "non_goals": list(NON_GOALS),
        "blockers": blocker_rows(),
        "authority": authority(),
    }


def check_selection_output_bounds(files: dict) -> None:
    if (len(files["parse.json"]) > SELECTION_MAX_PARSE_BYTES or len(files["SHA256SUMS"]) > SELECTION_MAX_SUMS_BYTES
            or len(files[SELECTION_OPERATION_PATH]) > SELECTION_MAX_OPERATION_BYTES
            or sum(len(data) for data in files.values()) > SELECTION_MAX_OUTPUT_BYTES):
        raise selection_budget("the selection parse output exceeds its byte bounds")


def selection_parse_spec(env: Environment, inputs: SelectionInputs) -> list:
    d = deploy()
    result = selection_result(env, inputs)
    operation = d.render_json(operation_document(inputs.request_sha256, result, R4_ID))
    validate_selection_operation(env, inputs.request, inputs.request_sha256, operation)
    files = {
        "parse.json": d.render_json(selection_parse_document(env, inputs, result, operation)),
        SELECTION_OPERATION_PATH: operation,
    }
    files["SHA256SUMS"] = sums_of(files)
    if sorted(files) != SELECTION_OUTPUT_FILES:
        raise selection_operation_rejected("the selection parse output closure differs from the contract")
    check_selection_output_bounds(files)
    spec = [("operations", "dir", 0o755, None)]
    spec += [(path, "file", 0o644, data) for path, data in files.items()]
    spec.sort(key=lambda item: item[0].encode("utf-8"))
    return spec


def selection_result_summary(status: str, inputs: SelectionInputs, spec: list) -> dict:
    d = deploy()
    operation = spec_file(spec, SELECTION_OPERATION_PATH)
    document = json.loads(operation)
    parse = json.loads(spec_file(spec, "parse.json"))
    accounting = parse["accounting"]
    return {
        "status": status,
        "evidence_level": SELECTION_EVIDENCE_LEVEL,
        "profile": SELECTION_PROFILE,
        "operation": R4_ID,
        "parse_sha256": d.sha256_bytes(spec_file(spec, "SHA256SUMS")),
        "operation_sha256": d.sha256_bytes(operation),
        "request_sha256": inputs.request_sha256,
        "inventory_sha256": inputs.inventory.sha256,
        "images_sha256": inputs.images.sha256,
        "r3_parse_sha256": inputs.r3_parse_sha256,
        "selection_sha256": inputs.fixture.manifest_sha256,
        "witness_sha256": inputs.fixture.witness_sha256,
        "bytes_read": document["bytes_read"],
        "represented_metadata_bytes": accounting["represented_metadata_bytes"],
        "operation_output_bytes": accounting["operation_output_bytes"],
        "hardware_bytes_read": 0,
        "dtb_count": document["data"]["dtb_count"],
        "dtbo_entry_count": document["data"]["dtbo_entry_count"],
        "selected_board_id": None,
        "selected_board_revision": None,
        "selection_source": None,
        "blocker_count": len(d.BLOCKERS),
        "synthetic": True,
        "live": False,
        "executes": False,
        "kit_snapshot_reverified": False,
        "complete_capture": False,
        **authority(),
    }


# --- contract ----------------------------------------------------------------------------


def check_selection_registry_consistency(c) -> None:
    """These constants are exactly the collector's R4 fields, null rule and budgets."""
    registry = c.policy_registry()["operations"][R4_ID]
    fields = registry["fields"]
    triple = ["selected_board_id", "selected_board_revision", "selection_source"]
    if set(fields) != {"dtb_count", "dtbo_entry_count", "compatible_prefix", *triple}:
        raise BootchainError("selection parser fields differ from the collector's")
    if fields["dtb_count"] != c._int(0, MAX_FDT_BLOBS) or fields["dtbo_entry_count"] != c._int(0, MAX_DT_ENTRIES):
        raise BootchainError("selection parser counts differ from the collector's")
    if fields["selection_source"] != c._nullable(c._enum(["bootconfig", "device-tree", "dtbo-header"])) or (
        fields["selected_board_id"] != c._nullable(c._int(0, 2**32 - 1))
        or fields["selected_board_revision"] != c._nullable(c._int(0, 2**32 - 1))
    ):
        raise BootchainError("selection parser nullable fields differ from the collector's")
    if registry["constraints"] != [c._null_together(*triple)]:
        raise BootchainError("selection parser null rule differs from the collector's")
    budgets = registry["budgets"]
    if budgets["max_fixture_input_bytes"] != SELECTION_MAX_FIXTURE_INPUT_BYTES or (
        budgets["max_hardware_read_bytes"] != SELECTION_MAX_REPRESENTED_METADATA_BYTES
        or budgets["max_output_bytes"] != SELECTION_MAX_OPERATION_BYTES
    ):
        raise BootchainError("selection parser budgets differ from the collector's")
    if MAX_FDT_BLOBS != 64 or MAX_WITNESS_DTBO_INDEX != 255:
        raise BootchainError("selection parser index bounds are inconsistent")


def selection_parser_contract() -> dict:
    c = collect()
    return {
        "version": SELECTION_PARSER_VERSION,
        "independently_versioned": True,
        "profile": SELECTION_PROFILE,
        "operation": R4_ID,
        "commands": ["plan-selection", "parse-selection", "verify-selection"],
        "kinds": {"manifest": SELECTION_KIND, "witness": WITNESS_KIND, "plan": SELECTION_PLAN_KIND,
                  "parse": SELECTION_PARSE_KIND},
        "transport": SELECTION_TRANSPORT,
        "evidence_level": SELECTION_EVIDENCE_LEVEL,
        "status": SELECTION_PARSE_STATUS,
        "synthetic": True,
        "live": False,
        "executes": False,
        "capture": {
            "operation_kind": c.OPERATION_KIND,
            "transport": c.TRANSPORT,
            "read_domain": c.READ_DOMAIN,
            "operation_schema": c.OPERATION_SCHEMA,
            "collector_transport_label_is_not_provenance": True,
            "validated_by": ["validate_operation", "null-selection-triple"],
            "produces": [R4_ID],
            "does_not_produce": list(SELECTION_NOT_PRODUCED),
            "selection_triple": "always-null",
            "complete_capture": False,
        },
        "binding": {
            "original_r3_fixture": "the exact image fixture bytes the R3 parser admitted: no detached dtb or dtbo copy",
            "r3_artifact": "recomputed from the exact admitted image buffers and compared entry for entry and byte for byte with --r3-parse",
            "r3_metadata_hashes_alone": "insufficient: they do not bind the payload",
            "binds": ["bootchain_contract_sha256", "request_sha256", "inventory_sha256", "r3_parse_sha256",
                      "r3_operation_sha256", "images_sha256", "base_source_partition",
                      "dtbo_source_partition", "witness_bytes", "witness_sha256"],
            "witness_hashed_one_way": "selection.json hashes witness.json; the witness never hashes the manifest",
        },
        "input": {
            "layout": "flat",
            "closure": list(SELECTION_CLOSURE),
            "closure_checked_before_payload_read": True,
            "extra_entries": "reject",
            "bootconfig_txt": "rejected as an extra file: bootconfig is not parsed",
            "entries_max": SELECTION_LISTING_MAX,
            "files": [
                {"path": SELECTION_MANIFEST_PATH, "min_bytes": 1, "max_bytes": SELECTION_MANIFEST_MAX_BYTES,
                 "role": "selection-manifest"},
                {"path": WITNESS_PATH, "min_bytes": 1, "max_bytes": WITNESS_MAX_BYTES, "role": "synthetic-witness"},
            ],
            "json": "strict canonical ASCII; duplicate keys, floats, booleans for integers rejected",
            "schemas": {SELECTION_MANIFEST_PATH: selection_manifest_schema(), WITNESS_PATH: witness_schema()},
            "scope": {
                "base_source_partitions": list(BASE_SOURCES),
                "dtbo_source_partitions": list(DTBO_SOURCES),
                "slot_suffix": "the two source partitions must share one suffix: a synthetic profile restriction, no active-slot claim",
                "init_boot": "never a base source: it carries no dtb",
            },
            "witness": {
                "claim": "null or exactly dtb_index 0..63 and dtbo_entry_index 0..255",
                "meaning": "synthetic unverified claim: membership and binding only",
                "binds": ["request_sha256", "r3_operation_sha256", "base_source_partition",
                          "dtbo_source_partition"],
            },
            "safety": list(SELECTION_SAFETY),
            "configurable": "nothing: caller paths, offsets, parser names, algorithms and limits are fixed here",
            "snapshot_claim": "descriptor-read snapshot only: not atomic, no writer exclusion",
        },
        "formats": {
            "dt_table": {
                "layout": "the R3 DT table v0 layout rules, reused",
                "entry_words": {"id": {"offset": DT_ENTRY_ID_OFFSET, "bytes": 4, "endian": "big"},
                                "revision": {"offset": DT_ENTRY_REVISION_OFFSET, "bytes": 4, "endian": "big"}},
                "decoded": "only for the sidecar's claimed entry; duplicates allowed; custom words opaque; payload never parsed",
                "never_infers_selection_by": ["id", "singleton", "highest-revision", "entry-0"],
                "entries": {"min": 1, "max": MAX_DT_ENTRIES},
            },
            "fdt": {
                "version": FDT_VERSION, "last_comp_version": FDT_LAST_COMP_VERSION, "endian": "big",
                "header_bytes": FDT_HEADER,
                "component": "the exact R3 dtb component: one blob or tightly concatenated blobs, no scan, no gap, no trailing byte",
                "validated": ["magic", "header", "block extents and alignment", "reserve map terminator",
                              "structure tokens", "balanced iterative traversal", "string references",
                              "single FDT_END", "zero gaps and slack", "exact component consumption"],
                "root_compatible": "root node only; duplicate root compatible is corrupt; missing is unsupported",
                "match": "exact token equality with the contract compatible",
                "limits": {"blobs": MAX_FDT_BLOBS, "depth": MAX_FDT_DEPTH, "nodes": MAX_FDT_NODES,
                           "properties_per_blob": MAX_FDT_PROPERTIES, "name_bytes": MAX_FDT_NAME_BYTES,
                           "compatible_tokens": [1, MAX_COMPATIBLE_TOKENS],
                           "compatible_token_bytes": [1, MAX_COMPATIBLE_TOKEN_BYTES]},
                "classification": "malformed is corrupt, valid but outside the profile is unsupported, numeric overruns are budget",
                "empty_component": "unsupported",
            },
        },
        "membership": {
            "claim_null": "no membership check; counts only",
            "claim_set": ["both indexes inside the parsed counts",
                          "the chosen base candidate carries the exact contract compatible token",
                          "the selected table entry id and revision are decoded into the sidecar only"],
            "promotion": "never: a membership result and a decoded entry do not become selected_board_* fields",
        },
        "operation": {
            "dtb_count": "parsed blob count",
            "dtbo_entry_count": "parsed DT table entry count",
            "compatible_prefix": "the capture contract's device.compatible constant",
            "selected_board_id": None,
            "selected_board_revision": None,
            "selection_source": None,
        },
        "accounting": selection_accounting_policy(),
        "diagnostics": {
            "codes": dict(SELECTION_CODES),
            "shared": "the shared request, R2 inventory and R3 image admission keep their documented request-rejected and image-* codes",
            "value_free": "fixed categories only: untrusted paths, names, bytes, sizes, hashes, board ids, compatible strings and exception text are never echoed",
        },
        "output": {
            "kind": SELECTION_PARSE_KIND,
            "directories": ["operations"],
            "files": list(SELECTION_OUTPUT_FILES),
            "extra_entries": "reject",
            "binary_copies": False,
            "witness_copies": False,
            "modes": {"directories": "0755", "files": "0644"},
            "max_bytes": {"parse.json": SELECTION_MAX_PARSE_BYTES, SELECTION_OPERATION_PATH: SELECTION_MAX_OPERATION_BYTES,
                          "SHA256SUMS": SELECTION_MAX_SUMS_BYTES, "total": SELECTION_MAX_OUTPUT_BYTES},
            "checksums": {"path": "SHA256SUMS", "covers": ["parse.json", SELECTION_OPERATION_PATH],
                          "sorted": "canonical-byte-order-of-path"},
            "deterministic": True,
            "published": "atomic-no-replace",
            "verification": "recompute-from-request-inventory-images-r3-parse-and-selection-byte-for-byte",
        },
        "capability": dict(qualification()["r4_capability"]),
        "not_established": list(SELECTION_NOT_ESTABLISHED),
        "semantic_limits": list(SELECTION_SEMANTIC_LIMITS),
        "limitations": list(SELECTION_LIMITATIONS),
    }


def selection_plan_document(env: Environment, request: dict, request_sha256: str, inventory: Inventory) -> dict:
    d = deploy()
    row = selection_request_row(request)
    expected = [name for name in IMAGE_NAMES if name in inventory.sizes]
    return {
        "schema": 1,
        "kind": SELECTION_PLAN_KIND,
        "format_version": VERSION,
        "selection_parser_version": SELECTION_PARSER_VERSION,
        "bootchain_contract_sha256": env.contract_sha256,
        "request_sha256": request_sha256,
        "inventory_sha256": inventory.sha256,
        "request_binding": {
            "operation": R4_ID,
            **{key: row[key] for key in collect().BUDGET_KEYS},
            "emits": list(row["emits"]),
            "never_emits": list(row["never_emits"]),
            "request_sha256_is": "sha256-of-the-verified-request-SHA256SUMS-bytes",
        },
        "expected_inputs": {
            "r3_images": {"present": expected, "absent": [n for n in IMAGE_NAMES if n not in inventory.sizes]},
            "selection_fixture": list(SELECTION_CLOSURE),
            "r3_parse": list(IMAGE_OUTPUT_FILES),
            "note": "the selection fixture holds exactly selection.json and witness.json; the R3 parse is recomputed from the exact R3 image fixture",
        },
        "transport": SELECTION_TRANSPORT,
        "evidence_level": SELECTION_EVIDENCE_LEVEL,
        "implementation": implementation_binding(),
        "synthetic": True,
        "live": False,
        "executes": False,
        "kit_snapshot_reverified": False,
        "remote_commands": [],
        "complete_capture": False,
        "selection_parser": selection_parser_contract(),
        "output_closure": selection_parser_contract()["output"],
        "qualification": qualification(),
        "unresolved_claims": unresolved_claims(),
        "deferred": deferred_rows(),
        "non_goals": list(NON_GOALS),
        "human_approval_required": True,
        "blockers": list(d.BLOCKERS),
        "authority": authority(),
    }


def revalidate_selection_tree(tree, env: Environment, inputs: SelectionInputs) -> None:
    validate_selection_operation(env, inputs.request, inputs.request_sha256, tree.data[SELECTION_OPERATION_PATH])


# --- commands ----------------------------------------------------------------------------


def command_plan_selection(env: Environment, args) -> dict:
    request, request_sha256, _ids, inventory = gather_inventory(args, env)
    try:
        recheck_inventory(args.inventory, inventory)
    finally:
        os.close(inventory.handle.pinned)
    return selection_plan_document(env, request, request_sha256, inventory)


def command_parse_selection(env: Environment, args) -> dict:
    d = deploy()
    check_selection_paths(args, extra=(args.out,))
    inputs = gather_selection(args, env)
    spec = selection_parse_spec(env, inputs)
    expected = d.spec_entries(spec)
    protected = selection_paths(args)
    protected_ids = frozenset(inputs.request_ids | inputs.images.directory_ids | inputs.r3_directory_ids
                              | inputs.fixture.directory_ids)

    def verify_built(_temporary_path: str, descriptor: int) -> None:
        again = gather_selection(args, env)
        if selection_parse_spec(env, again) != spec:
            raise selection_unstable("the request, inventory, images, R3 parse or selection changed during the parse")
        tree = walk_output(descriptor, "parse", keep_data=True)
        diff_output(tree.entries, expected, "parse")
        revalidate_selection_tree(tree, env, again)

    try:
        d.publish(args.out, protected, protected_ids, spec, verify_built)
    except d.handled_errors():
        raise SelectionError("publish-rejected", "the selection parse could not be published safely") from None
    return selection_result_summary("parsed", inputs, spec)


def command_verify_selection(env: Environment, args) -> dict:
    d = deploy()
    check_selection_paths(args, extra=(args.parse,))
    inputs = gather_selection(args, env)
    spec = selection_parse_spec(env, inputs)
    try:
        descriptor, identity = d.open_trusted_artifact(args.parse, "parse")
    except (*d.handled_errors(), OSError):
        raise selection_input_error("the parse artifact failed safe admission") from None
    try:
        tree = walk_output(descriptor, "parse", keep_data=True, trusted_ownership=True)
    finally:
        os.close(descriptor)
    diff_output(tree.entries, d.spec_entries(spec), "parse")
    if tree.directory_ids & (inputs.request_ids | inputs.images.directory_ids | inputs.r3_directory_ids
                             | inputs.fixture.directory_ids):
        raise selection_input_error("the parse aliases an input tree")
    revalidate_selection_tree(tree, env, inputs)
    try:
        d.recheck_trusted_artifact(args.parse, identity, "parse")
    except (*d.handled_errors(), OSError):
        raise selection_unstable("the parse artifact changed during verification") from None
    again = gather_selection(args, env)
    if selection_parse_spec(env, again) != spec:
        raise selection_unstable("the request, inventory, images, R3 parse or selection changed during verification")
    return selection_result_summary("verified", inputs, spec)


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
    plan_images = commands.add_parser("plan-images", help="print the value-free offline R3 image parse plan")
    plan_images.add_argument("--request", required=True)
    plan_images.add_argument("--inventory", required=True)
    parse_images = commands.add_parser(
        "parse-images", help="parse synthetic boot, vendor boot and DT table images into an R3 fragment"
    )
    verify_images = commands.add_parser("verify-images", help="recompute an R3 image parse artifact")
    for command in (parse_images, verify_images):
        command.add_argument("--request", required=True)
        command.add_argument("--inventory", required=True)
        command.add_argument("--images", required=True)
    parse_images.add_argument("--out", required=True)
    verify_images.add_argument("--parse", required=True)
    plan_selection = commands.add_parser(
        "plan-selection", help="print the value-free offline R4 selection parse plan"
    )
    plan_selection.add_argument("--request", required=True)
    plan_selection.add_argument("--inventory", required=True)
    parse_selection = commands.add_parser(
        "parse-selection",
        help="count device tree blobs and DT table entries and bind a synthetic index witness into an R4 fragment",
    )
    verify_selection = commands.add_parser("verify-selection", help="recompute an R4 selection parse artifact")
    for command in (parse_selection, verify_selection):
        command.add_argument("--request", required=True)
        command.add_argument("--inventory", required=True)
        command.add_argument("--images", required=True)
        command.add_argument("--r3-parse", required=True, dest="r3_parse")
        command.add_argument("--selection", required=True)
    parse_selection.add_argument("--out", required=True)
    verify_selection.add_argument("--parse", required=True)
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
            elif args.command == "plan-images":
                result = command_plan_images(env, args)
            elif args.command == "parse-images":
                result = command_parse_images(env, args)
            elif args.command == "verify-images":
                result = command_verify_images(env, args)
            elif args.command == "plan-selection":
                result = command_plan_selection(env, args)
            elif args.command == "parse-selection":
                result = command_parse_selection(env, args)
            elif args.command == "verify-selection":
                result = command_verify_selection(env, args)
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
