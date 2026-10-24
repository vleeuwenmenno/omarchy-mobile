# SPDX-License-Identifier: MIT
"""Rehearse synthetic input adaptation into the exact Myron R1-R7 capture fixture.

Offline and synthetic only. A fixed registry turns one flat tree of synthetic
projections into the capture fixture that tools/myron-collect already consumes,
validates the result with the collector's own validators, and records the
rehearsal. Nothing here reads a phone, acquires evidence, authorizes anything or
clears a blocker.

This file is not run directly. tools/myron-session captures its bytes once and
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

VERSION = "0.1.0"
REPO = Path(__file__).resolve().parent.parent
COLLECT_TOOL = REPO / "tools/myron-collect"
PINNED_VERSIONS = {
    "collector": "0.1.0", "preflight": "0.2.1", "snapshot": "0.2.0", "deployment": "0.4.0",
}
SESSION_CONTRACT_PATH = "device/myron/session-contract.json"
IMPLEMENTATION_PATH = "tools/lib/myron-session-impl.py"
IMPLEMENTATION_ALGORITHM = "sha256-of-captured-implementation-bytes"
CONTRACT_KIND = "myron-synthetic-session-contract"
PLAN_KIND = "myron-synthetic-session-plan"
READS_KIND = "myron-synthetic-reads"
REHEARSAL_KIND = "myron-synthetic-rehearsal"
MANIFEST_KIND = "myron-synthetic-rehearsal-manifest"
TRANSPORT = "synthetic-adapter-rehearsal"
EVIDENCE_LEVEL = "synthetic-adapter-rehearsal-only"
REHEARSAL_STATUS = "synthetic-rehearsal-recorded"
DEPENDENCY_TRUST = "trusted-version-pinned-imports"
MIB = 1024 * 1024
TOTAL_READS_BYTES = 4 * MIB
MANIFEST_PATH = "reads.json"
MANIFEST_MAX_BYTES = 64 * 1024
FILE_CEILING_BYTES = 512 * 1024  # no single payload file may be bounded above this
READS_ENTRIES = 13  # the closure (manifest included) plus one: anything past it is overbound
JSON_DEPTH = 8
PLAN_DEPTH = 8
HEX256 = re.compile(r"[0-9a-f]{64}")
RECOVERY_NAME = re.compile(r"recovery(_a|_b)?")
IMAGE_NAME_LIKE = re.compile(
    r"(boot|init_boot|vendor_boot|vendor_kernel_boot|dtbo|recovery)(_a|_b)?"
)
PARTITION_NAME = re.compile(r"[a-z0-9_]{1,36}")
MODULE_NAME = re.compile(r"[A-Za-z0-9_-]{1,56}")
TAINT_FLAGS = re.compile(r"[A-Z]{0,8}")
SHORT_WORD = re.compile(r"[a-z0-9]{1,32}")
COMPATIBLE = re.compile(r"[a-z0-9,._-]{1,64}")
RELEASE_LINE = re.compile(r"[A-Za-z0-9._+-]{1,128}")
MAX_PARTITIONS = 128
MAX_MODULES = 256
GPT_LBA_LIMIT = 2**48
SECTOR_SIZES = [512, 4096]
ALLOCATION_UNITS = [512, 1024, 2048, 4096, 8192, 16384, 65536]
STATISTICS_LIMIT = 2**50

R1_ID = "R1-identity-and-slot"
R2_ID = "R2-gpt-and-recovery-inventory"
R3_ID = "R3-boot-image-headers"
R4_ID = "R4-dtb-dtbo-selection"
R5_ID = "R5-module-load-order"
R6_ID = "R6-storage-and-mount-model"
R7_ID = "R7-kernel-identity-revalidation"
OPERATION_IDS = [R1_ID, R2_ID, R3_ID, R4_ID, R5_ID, R6_ID, R7_ID]

PARSED, PROJECTION, CLAIM = "parsed-bytes", "synthetic-projection", "unverified-source-claim"
COVERAGE_CLASSES = [PARSED, PROJECTION, CLAIM]

# The fixed input registry. The input tree never selects a parser, a path or a bound.
INPUT_FILES = [
    {"path": "r1-source-a.json", "operation": R1_ID, "format": "json",
     "parser": "synthetic-r1-source-record-v1", "min_bytes": 1, "max_bytes": 16 * 1024},
    {"path": "r1-source-b.json", "operation": R1_ID, "format": "json",
     "parser": "synthetic-r1-source-record-v1", "min_bytes": 1, "max_bytes": 16 * 1024},
    {"path": "r2-partitions.json", "operation": R2_ID, "format": "json",
     "parser": "synthetic-gpt-projection-v1", "min_bytes": 1, "max_bytes": 64 * 1024},
    {"path": "r3-header-summaries.json", "operation": R3_ID, "format": "json",
     "parser": "synthetic-header-summaries-v1", "min_bytes": 1, "max_bytes": 32 * 1024},
    {"path": "r4-selection.json", "operation": R4_ID, "format": "json",
     "parser": "synthetic-selection-record-v1", "min_bytes": 1, "max_bytes": 16 * 1024},
    {"path": "r5-modules.tsv", "operation": R5_ID, "format": "tsv",
     "parser": "module-name-taint-tsv-v1", "min_bytes": 1, "max_bytes": 32 * 1024},
    {"path": "r6-filesystem.json", "operation": R6_ID, "format": "json",
     "parser": "synthetic-filesystem-statistics-v1", "min_bytes": 1, "max_bytes": 16 * 1024},
    {"path": "r7-release.txt", "operation": R7_ID, "format": "text-line",
     "parser": "kernel-release-line-v1", "min_bytes": 2, "max_bytes": 256},
    {"path": "r7-notes.bin", "operation": R7_ID, "format": "bounded-bytes",
     "parser": "bounded-bytes-sha256-v1", "min_bytes": 1, "max_bytes": 512 * 1024},
    {"path": "r7-cmdline.txt", "operation": R7_ID, "format": "text-line",
     "parser": "narrow-cmdline-projection-v1", "min_bytes": 0, "max_bytes": 4096},
    {"path": "r7-bootconfig.txt", "operation": R7_ID, "format": "key-value-lines",
     "parser": "narrow-bootconfig-projection-v1", "min_bytes": 0, "max_bytes": 4096},
]
CLOSURE = sorted([MANIFEST_PATH] + [row["path"] for row in INPUT_FILES])
INPUT_ROWS = {row["path"]: row for row in INPUT_FILES}
OPERATION_INPUTS = {
    operation: [row["path"] for row in INPUT_FILES if row["operation"] == operation]
    for operation in OPERATION_IDS
}
OPERATION_PARSERS = {
    R1_ID: "synthetic-two-source-compare-v1",
    R2_ID: "synthetic-gpt-projection-v1",
    R3_ID: "synthetic-header-summaries-v1",
    R4_ID: "synthetic-selection-record-v1",
    R5_ID: "module-name-taint-tsv-v1",
    R6_ID: "synthetic-filesystem-statistics-v1",
    R7_ID: "release-notes-cmdline-bootconfig-v1",
}
DERIVATIONS = {
    R1_ID: [
        "each source record holds a non-empty subset of the six observed facts",
        "the facts both records hold are compared; any difference rejects the rehearsal",
        "sources_agree is derived from that comparison and is never read from input",
        "the two records must together cover every fact; nothing is filled from the contract",
    ],
    R2_ID: [
        "size_bytes = (last_lba - first_lba + 1) * sector_bytes",
        "slot_suffix is the name's _a or _b ending, else empty",
        "recovery_present is true when a name matches recovery, recovery_a or recovery_b",
        "rows are kept in first_lba order for the overlap check, then emitted sorted by name",
        "simulated_bootable is copied to bootable_flag; no flag is inferred",
    ],
    R3_ID: [
        "rows are explicit synthetic header summaries copied as supplied",
        "header_sha256 is an unverified fixture claim, never recomputed",
        "every R2 partition that names a boot image needs a present row; no row is inferred",
        "an absent row is only accepted where R2 lacks the partition",
    ],
    R4_ID: [
        "the record is copied field by field; no selection is inferred",
        "the board id and revision are both set or both null",
    ],
    R5_ID: [
        "each line is module name, a tab, then the taint flags; file order is kept",
        "load_order_index is the line position and is not historical load chronology",
        "names repeat if equal after hyphen and underscore are treated as one",
        "order_matches_declared compares the declared module order with the file order",
    ],
    R6_ID: [
        "rounded_total_bytes = floor(block_count * allocation_unit_bytes / 1 MiB) * 1 MiB",
        "rounded_free_bytes = floor(free_block_count * allocation_unit_bytes / 1 MiB) * 1 MiB",
        "free_block_count is the free-block count (f_bfree), not the unprivileged count",
        "allocation_unit_bytes divides block_size and is at most block_size",
        "ro and rw together reject; mount options are emitted sorted",
    ],
    R7_ID: [
        "kernel_release is the single bounded release line",
        "notes_sha256 is the SHA-256 of the bounded notes bytes; the bytes are not kept",
        "the command line is space-separated key=value or flag tokens, no quoting",
        "the bootconfig is one key=value per line, no quoting, comments or nesting",
        "only keys and values the request lists are accepted; nothing else is filtered out",
    ],
}
# (operation, field, class, unresolved claim or None)
COVERAGE = [
    (R1_ID, "codename", PROJECTION, None),
    (R1_ID, "soc", PROJECTION, None),
    (R1_ID, "compatible_prefix", PROJECTION, None),
    (R1_ID, "current_slot", PROJECTION, None),
    (R1_ID, "slot_suffix", PROJECTION, None),
    (R1_ID, "verified_boot_state", PROJECTION, None),
    (R1_ID, "sources_agree", PROJECTION, None),
    (R2_ID, "partitions.partition_name", PROJECTION, None),
    (R2_ID, "partitions.size_bytes", PROJECTION, None),
    (R2_ID, "partitions.bootable_flag", CLAIM, "simulated-flag-supplied-not-inferred"),
    (R2_ID, "partitions.slot_suffix", PROJECTION, None),
    (R2_ID, "recovery_present", PROJECTION, None),
    (R3_ID, "images.partition_name", PROJECTION, None),
    (R3_ID, "images.absent", PROJECTION, None),
    (R3_ID, "images.header_version", CLAIM, "header-summary-supplied-not-parsed-from-image-bytes"),
    (R3_ID, "images.page_size", CLAIM, "header-summary-supplied-not-parsed-from-image-bytes"),
    (R3_ID, "images.os_version", CLAIM, "header-summary-supplied-not-parsed-from-image-bytes"),
    (R3_ID, "images.component_sizes", CLAIM, "header-summary-supplied-not-parsed-from-image-bytes"),
    (R3_ID, "images.component_offsets", CLAIM, "header-summary-supplied-not-parsed-from-image-bytes"),
    (R3_ID, "images.segment_count", CLAIM, "header-summary-supplied-not-parsed-from-image-bytes"),
    (R3_ID, "images.header_sha256", CLAIM, "header-hash-supplied-not-verified-against-image-bytes"),
    (R4_ID, "dtb_count", CLAIM, "selection-supplied-not-derived-from-boot-image-bytes"),
    (R4_ID, "selected_board_id", CLAIM, "selection-supplied-not-derived-from-boot-image-bytes"),
    (R4_ID, "selected_board_revision", CLAIM, "selection-supplied-not-derived-from-boot-image-bytes"),
    (R4_ID, "dtbo_entry_count", CLAIM, "selection-supplied-not-derived-from-boot-image-bytes"),
    (R4_ID, "compatible_prefix", PROJECTION, None),
    (R4_ID, "selection_source", PROJECTION, None),
    (R5_ID, "module_names", PARSED, None),
    (R5_ID, "load_order_index", PARSED, None),
    (R5_ID, "taint_flags", PARSED, None),
    (R5_ID, "order_matches_declared", PARSED, None),
    (R6_ID, "root_source_gpt_name", PROJECTION, None),
    (R6_ID, "filesystem_type", PROJECTION, None),
    (R6_ID, "mount_options", PROJECTION, None),
    (R6_ID, "block_size", PROJECTION, None),
    (R6_ID, "rounded_total_bytes", PROJECTION, None),
    (R6_ID, "rounded_free_bytes", PROJECTION, None),
    (R7_ID, "kernel_release", PARSED, None),
    (R7_ID, "notes_sha256", PARSED, None),
    (R7_ID, "allowlisted_cmdline", PARSED, None),
    (R7_ID, "allowlisted_bootconfig_keys", PARSED, None),
]
LIMITATIONS = [
    "synthetic input adaptation only: the fixture bytes were never read from a phone",
    "collector validation proves structure and cross-checks only, not that any value is true",
    "R2 is a synthetic projection, not a GPT binary parse",
    "R3 header values and the R4 selection are explicit claims, not parsed from image or device-tree bytes",
    "R5 order is the fixture file order, not historical load chronology",
    "R7 command line and bootconfig are deliberately narrow projections, not full parsers",
    "bytes_read is fixture accounting only: it counts consumed fixture payload bytes",
    "the collector, preflight, snapshot and deployment imports are trusted version-pinned dependencies, not fully byte-pinned execution",
    "the session contract pins the session implementation bytes; the collector implementation is bound only through the capture contract",
]
NON_GOALS = [
    "real acquisition from a device",
    "live transport of any kind",
    "hardware evidence",
    "authorization of any read, deployment or boot",
    "closing any blocker",
    "device-format qualification: no GPT, Android boot image or device-tree parser is implemented",
]
SAFETY = [
    "flat-tree-only", "exact-closure-before-payload-read", "no-symlinks", "no-hardlinks",
    "no-executable-files", "no-special-files", "no-mount-crossing", "no-writable-ancestry",
    "no-aliases-of-inputs", "stable-while-read", "metadata-admitted-before-payload-read",
    "names-revalidated-after-read",
]


class SessionError(Exception):
    """Synthetic input or rehearsal differs from the reviewed session contract."""


_collect = None


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
        except Exception as error:  # the loader boundary: any failure to load or pin is a refusal
            raise SessionError(f"cannot load the collector: {error}") from error
        if found != PINNED_VERSIONS:
            raise SessionError(f"unsupported verifier versions {found}; expected {PINNED_VERSIONS}")
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
    if Path(__file__).resolve() != (REPO / "tools/myron-session").resolve():
        raise SessionError("session tool is not running from its pinned path")
    digest = globals().get("CAPTURED_IMPLEMENTATION_SHA256")
    if type(digest) is not str or not HEX256.fullmatch(digest):
        raise SessionError("session tool was not loaded through its trusted loader")
    return {
        "algorithm": IMPLEMENTATION_ALGORITHM,
        "path": IMPLEMENTATION_PATH,
        "sha256": digest,
    }


# --- fixed raw-tree schemas -----------------------------------------------------


def raw_schemas() -> dict:
    """The typed shape of every synthetic input file, built from the collector's own spec forms."""
    c = collect()
    schema = c._int(1, 1)

    def kind(name: str) -> dict:
        return c._enum([name])

    facts = {
        "codename": c._text(SHORT_WORD),
        "soc": c._text(SHORT_WORD),
        "compatible_prefix": c._text(COMPATIBLE),
        "current_slot": c._enum(c.SLOTS),
        "slot_suffix": c._enum(c.SLOT_SUFFIXES),
        "verified_boot_state": c._enum(["green", "yellow", "orange", "red"]),
    }
    return {
        "r1-source-a.json": {
            "fields": {"schema": schema, "kind": kind("myron-synthetic-r1-source"),
                       "source": c._enum(["a"])},
            "observed": facts,
        },
        "r1-source-b.json": {
            "fields": {"schema": schema, "kind": kind("myron-synthetic-r1-source"),
                       "source": c._enum(["b"])},
            "observed": facts,
        },
        "r2-partitions.json": {
            "fields": {
                "schema": schema, "kind": kind("myron-synthetic-gpt-projection"),
                "projection": c._enum(["synthetic-gpt-projection-v1"]),
                "sector_bytes": c._int_enum(SECTOR_SIZES),
                "disk_lbas": c._int(2, GPT_LBA_LIMIT),
            },
            "rows_field": "rows",
            "rows": c._rows({
                "name": c._text(PARTITION_NAME),
                "first_lba": c._int(1, GPT_LBA_LIMIT),
                "last_lba": c._int(1, GPT_LBA_LIMIT),
                "simulated_bootable": c._bool(),
            }, 1, MAX_PARTITIONS, "name"),
        },
        "r3-header-summaries.json": {
            "fields": {"schema": schema, "kind": kind("myron-synthetic-header-summaries")},
            "rows_field": "images",
            "rows": c.IMAGE_ROWS,
        },
        "r4-selection.json": {
            "fields": {
                "schema": schema, "kind": kind("myron-synthetic-selection"),
                "compatible_prefix": c._text(COMPATIBLE),
                "dtb_count": c._int(0, 64),
                "dtbo_entry_count": c._int(0, 256),
                "selected_board_id": c._nullable(c._int(0, 2**32 - 1)),
                "selected_board_revision": c._nullable(c._int(0, 2**32 - 1)),
                "selection_source": c._enum(["bootconfig", "device-tree", "dtbo-header"]),
            },
        },
        "r6-filesystem.json": {
            "fields": {
                "schema": schema, "kind": kind("myron-synthetic-filesystem-statistics"),
                "gpt_name": c._text(PARTITION_NAME),
                "filesystem": c._enum(c.FILESYSTEMS),
                "mount_options": c._list(c._enum(c.MOUNT_OPTIONS), 0, 16),
                "block_size": c._int_enum([1024, 2048, 4096, 8192, 16384, 65536]),
                "allocation_unit_bytes": c._int_enum(ALLOCATION_UNITS),
                "block_count": c._int(1, STATISTICS_LIMIT),
                "free_block_count": c._int(0, STATISTICS_LIMIT),
            },
        },
        MANIFEST_PATH: {
            "fields": {
                "schema": schema, "kind": kind(READS_KIND), "format_version": c._enum([VERSION]),
                "session_contract_sha256": c._hash(), "request_sha256": c._hash(),
                "synthetic": c._bool(True),
            },
            "rows_field": "files",
            "rows": c._rows({
                "path": c._enum(sorted(INPUT_ROWS)),
                "bytes": c._int(0, max(row["max_bytes"] for row in INPUT_FILES)),
                "sha256": c._hash(),
            }, len(INPUT_FILES), len(INPUT_FILES), "path"),
        },
    }


def check_registry_consistency(c) -> None:
    """The session registry names exactly the collector's operations, fields and bounds."""
    shared = (
        (IMAGE_NAME_LIKE, c.IMAGE_NAME), (PARTITION_NAME, c.PARTITION_NAME),
        (MODULE_NAME, c.MODULE_NAME), (TAINT_FLAGS, c.TAINT_FLAGS),
    )
    if any(mine.pattern != theirs.pattern for mine, theirs in shared) or MAX_MODULES != c.MAX_MODULES:
        raise SessionError("session patterns or bounds differ from the collector's")
    registry = c.policy_registry()["operations"]
    if registry[R2_ID]["recovery_pattern"] != RECOVERY_NAME.pattern:
        raise SessionError("session recovery pattern differs from the collector's")
    if list(registry) != OPERATION_IDS:
        raise SessionError("session registry operations differ from the collector's")
    declared = {}
    for operation, field, klass, claim in COVERAGE:
        if klass not in COVERAGE_CLASSES or (klass == CLAIM) != (claim is not None):
            raise SessionError("session coverage registry is inconsistent")
        declared.setdefault(operation, []).append(field)
    for operation in OPERATION_IDS:
        policy = registry[operation]
        container = policy["container"]
        expected = set(policy["fields"])
        if container is not None:
            expected = {name for name in expected if name != container["rows_field"]} | {
                f"{container['rows_field']}.{name}" for name in container["row_fields"]
            }
        if sorted(declared.get(operation, [])) != sorted(expected) or len(set(declared[operation])) != len(
            declared[operation]
        ):
            raise SessionError("session coverage registry differs from the collector's fields")
    if len(set(CLOSURE)) != len(CLOSURE) or len(CLOSURE) != READS_ENTRIES - 1:
        raise SessionError("session input closure is inconsistent")
    for row in INPUT_FILES:
        if not 0 <= row["min_bytes"] <= row["max_bytes"] <= FILE_CEILING_BYTES:
            raise SessionError("session input bounds are inconsistent")
    if sum(row["max_bytes"] for row in INPUT_FILES) + MANIFEST_MAX_BYTES > TOTAL_READS_BYTES:
        raise SessionError("session input bounds exceed the total byte bound")
    limits = {row["id"]: row["max_bytes"] for row in c.preflight().requested_reads()}
    for operation in OPERATION_IDS:
        if sum(INPUT_ROWS[path]["max_bytes"] for path in OPERATION_INPUTS[operation]) > limits[operation]:
            raise SessionError("session input bounds exceed an operation's byte bound")


def coverage_rows() -> list[dict]:
    return [
        {"operation": operation, "field": field, "classification": klass}
        for operation, field, klass, _ in COVERAGE
    ]


def unresolved_claims() -> list[dict]:
    return [
        {"operation": operation, "field": field, "claim": claim}
        for operation, field, klass, claim in COVERAGE if klass == CLAIM
    ]


def output_files() -> list[str]:
    capture = ["capture/capture.json"] + [f"capture/operations/{name}.json" for name in OPERATION_IDS]
    return sorted(["SHA256SUMS", "manifest.json", "rehearsal.json", *capture])


def output_closure() -> dict:
    return {
        "directories": ["capture", "capture/operations"],
        "files": output_files(),
        "extra_entries": "reject",
        "checksums": {
            "path": "SHA256SUMS",
            "covers": "every file except SHA256SUMS itself",
            "sufficient_for_verification": False,
        },
    }


def accounting_policy() -> dict:
    return {
        "bytes_read": "exact-consumed-fixture-payload-bytes",
        "meaning": "fixture-accounting-only",
        "excludes": ["reads.json", "verification-rereads"],
        "operation_inputs": {name: list(OPERATION_INPUTS[name]) for name in OPERATION_IDS},
    }


# --- contract -------------------------------------------------------------------


def input_contract() -> dict:
    return {
        "kind": READS_KIND,
        "format_version": VERSION,
        "layout": "flat",
        "closure": list(CLOSURE),
        "closure_checked_before_payload_read": True,
        "extra_entries": "reject",
        "entries_max": READS_ENTRIES,
        "total_max_bytes": TOTAL_READS_BYTES,
        "json_depth_max": JSON_DEPTH,
        "json": "strict canonical ASCII; duplicate keys, floats, booleans for integers rejected",
        "safety": list(SAFETY),
        "manifest": {
            "path": MANIFEST_PATH,
            "max_bytes": MANIFEST_MAX_BYTES,
            "rows_sorted_by": "path",
            "binds": ["session_contract_sha256", "request_sha256"],
        },
        "files": [dict(row) for row in INPUT_FILES],
        "schemas": raw_schemas(),
        "text_limits": {
            "release": RELEASE_LINE.pattern,
            "module_name": MODULE_NAME.pattern,
            "taint_flags": TAINT_FLAGS.pattern,
            "max_modules": MAX_MODULES,
            "max_partitions": MAX_PARTITIONS,
        },
        "parser_selection": "fixed-registry-only",
    }


def expected_session_contract(env) -> dict:
    """The one session contract this collector, preflight and kernel reference admit."""
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
                "imported in-process and pinned by version only; their bytes are not pinned "
                "here, and the collector implementation digest is bound through the capture contract"
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
        "status": REHEARSAL_STATUS,
        "human_approval_required": True,
        "capture": {
            "kind": c.CAPTURE_KIND,
            "operation_kind": c.OPERATION_KIND,
            "transport": c.TRANSPORT,
            "collector_transport_label_is_not_provenance": True,
            "unchanged_for_collector": True,
            "validated_by": ["validate_operation", "cross_check", "read_capture"],
        },
        "input": input_contract(),
        "registry": {
            "operations": [
                {
                    "id": operation,
                    "parser": OPERATION_PARSERS[operation],
                    "inputs": list(OPERATION_INPUTS[operation]),
                    "derivations": list(DERIVATIONS[operation]),
                }
                for operation in OPERATION_IDS
            ],
        },
        "coverage": {
            "classes": list(COVERAGE_CLASSES),
            "fields": coverage_rows(),
            "unresolved_claims": unresolved_claims(),
        },
        "output": {
            "kind": REHEARSAL_KIND,
            "manifest_kind": MANIFEST_KIND,
            "closure": output_closure(),
            "accounting": accounting_policy(),
            "deterministic": True,
            "published": "atomic-no-replace",
            "verification": "recompute-from-request-and-reads-byte-for-byte",
        },
        "identity": c.identity_values(env.contracts),
        "limitations": list(LIMITATIONS),
        "non_goals": list(NON_GOALS),
        "blockers": list(d.BLOCKERS),
        "authority": p.authority(),
    }


def load_session_contract(root: Path, env) -> tuple[dict, bytes, str]:
    d = deploy()
    data = d.read_file(f"{root}/{SESSION_CONTRACT_PATH}", "session contract", d.MAX_SMALL_BYTES)
    value = d.strict_json(data, "session contract")
    expected = expected_session_contract(env)
    if not collect().kernel().strict_equal(value, expected):
        raise SessionError("session contract differs from its derived form")
    if data != d.render_json(expected):
        raise SessionError("session contract is not canonical")
    return value, data, d.sha256_bytes(data)


class Environment:
    def __init__(self, collector_env, contract, contract_bytes, contract_sha256):
        self.collector = collector_env
        self.contracts = collector_env.contracts
        self.identity = collector_env.identity
        self.contract = contract
        self.contract_bytes = contract_bytes
        self.contract_sha256 = contract_sha256


def load_environment(root: Path) -> Environment:
    c = collect()
    collector_env = c.load_environment(root)
    contract, contract_bytes, contract_sha256 = load_session_contract(root, collector_env)
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
                raise SessionError(f"{label} repeats a JSON key")
            result[key] = value
        return result

    def constant(_name):
        raise SessionError(f"{label} holds a non-finite number")

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, RecursionError) as error:  # includes UnicodeDecodeError, JSONDecodeError
        raise SessionError(f"{label} is invalid JSON") from error
    if type(value) is not dict:
        raise SessionError(f"{label} is not a JSON object")
    c.check_json_depth(value, label, JSON_DEPTH)
    if raw != d.render_json(value):
        raise SessionError(f"{label} is not canonical JSON")
    return value


def check_fields(document: dict, fields: dict, label: str) -> dict:
    c = collect()
    c.need_dict(document, list(fields), label)
    return {
        name: c.check_spec(spec, document[name], f"{label} {name}", {})
        for name, spec in fields.items()
    }


def split_header(document: dict, schema: dict, body: str, label: str) -> dict:
    """Check a document holds exactly the schema's header fields plus its one body field."""
    if set(document) != {*schema["fields"], body}:
        raise SessionError(f"{label} fields differ")
    return check_fields({key: document[key] for key in schema["fields"]}, schema["fields"], label)


def ascii_text(raw: bytes, label: str) -> str:
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError as error:
        raise SessionError(f"{label} is not ASCII") from error
    if any(not (char == "\n" or char == "\t" or 32 <= ord(char) < 127) for char in text):
        raise SessionError(f"{label} holds a control character")
    return text


# --- R1 -------------------------------------------------------------------------


def parse_r1_source(raw: bytes, path: str) -> dict:
    c = collect()
    schema = raw_schemas()[path]
    label = f"R1 {path}"
    document = parse_json(raw, label)
    split_header(document, schema, "observed", label)
    observed = document["observed"]
    if type(observed) is not dict or not observed or set(observed) - set(schema["observed"]):
        raise SessionError(f"{label} observed facts differ")
    return {
        name: c.check_spec(schema["observed"][name], value, f"{label} {name}", {})
        for name, value in observed.items()
    }


def derive_r1(raw_a: bytes, raw_b: bytes) -> dict:
    first = parse_r1_source(raw_a, "r1-source-a.json")
    second = parse_r1_source(raw_b, "r1-source-b.json")
    overlap = set(first) & set(second)
    if not overlap:
        raise SessionError("R1 source records share no fact to compare")
    agree = all(first[name] == second[name] for name in overlap)
    if not agree:
        raise SessionError("R1 source records disagree on an overlapping fact")
    merged = {**first, **second}
    if set(merged) != set(raw_schemas()["r1-source-a.json"]["observed"]):
        raise SessionError("R1 source records do not cover every observed fact")
    return {**merged, "sources_agree": agree}


# --- R2 -------------------------------------------------------------------------


def derive_r2(raw: bytes) -> dict:
    c = collect()
    schema = raw_schemas()["r2-partitions.json"]
    document = parse_json(raw, "R2 partitions")
    header = split_header(document, schema, "rows", "R2 partitions")
    rows = c.check_rows(schema["rows"], document["rows"], "R2 rows", "R2 row", {})
    sector, disk = header["sector_bytes"], header["disk_lbas"]
    names = [row["name"] for row in rows]
    if len(set(names)) != len(names):
        raise SessionError("R2 rows repeat a partition name")
    previous_last, previous_first = 0, 0
    partitions = []
    for row in rows:
        first, last = row["first_lba"], row["last_lba"]
        if first > last or last >= disk:
            raise SessionError("R2 row geometry lies outside the disk or runs backwards")
        if first <= previous_first:
            raise SessionError("R2 rows are not in ascending first_lba order")
        if first <= previous_last:
            raise SessionError("R2 rows overlap")
        previous_first, previous_last = first, last
        size = (last - first + 1) * sector
        if size > 2**50:
            raise SessionError("R2 row size is outside the supported range")
        name = row["name"]
        partitions.append({
            "partition_name": name,
            "size_bytes": size,
            "bootable_flag": row["simulated_bootable"],
            "slot_suffix": name[-2:] if name.endswith(("_a", "_b")) else "",
        })
    partitions.sort(key=lambda row: row["partition_name"])
    return {
        "partitions": partitions,
        "recovery_present": any(RECOVERY_NAME.fullmatch(name) for name in names),
    }


# --- R3 -------------------------------------------------------------------------


def derive_r3(raw: bytes, inventory: list) -> dict:
    c = collect()
    schema = raw_schemas()["r3-header-summaries.json"]
    document = parse_json(raw, "R3 header summaries")
    split_header(document, schema, "images", "R3 header summaries")
    rows = c.check_rows(schema["rows"], document["images"], "R3 images", "R3 image", {})
    names = [row["partition_name"] for row in rows]
    if names != sorted(set(names)):
        raise SessionError("R3 images are not unique and sorted")
    present = {row["partition_name"] for row in inventory}
    for row in rows:
        listed = row["partition_name"] in present
        if row["absent"] == listed:
            raise SessionError("R3 summary presence differs from the R2 inventory")
    missing = [name for name in sorted(present) if IMAGE_NAME_LIKE.fullmatch(name) and name not in names]
    if missing:
        raise SessionError("R3 has no header summary for an inventoried boot image")
    return {"images": rows}


# --- R4 -------------------------------------------------------------------------


def derive_r4(raw: bytes) -> dict:
    schema = raw_schemas()["r4-selection.json"]
    values = check_fields(parse_json(raw, "R4 selection"), schema["fields"], "R4 selection")
    if (values["selected_board_id"] is None) != (values["selected_board_revision"] is None):
        raise SessionError("R4 board id and revision must both be set or both be null")
    return {
        name: values[name] for name in (
            "dtb_count", "selected_board_id", "selected_board_revision", "dtbo_entry_count",
            "compatible_prefix", "selection_source",
        )
    }


# --- R5 -------------------------------------------------------------------------


def derive_r5(raw: bytes, declared_order: list) -> dict:
    c = collect()
    text = ascii_text(raw, "R5 modules")
    if not text.endswith("\n"):
        raise SessionError("R5 modules do not end with a newline")
    lines = text[:-1].split("\n")
    if len(lines) > MAX_MODULES:
        raise SessionError(f"R5 modules exceed {MAX_MODULES} entries")
    names, taints, seen = [], [], set()
    for line in lines:
        columns = line.split("\t")
        if len(columns) != 2:
            raise SessionError("R5 line is not a module name and a taint column")
        name = c.need_text(columns[0], "R5 module name", MODULE_NAME)
        taints.append(c.need_text(columns[1], "R5 taint flags", TAINT_FLAGS))
        key = name.replace("-", "_")
        if key in seen:
            raise SessionError("R5 modules repeat a name, hyphen and underscore forms included")
        seen.add(key)
        names.append(name)
    declared = [name.replace("-", "_") for name in declared_order]
    listed = [name.replace("-", "_") for name in names]
    return {
        "module_names": names,
        "load_order_index": list(range(len(names))),
        "taint_flags": taints,
        "order_matches_declared": [name for name in listed if name in declared] == declared,
    }


# --- R6 -------------------------------------------------------------------------


def derive_r6(raw: bytes) -> dict:
    schema = raw_schemas()["r6-filesystem.json"]
    values = check_fields(parse_json(raw, "R6 filesystem"), schema["fields"], "R6 filesystem")
    options = values["mount_options"]
    if len(set(options)) != len(options):
        raise SessionError("R6 mount options repeat")
    if "ro" in options and "rw" in options:
        raise SessionError("R6 mount options hold both ro and rw")
    unit, block = values["allocation_unit_bytes"], values["block_size"]
    if unit > block or block % unit:
        raise SessionError("R6 allocation unit does not divide the block size")
    count, free = values["block_count"], values["free_block_count"]
    if free > count:
        raise SessionError("R6 free blocks exceed the block count")
    total_bytes, free_bytes = count * unit, free * unit
    if total_bytes > STATISTICS_LIMIT:
        raise SessionError("R6 filesystem size is outside the supported range")
    rounded_total, rounded_free = total_bytes // MIB * MIB, free_bytes // MIB * MIB
    if rounded_total < MIB:
        raise SessionError("R6 filesystem is under 1 MiB after rounding")
    return {
        "root_source_gpt_name": values["gpt_name"],
        "filesystem_type": values["filesystem"],
        "mount_options": sorted(options),
        "block_size": block,
        "rounded_total_bytes": rounded_total,
        "rounded_free_bytes": rounded_free,
    }


# --- R7 -------------------------------------------------------------------------


def parse_release(raw: bytes) -> str:
    text = ascii_text(raw, "R7 release")
    if not text.endswith("\n") or "\n" in text[:-1] or "\t" in text:
        raise SessionError("R7 release is not one newline-terminated line")
    return collect().need_text(text[:-1], "R7 release", RELEASE_LINE)


def allowlist(entries: list, label: str) -> dict:
    allowed = {}
    for entry in entries:
        if entry["value_type"] not in ("enum", "flag") or entry["key"] in allowed:
            raise SessionError(f"{label} allowlist is unsupported")
        allowed[entry["key"]] = entry
    return allowed


def accept_pair(allowed: dict, key: str, value, label: str, found: dict) -> None:
    entry = allowed.get(key)
    if entry is None:
        raise SessionError(f"{label} holds a key the request does not list")
    if key in found:
        raise SessionError(f"{label} repeats a key")
    if entry["value_type"] == "flag":
        if value is not None:
            raise SessionError(f"{label} flag carries a value")
        value = "present"
    elif value is None:
        raise SessionError(f"{label} key has no value")
    if value not in entry["allowed_values"]:
        raise SessionError(f"{label} holds a value the request does not list")
    found[key] = value


def reject_quotes(text: str, label: str) -> None:
    if any(char in text for char in "\"'`\\"):
        raise SessionError(f"{label} holds a quoted or escaped form")


def parse_cmdline(raw: bytes, entries: list) -> list:
    label = "R7 command line"
    if raw == b"":
        return []
    text = ascii_text(raw, label)
    reject_quotes(text, label)
    if not text.endswith("\n") or "\n" in text[:-1] or "\t" in text or len(text) == 1:
        raise SessionError(f"{label} is not one newline-terminated line")
    allowed, found = allowlist(entries, label), {}
    for token in text[:-1].split(" "):
        if not token:
            raise SessionError(f"{label} holds an empty token")
        key, separator, value = token.partition("=")
        accept_pair(allowed, key, value if separator else None, label, found)
    return [{"key": key, "value": found[key]} for key in sorted(found)]


def parse_bootconfig(raw: bytes, entries: list) -> list:
    label = "R7 bootconfig"
    if raw == b"":
        return []
    text = ascii_text(raw, label)
    reject_quotes(text, label)
    if not text.endswith("\n"):
        raise SessionError(f"{label} does not end with a newline")
    allowed, found = allowlist(entries, label), {}
    for line in text[:-1].split("\n"):
        key, separator, value = line.partition("=")
        if not separator or any(char in line for char in " \t#;{}[]"):
            raise SessionError(f"{label} holds an unsupported form")
        if allowed.get(key, {}).get("value_type") == "flag":
            raise SessionError(f"{label} holds an unsupported form")
        accept_pair(allowed, key, value, label, found)
    return [{"key": key, "value": found[key]} for key in sorted(found)]


def derive_r7(release: bytes, notes: bytes, cmdline: bytes, bootconfig: bytes, policy: dict) -> dict:
    return {
        "kernel_release": parse_release(release),
        "notes_sha256": sha256_hex(notes),
        "allowlisted_cmdline": parse_cmdline(cmdline, policy["kernel_command_line"]["entries"]),
        "allowlisted_bootconfig_keys": parse_bootconfig(bootconfig, policy["bootconfig"]["entries"]),
    }


# --- reads tree -----------------------------------------------------------------


class Reads:
    def __init__(self, manifest_bytes, files, directory_ids):
        self.manifest_bytes = manifest_bytes
        self.files = files  # path -> bytes, payload only
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
    with os.scandir(descriptor) as children:
        for child in children:
            names.append(child.name)
            if len(names) > READS_ENTRIES:
                raise SessionError("synthetic reads exceed the entry bound")
    return names


def check_closure(names: list[str], when: str = "") -> None:
    """Diagnostics carry counts only: an unexpected name is never echoed."""
    if sorted(names) != CLOSURE:
        extra = len(set(names) - set(CLOSURE))
        missing = len(set(CLOSURE) - set(names))
        raise SessionError(
            f"synthetic reads {when}differ from the exact closure ({extra} extra, {missing} missing)"
        )


def reads_bounds(name: str) -> tuple[int, int]:
    if name == MANIFEST_PATH:
        return 1, MANIFEST_MAX_BYTES
    row = INPUT_ROWS[name]
    return row["min_bytes"], row["max_bytes"]


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
                directory, name, f"synthetic reads file {name}"
            )
            held.append(Held(name, pinned, descriptor, opened))
            if opened.st_nlink != 1:
                raise SessionError(f"synthetic reads file {name} has additional hard links")
            if d.untrusted_owner_or_mode(opened):
                raise SessionError(f"synthetic reads file {name} is writable or controlled by another user")
            if opened.st_mode & 0o111:
                raise SessionError(f"synthetic reads file is executable: {name}")
            if opened.st_dev != root.st_dev:
                raise SessionError(f"synthetic reads file {name} crosses a device boundary")
            if d.kernel().mount_id_for_fd(pinned, f"synthetic reads file {name}") != root_mount:
                raise SessionError(f"synthetic reads file {name} crosses a mount point")
            low, high = reads_bounds(name)
            if not low <= opened.st_size <= high:
                raise SessionError(f"synthetic reads file {name} is outside its {low}..{high} byte bounds")
            total += opened.st_size
            if total > TOTAL_READS_BYTES:
                raise SessionError("synthetic reads exceed the total byte bound")
    except BaseException:
        release(held)
        raise
    return held


def settle_reads(directory: int, held: list, root_before: tuple, when: str) -> None:
    """The listing, the directory and every name still match the pinned descriptors."""
    d = deploy()
    check_closure(list_names(directory), f"changed {when} and ")
    if d.fingerprint(os.fstat(directory)) != root_before:
        raise SessionError(f"synthetic reads directory changed {when}")
    for item in held:
        pinned = d.fingerprint(item.opened)
        if d.fingerprint(os.fstat(item.descriptor)) != pinned:
            raise SessionError(f"synthetic reads file {item.name} changed {when}")
        try:
            current = os.stat(item.name, dir_fd=directory, follow_symlinks=False)
        except OSError as error:
            raise SessionError(f"synthetic reads file {item.name} was removed {when}") from error
        if d.fingerprint(current) != pinned:
            raise SessionError(f"synthetic reads file {item.name} was replaced {when}")


def read_pinned(item: Held) -> bytes:
    """Exactly the stat size from the captured descriptor, then a stability check."""
    d = deploy()
    pinned = d.fingerprint(item.opened)
    if d.fingerprint(os.fstat(item.descriptor)) != pinned:
        raise SessionError(f"synthetic reads file {item.name} changed before being read")
    chunks, remaining = [], item.opened.st_size
    while remaining:
        block = os.read(item.descriptor, min(MIB, remaining))
        if not block:
            raise SessionError(f"synthetic reads file {item.name} changed size while being read")
        chunks.append(block)
        remaining -= len(block)
    if os.read(item.descriptor, 1):
        raise SessionError(f"synthetic reads file {item.name} grew while being read")
    if d.fingerprint(os.fstat(item.descriptor)) != pinned:
        raise SessionError(f"synthetic reads file {item.name} changed while being read")
    return b"".join(chunks)


def check_manifest(raw: bytes, files: dict, env: Environment, request_sha256: str) -> None:
    c = collect()
    schema = raw_schemas()[MANIFEST_PATH]
    document = parse_json(raw, "reads.json")
    header = split_header(document, schema, "files", "reads.json")
    if header["session_contract_sha256"] != env.contract_sha256:
        raise SessionError("reads.json session contract binding differs")
    if header["request_sha256"] != request_sha256:
        raise SessionError("reads.json request binding differs")
    rows = c.check_rows(schema["rows"], document["files"], "reads.json files", "reads.json file", {})
    if [row["path"] for row in rows] != sorted(files):
        raise SessionError("reads.json files differ from the closure or are not sorted")
    for row in rows:
        data = files[row["path"]]
        if row["bytes"] != len(data) or row["sha256"] != sha256_hex(data):
            raise SessionError(f"reads.json row for {row['path']} differs from the file")


def read_reads(path: str, env: Environment, request_sha256: str) -> Reads:
    """Admit the flat tree in order: exact closure, then every descriptor's metadata, then a
    re-listing, and only then the payload bytes, from the pinned descriptors, with the names
    revalidated afterwards. A missing, extra or unsafe file stops the read at zero payload bytes."""
    d = deploy()
    descriptor, identity = d.open_trusted_artifact(path, "synthetic reads")
    held = []
    try:
        root = os.fstat(descriptor)
        if d.untrusted_owner_or_mode(root):
            raise SessionError("synthetic reads directory is writable or controlled by another user")
        root_mount = d.kernel().mount_id_for_fd(descriptor, "synthetic reads root")
        root_before = d.fingerprint(root)
        check_closure(list_names(descriptor))
        held = pin_reads(descriptor, root, root_mount)
        settle_reads(descriptor, held, root_before, "during admission")
        data = {item.name: read_pinned(item) for item in held}
        settle_reads(descriptor, held, root_before, "while being read")
    finally:
        release(held)
        os.close(descriptor)
    manifest_bytes = data[MANIFEST_PATH]
    files = {name: data[name] for name in CLOSURE if name != MANIFEST_PATH}
    check_manifest(manifest_bytes, files, env, request_sha256)
    d.recheck_trusted_artifact(path, identity, "synthetic reads")
    return Reads(manifest_bytes, files, frozenset({(root.st_dev, root.st_ino)}))


# --- adaptation -----------------------------------------------------------------


class Inputs:
    def __init__(self, request, request_sha256, request_ids, reads):
        self.request = request
        self.request_sha256 = request_sha256
        self.request_ids = request_ids
        self.reads = reads


def read_request(path: str, env: Environment):
    request, request_sha256, ids = collect().read_request(path, env.collector)
    if [row["id"] for row in request["requested_reads"]] != OPERATION_IDS:
        raise SessionError("request operations differ from the session registry")
    return request, request_sha256, ids


def gather(args, env: Environment) -> Inputs:
    d = deploy()
    if d.paths_overlap(args.request, args.reads):
        raise SessionError("reads and request paths overlap")
    request, request_sha256, request_ids = read_request(args.request, env)
    reads = read_reads(args.reads, env, request_sha256)
    if request_ids & reads.directory_ids:
        raise SessionError("reads alias the request tree")
    return Inputs(request, request_sha256, request_ids, reads)


def adapt(env: Environment, inputs: Inputs) -> dict:
    """Operation id -> {data, bytes_read}, derived from the synthetic bytes alone."""
    c = collect()
    files = inputs.reads.files
    request = inputs.request
    reads = {row["id"]: row for row in request["requested_reads"]}
    r2 = derive_r2(files["r2-partitions.json"])
    data = {
        R1_ID: derive_r1(files["r1-source-a.json"], files["r1-source-b.json"]),
        R2_ID: r2,
        R3_ID: derive_r3(files["r3-header-summaries.json"], r2["partitions"]),
        R4_ID: derive_r4(files["r4-selection.json"]),
        R5_ID: derive_r5(files["r5-modules.tsv"], list(c.deploy().REFERENCE_MODULE_ORDER)),
        R6_ID: derive_r6(files["r6-filesystem.json"]),
        R7_ID: derive_r7(
            files["r7-release.txt"], files["r7-notes.bin"], files["r7-cmdline.txt"],
            files["r7-bootconfig.txt"], reads[R7_ID]["field_policy"],
        ),
    }
    return {
        operation: {
            "data": data[operation],
            "bytes_read": sum(len(files[path]) for path in OPERATION_INPUTS[operation]),
        }
        for operation in OPERATION_IDS
    }


def operation_document(operation: str, request_sha256: str, result: dict) -> dict:
    c = collect()
    return {
        "schema": 1,
        "kind": c.OPERATION_KIND,
        "id": operation,
        "request_sha256": request_sha256,
        "transport": c.TRANSPORT,
        "read_only": True,
        "bytes_read": result["bytes_read"],
        "data": result["data"],
    }


def capture_files(env: Environment, inputs: Inputs, results: dict) -> dict:
    """The capture fixture the collector consumes, built and checked by the collector's own code."""
    c, d = collect(), deploy()
    request, request_sha256 = inputs.request, inputs.request_sha256
    files = {
        c.operation_path(operation): d.render_json(
            operation_document(operation, request_sha256, results[operation])
        )
        for operation in OPERATION_IDS
    }
    documents, r7 = {}, None
    for row in request["requested_reads"]:
        document, outcome = c.validate_operation(
            files[c.operation_path(row["id"])], row, request_sha256, env.identity
        )
        documents[row["id"]] = document
        if outcome is not None:
            r7 = outcome
    c.cross_check(documents, r7)
    files["capture.json"] = d.render_json(
        c.manifest_document(env.collector, request_sha256, request, files)
    )
    return files


def sums_of(files: dict) -> bytes:
    d = deploy()
    return "".join(
        f"{d.sha256_bytes(files[path])}  {path}\n" for path in sorted(files, key=lambda p: p.encode())
    ).encode("ascii")


def input_rows(inputs: Inputs) -> list[dict]:
    return [
        {
            "path": path,
            "operation": INPUT_ROWS[path]["operation"],
            "parser": INPUT_ROWS[path]["parser"],
            "bytes": len(inputs.reads.files[path]),
            "sha256": sha256_hex(inputs.reads.files[path]),
        }
        for path in sorted(inputs.reads.files)
    ]


def rehearsal_document(env: Environment, inputs: Inputs, results: dict, capture: dict) -> dict:
    d = deploy()
    request = inputs.request
    return {
        "schema": 1,
        "kind": REHEARSAL_KIND,
        "format_version": VERSION,
        "session_contract_sha256": env.contract_sha256,
        "capture_contract_sha256": env.collector.contract_sha256,
        "preflight_contract_sha256": env.collector.preflight_sha256,
        "request_sha256": inputs.request_sha256,
        "reads_sha256": inputs.reads.sha256,
        "capture_sha256": d.sha256_bytes(sums_of(capture)),
        "transport": TRANSPORT,
        "evidence_level": EVIDENCE_LEVEL,
        "status": REHEARSAL_STATUS,
        "synthetic": True,
        "live": False,
        "executes": False,
        "kit_snapshot_reverified": False,
        "remote_commands": [],
        "human_approval_required": True,
        "collector_checks": ["validate_operation", "cross_check", "read_capture"],
        "dependencies": {"trust": DEPENDENCY_TRUST, "byte_pinned": False},
        "inputs": input_rows(inputs),
        "operations": [
            {
                "id": row["id"],
                "parser": OPERATION_PARSERS[row["id"]],
                "inputs": list(OPERATION_INPUTS[row["id"]]),
                "bytes_read": results[row["id"]]["bytes_read"],
                "max_bytes": row["max_bytes"],
                "output": f"capture/operations/{row['id']}.json",
                "output_bytes": len(capture[f"operations/{row['id']}.json"]),
                "output_sha256": d.sha256_bytes(capture[f"operations/{row['id']}.json"]),
            }
            for row in request["requested_reads"]
        ],
        "accounting": {
            **accounting_policy(),
            "total_fixture_payload_bytes": sum(len(data) for data in inputs.reads.files.values()),
        },
        "coverage": coverage_rows(),
        "unresolved_claims": unresolved_claims(),
        "limitations": list(LIMITATIONS),
        "non_goals": list(NON_GOALS),
        "blockers": blocker_rows(),
        "authority": authority(),
    }


def manifest_document(env: Environment, inputs: Inputs, files: dict) -> dict:
    d = deploy()
    return {
        "schema": 1,
        "kind": MANIFEST_KIND,
        "format_version": VERSION,
        "session_contract_sha256": env.contract_sha256,
        "capture_contract_sha256": env.collector.contract_sha256,
        "preflight_contract_sha256": env.collector.preflight_sha256,
        "request_sha256": inputs.request_sha256,
        "reads_sha256": inputs.reads.sha256,
        "transport": TRANSPORT,
        "synthetic": True,
        "live": False,
        "files": [
            {"path": path, "sha256": d.sha256_bytes(files[path]), "bytes": len(files[path])}
            for path in sorted(files, key=lambda p: p.encode())
        ],
    }


def rehearsal_spec(env: Environment, inputs: Inputs) -> list:
    d = deploy()
    results = adapt(env, inputs)
    capture = capture_files(env, inputs, results)
    files = {f"capture/{path}": data for path, data in capture.items()}
    files["rehearsal.json"] = d.render_json(rehearsal_document(env, inputs, results, capture))
    files["manifest.json"] = d.render_json(manifest_document(env, inputs, files))
    files["SHA256SUMS"] = sums_of(files)
    if sorted(files) != output_files():
        raise SessionError("rehearsal output closure differs from the contract")
    spec = [("capture", "dir", 0o755, None), ("capture/operations", "dir", 0o755, None)]
    spec += [(path, "file", 0o644, data) for path, data in files.items()]
    spec.sort(key=lambda item: item[0].encode("utf-8"))
    return spec


def capture_digest(spec: list) -> str:
    """The digest of the capture tree inside SPEC, as the collector would list its files."""
    capture = {
        path[len("capture/"):]: data for path, kind, mode, data in spec
        if kind == "file" and path.startswith("capture/")
    }
    return sha256_hex(sums_of(capture))


def result_summary(status: str, env: Environment, inputs: Inputs, spec: list) -> dict:
    d = deploy()
    sums = next(data for path, kind, mode, data in spec if path == "SHA256SUMS")
    return {
        "status": status,
        "evidence_level": EVIDENCE_LEVEL,
        "rehearsal_sha256": d.sha256_bytes(sums),
        "request_sha256": inputs.request_sha256,
        "reads_sha256": inputs.reads.sha256,
        "capture_sha256": capture_digest(spec),
        "operation_count": len(OPERATION_IDS),
        "blocker_count": len(d.BLOCKERS),
        "synthetic": True,
        "live": False,
        "executes": False,
        "kit_snapshot_reverified": False,
        **authority(),
    }


# --- plan -----------------------------------------------------------------------


def plan_document(env: Environment, request: dict, request_sha256: str) -> dict:
    d = deploy()
    reads = {row["id"]: row for row in request["requested_reads"]}
    return {
        "schema": 1,
        "kind": PLAN_KIND,
        "format_version": VERSION,
        "session_contract_sha256": env.contract_sha256,
        "request_sha256": request_sha256,
        "transport": TRANSPORT,
        "evidence_level": EVIDENCE_LEVEL,
        "implementation": implementation_binding(),
        "synthetic": True,
        "live": False,
        "executes": False,
        "kit_snapshot_reverified": False,
        "remote_commands": [],
        "redaction": dict(request["redaction"]),
        "input_closure": {
            "manifest": MANIFEST_PATH,
            "manifest_max_bytes": MANIFEST_MAX_BYTES,
            "files": [
                {key: row[key] for key in ("path", "operation", "parser", "format", "min_bytes", "max_bytes")}
                for row in INPUT_FILES
            ],
            "entries_max": READS_ENTRIES,
            "total_max_bytes": TOTAL_READS_BYTES,
            "json_depth_max": JSON_DEPTH,
            "extra_entries": "reject",
        },
        "operations": [
            {
                "id": operation,
                "parser": OPERATION_PARSERS[operation],
                "inputs": list(OPERATION_INPUTS[operation]),
                "max_bytes": reads[operation]["max_bytes"],
                "emits": list(reads[operation]["emits"]),
                "never_emits": list(reads[operation]["never_emits"]),
            }
            for operation in OPERATION_IDS
        ],
        "output_closure": output_closure(),
        "accounting": accounting_policy(),
        "coverage": coverage_rows(),
        "unresolved_claims": unresolved_claims(),
        "limitations": list(LIMITATIONS),
        "non_goals": list(NON_GOALS),
        "human_approval_required": True,
        "blockers": list(d.BLOCKERS),
        "authority": authority(),
    }


# --- untrusted rehearsal trees --------------------------------------------------
# A rehearsal tree under verification is untrusted: its names, links and special
# files must never reach a diagnostic. Every failure from the shared tree reader,
# the entry comparison and the collector's capture read becomes a fixed code here.

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


def walk_rehearsal(descriptor: int, label: str, **options):
    d = deploy()
    try:
        return d.walk_tree(descriptor, d.STAGE_LIMITS, allow_symlinks=False, label=label, **options)
    except (d.DeploymentError, OSError) as error:
        raise SessionError(
            f"{label} tree failed safe inspection (code {tree_failure_code(str(error))})"
        ) from None


def diff_rehearsal(actual: list, expected: list, label: str) -> None:
    """Compare entries; only the expected side's own paths may be named."""
    have = {entry.path: entry for entry in actual}
    want = {entry.path: entry for entry in expected}
    extra = len(set(have) - set(want))
    if extra:
        raise SessionError(f"{label} has {extra} unexpected paths (names withheld)")
    missing = sorted(set(want) - set(have))
    if missing:
        raise SessionError(f"{label} is missing paths: {missing}")
    for path in sorted(want):
        if have[path] != want[path]:
            raise SessionError(f"{label} differs at {path}")


def reread_capture(path: str, env: Environment, request: dict, request_sha256: str, label: str):
    """The collector's own capture read, with its diagnostics replaced by one fixed code."""
    c, d = collect(), deploy()
    try:
        return c.read_capture(path, env.collector, request, request_sha256)
    except (c.CollectError, d.DeploymentError, OSError, ValueError):
        raise SessionError(f"{label} capture was refused by the collector's read (code capture-rejected)") from None


# --- commands -------------------------------------------------------------------


def command_plan(env: Environment, args) -> dict:
    request, request_sha256, _ids = read_request(args.request, env)
    return plan_document(env, request, request_sha256)


def command_verify_plan(env: Environment, args) -> dict:
    d = deploy()
    request, request_sha256, _ids = read_request(args.request, env)
    expected = plan_document(env, request, request_sha256)
    raw = d.read_file(args.plan, "session plan", d.MAX_SMALL_BYTES)
    document = d.strict_json(raw, "session plan")
    collect().check_json_depth(document, "session plan", PLAN_DEPTH)
    if raw != d.render_json(document):
        raise SessionError("session plan is not canonical")
    if not collect().kernel().strict_equal(document, expected):
        raise SessionError("session plan differs from the request")
    return {
        "status": "verified",
        "request_sha256": request_sha256,
        "operation_count": len(OPERATION_IDS),
        "synthetic": True,
        "live": False,
        "executes": False,
        **authority(),
    }


def command_rehearse(env: Environment, args) -> dict:
    d = deploy()
    for path in (args.request, args.reads):
        if d.paths_overlap(args.out, path):
            raise SessionError("output path overlaps an input")
    inputs = gather(args, env)
    spec = rehearsal_spec(env, inputs)
    expected = d.spec_entries(spec)
    protected = [args.request, args.reads]
    protected_ids = frozenset(inputs.request_ids | inputs.reads.directory_ids)

    def verify_built(temporary_path: str, descriptor: int) -> None:
        again = gather(args, env)
        if rehearsal_spec(env, again) != spec:
            raise SessionError("request or reads changed during the rehearsal")
        tree = walk_rehearsal(descriptor, "rehearsal")
        diff_rehearsal(tree.entries, expected, "rehearsal")
        built = reread_capture(
            f"{temporary_path}/capture", env, again.request, again.request_sha256, "built"
        )
        if built.capture_sha256 != capture_digest(spec):
            raise SessionError("built capture differs from the rehearsed capture")

    d.publish(args.out, protected, protected_ids, spec, verify_built)
    return result_summary("rehearsed", env, inputs, spec)


def command_verify_rehearsal(env: Environment, args) -> dict:
    d = deploy()
    inputs = gather(args, env)
    spec = rehearsal_spec(env, inputs)
    if any(d.paths_overlap(args.rehearsal, path) for path in (args.request, args.reads)):
        raise SessionError("rehearsal overlaps an input")
    descriptor, identity = d.open_trusted_artifact(args.rehearsal, "rehearsal")
    try:
        tree = walk_rehearsal(descriptor, "rehearsal", keep_data=True, trusted_ownership=True)
    finally:
        os.close(descriptor)
    diff_rehearsal(tree.entries, d.spec_entries(spec), "rehearsal")
    if tree.directory_ids & (inputs.request_ids | inputs.reads.directory_ids):
        raise SessionError("rehearsal aliases an input tree")
    built = reread_capture(
        f"{args.rehearsal}/capture", env, inputs.request, inputs.request_sha256, "rehearsed"
    )
    if built.capture_sha256 != capture_digest(spec):
        raise SessionError("rehearsed capture differs from the recomputed capture")
    d.recheck_trusted_artifact(args.rehearsal, identity, "rehearsal")
    again = gather(args, env)
    if rehearsal_spec(env, again) != spec:
        raise SessionError("request or reads changed during verification")
    return result_summary("verified", env, inputs, spec)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("show", help="verify and print the committed session contract")
    commands.add_parser(
        "derive-contract",
        help="print the contract derived from the pinned upstream contracts; writes nothing",
    )
    plan = commands.add_parser("plan", help="print the value-free rehearsal plan")
    plan.add_argument("--request", required=True)
    verify_plan = commands.add_parser("verify-plan", help="recompute a saved plan")
    verify_plan.add_argument("--request", required=True)
    verify_plan.add_argument("--plan", required=True)
    rehearse = commands.add_parser("rehearse", help="adapt synthetic reads into a capture fixture")
    rehearse.add_argument("--request", required=True)
    rehearse.add_argument("--reads", required=True)
    rehearse.add_argument("--out", required=True)
    verify = commands.add_parser("verify-rehearsal", help="recompute a rehearsal")
    verify.add_argument("--request", required=True)
    verify.add_argument("--reads", required=True)
    verify.add_argument("--rehearsal", required=True)
    return parser


def main(argv: list[str] | None = None, contracts_root: Path | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        c = collect()
    except SessionError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    p = c.preflight()
    d = p.deploy()
    s = p.snapshot()
    root = contracts_root or REPO
    try:
        if args.command == "derive-contract":
            # No committed session contract is read: the pinned upstream contracts and this
            # source alone derive the bytes that `show` verifies. Nothing is written or authorized.
            result = expected_session_contract(c.load_environment(root))
        else:
            env = load_environment(root)
            if args.command == "show":
                result = env.contract
            elif args.command == "plan":
                result = command_plan(env, args)
            elif args.command == "verify-plan":
                result = command_verify_plan(env, args)
            elif args.command == "rehearse":
                result = command_rehearse(env, args)
            else:
                result = command_verify_rehearsal(env, args)
    except (SessionError, c.CollectError, p.PreflightError, s.SnapshotError, *d.handled_errors()) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
