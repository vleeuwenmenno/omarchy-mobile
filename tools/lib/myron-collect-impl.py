# SPDX-License-Identifier: MIT
"""Validate bounded pre-captured Myron fixtures against a preflight request.

Offline and structural only: the one transport is a local, trusted,
pre-captured fixture tree. Nothing here reads a phone or clears a blocker.

This file is not run directly. tools/myron-collect captures its bytes once and
executes them in its own namespace (so `__file__` is the loader's), and passes
the digest of those same bytes as CAPTURED_IMPLEMENTATION_SHA256."""

from __future__ import annotations

import os
import sys
import argparse
import copy
import hashlib
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import re
import stat

sys.dont_write_bytecode = True

VERSION = "0.2.0"
REPO = Path(__file__).resolve().parent.parent
PREFLIGHT_TOOL = REPO / "tools/myron-preflight"
PINNED_VERSIONS = {"preflight": "0.3.0", "snapshot": "0.2.0", "deployment": "0.4.0"}
OPERATION_SCHEMA = 2  # every R1-R7 envelope; schema 1 and a mix of generations are refused
READ_DOMAIN = "fixture"  # the only domain: no hardware transport exists
ENVELOPE_KEYS = [
    "schema", "kind", "id", "request_sha256", "transport", "read_domain", "read_only",
    "bytes_read", "data",
]
BUDGET_KEYS = ["max_output_bytes", "max_fixture_input_bytes", "max_hardware_read_bytes"]
CAPTURE_CONTRACT_PATH = "device/myron/capture-contract.json"
PREFLIGHT_CONTRACT_PATH = "device/myron/preflight-contract.json"
CONTRACT_KIND = "myron-capture-collector-contract"
PLAN_KIND = "myron-capture-collection-plan"
CAPTURE_KIND = "myron-precaptured-fixture"
OPERATION_KIND = "myron-precaptured-operation"
EVIDENCE_KIND = "myron-capture-fixture-evidence"
TRANSPORT = "external-precaptured-fixture"
EVIDENCE_LEVEL = "artifact-structure-only"
EVIDENCE_STATUS = "fixture-evidence-recorded"
TOTAL_CAPTURE_BYTES = 4 * 1024 * 1024
MAX_FILE_BYTES = 1024 * 1024
CAPTURE_ENTRIES = 16
CAPTURE_DEPTH = 2
MAX_DEPTH = 8
PLAN_MAX_DEPTH = 32  # a saved plan embeds the typed policy registry
POLICY_SPEC_DEPTH = 12  # the deepest typed spec (R3 range rows) nests 5 levels below its field
MAX_MODULES = 256
MEBIBYTE = 1024 * 1024
HEX256 = re.compile(r"[0-9a-f]{64}")
PARTITION_NAME = re.compile(r"[a-z0-9_]{1,36}")
MODULE_NAME = re.compile(r"[A-Za-z0-9_-]{1,56}")
TAINT_FLAGS = re.compile(r"[A-Z]{0,8}")
IMAGE_NAME = re.compile(
    r"(boot|init_boot|vendor_boot|vendor_kernel_boot|dtbo|recovery)(_a|_b)?"
)
IDENTIFIER_PATTERNS = (
    re.compile(r"(?i)(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}"),
    re.compile(r"(?i)[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"),
    re.compile(r"[0-9]{14,}"),
    re.compile(r"(?i)[0-9a-f]{24,}"),
)
FILESYSTEMS = ["ext4", "f2fs", "erofs", "btrfs", "xfs"]
MOUNT_OPTIONS = [
    "discard", "errors=remount-ro", "noatime", "nodev", "noexec", "nosuid", "relatime",
    "ro", "rw",
]
STATUS_TEXT = (
    "Omarchy Mobile Myron pre-captured fixture evidence (offline only)\n"
    "\n"
    "evidence_level: artifact-structure-only\n"
    "live: false\n"
    "executes: false\n"
    "hardware_read_authorized: false\n"
    "deployment_authorized: false\n"
    "This artifact records that a pre-captured fixture tree matched the bounded\n"
    "schemas of one preflight request. It is not live evidence, not approval, and\n"
    "clears no blocker. Every blocker stays missing; a human decides what follows.\n"
).encode("ascii")


class CollectError(Exception):
    """Capture input or evidence differs from the reviewed collector contract."""


_preflight = None


def preflight():
    global _preflight
    if _preflight is None:
        try:
            loader = importlib.machinery.SourceFileLoader("myron_preflight", str(PREFLIGHT_TOOL))
            spec = importlib.util.spec_from_loader(loader.name, loader)
            module = importlib.util.module_from_spec(spec)
            loader.exec_module(module)
        except (OSError, SyntaxError) as error:
            raise CollectError(f"cannot load the preflight verifier: {error}") from error
        found = {
            "preflight": module.VERSION,
            "snapshot": module.snapshot().VERSION,
            "deployment": module.deploy().VERSION,
        }
        if found != PINNED_VERSIONS:
            raise CollectError(f"unsupported verifier versions {found}; expected {PINNED_VERSIONS}")
        _preflight = module
    return _preflight


def deploy():
    return preflight().deploy()


def kernel():
    return deploy().kernel()


def authority() -> dict:
    return preflight().authority()


def blocker_rows() -> list[dict]:
    return [{"blocker": blocker, "state": "missing"} for blocker in deploy().BLOCKERS]


def status_document() -> dict:
    p = preflight()
    return {
        "artifact": EVIDENCE_KIND,
        "blockers": list(deploy().BLOCKERS),
        **p.authority(),
    }


def capture_limits():
    return deploy().Limits(CAPTURE_ENTRIES, CAPTURE_DEPTH, MAX_FILE_BYTES, TOTAL_CAPTURE_BYTES)


# --- policy registry ------------------------------------------------------------
# One typed registry holds every validation constant (patterns, enums, bounds,
# exclusions, per-operation field types). The validators, the collection plan and
# the capture contract all read it, so a policy change cannot skip the contract.


def _enum(values) -> dict:
    return {"type": "enum", "values": list(values)}


def _int(low: int, high: int) -> dict:
    return {"type": "int", "min": low, "max": high}


def _int_enum(values) -> dict:
    return {"type": "int_enum", "values": list(values)}


def _bool(const=None) -> dict:
    return {"type": "bool"} if const is None else {"type": "bool", "const": const}


def _text(pattern) -> dict:
    return {"type": "text", "pattern": pattern.pattern}


def _hash() -> dict:
    return {"type": "hash", "pattern": HEX256.pattern}


def _identity(source: str, pattern=None) -> dict:
    spec = {"type": "identity", "source": source}
    if pattern is not None:
        spec["pattern"] = pattern.pattern
    return spec


def _null() -> dict:
    return {"type": "null"}


def _nullable(spec: dict) -> dict:
    return {"type": "nullable", "of": spec}


def _list(item: dict, low: int, high: int, sorted_unique: bool = False) -> dict:
    return {
        "type": "list", "item": item, "min": low, "max": high, "sorted_unique": sorted_unique,
    }


def _object(fields: dict) -> dict:
    """An exact-key nested object: every field required, no other key accepted."""
    return {"type": "object", "fields": fields}


def _rows(row: dict, low: int, high: int, key) -> dict:
    """Rows of exact-key objects. KEY names the field (or the list of fields) that every
    row set must be unique and sorted by; None leaves ordering to the caller."""
    return {"type": "rows", "row": row, "min": low, "max": high, "sorted_unique_by": key}


def _null_together(*fields: str) -> dict:
    return {"type": "null_together", "fields": list(fields)}


def row_fields(spec: dict) -> list:
    """Every field a row carries."""
    return list(spec["row"])


def row_key_fields(spec: dict) -> list:
    key = spec["sorted_unique_by"]
    return [] if key is None else [key] if type(key) is str else list(key)


def _container(rows_field: str, spec: dict) -> dict:
    return {"rows_field": rows_field, "row_fields": row_fields(spec)}


def _operation_policy(operation_id: str, fields: dict, container=None, constraints=(), **extra) -> dict:
    return {
        "input_path": operation_path(operation_id),
        "fields": fields,
        "container": container,
        "constraints": list(constraints),
        **extra,
    }


R1_ID = "R1-identity-and-slot"
R2_ID = "R2-gpt-and-recovery-inventory"
R3_ID = "R3-boot-image-headers"
R4_ID = "R4-dtb-dtbo-selection"
R5_ID = "R5-module-load-order"
R6_ID = "R6-storage-and-mount-model"
R7_ID = "R7-kernel-identity-revalidation"
SLOTS = ["a", "b"]
SLOT_SUFFIXES = ["_a", "_b"]
PARTITION_ROW = {
    "partition_name": _text(PARTITION_NAME),
    "size_bytes": _int(0, 2**50),
    "bootable_flag": _bool(),
    "slot_suffix": _enum(["", "_a", "_b"]),
}
PARTITION_ROWS = _rows(PARTITION_ROW, 1, 128, "partition_name")
# --- R3 boot image schema (generation R3, Phase A: schema only, no image parser) -----
# One row per supported partition name; `image` is null where R2 lacks the name (that is
# absence from the bound inventory, not proof the physical device has no such partition),
# else a nested exact-key image summary. Every value in it is a claim of the fixture: no
# binary parser exists in this phase, so no offset, size or hash is recomputed from bytes.
MAX_IMAGE_BYTES = 16 * MEBIBYTE
MAX_VENDOR_FRAGMENTS = 64
MAX_DT_ENTRIES = 256
MAX_COVERAGE_RANGES = 32
MIN_HEADER_BYTES = 32
MAX_HEADER_BYTES = 2128
MAX_TABLE_BYTES = 8192
PAGE_SIZES = [2048, 4096, 8192, 16384]
RAMDISK_TYPES = [0, 1, 2, 3]
IMAGE_ROLES = ["boot", "init_boot", "vendor_boot", "vendor_kernel_boot", "dtbo", "recovery"]
IMAGE_SUFFIXES = ["", "_a", "_b"]
IMAGE_FORMATS = ["android-boot", "android-vendor-boot", "android-dt-table"]
COMPONENT_ROLES = [
    "kernel", "ramdisk", "second", "recovery_dtbo", "dtb", "boot_signature", "vendor_ramdisk",
    "vendor_ramdisk_fragment", "bootconfig", "dt_entry",
]
TABLE_ROLES = ["vendor_ramdisk_table", "dt_entry_table"]
COVERAGE_KINDS = ["metadata-only", "full-image"]
FRAGMENT_ROLE = "vendor_ramdisk_fragment"
TABLE_COUNT = "table-entries"  # a slot whose count is the table's entry_count
R3_HEADER = _object({
    "offset": _int(0, 0),
    "size_bytes": _int(MIN_HEADER_BYTES, MAX_HEADER_BYTES),
    "sha256": _hash(),
})
R3_COMPONENT_ROW = {
    "role": _enum(COMPONENT_ROLES),
    "index": _int(0, MAX_DT_ENTRIES - 1),
    "offset": _int(0, MAX_IMAGE_BYTES),
    "size_bytes": _int(0, MAX_IMAGE_BYTES),
    "sha256": _nullable(_hash()),
    "ramdisk_type": _nullable(_int(0, 3)),
}
R3_COMPONENTS = _rows(R3_COMPONENT_ROW, 1, MAX_DT_ENTRIES, ["role", "index"])
R3_TABLE = _nullable(_object({
    "role": _enum(TABLE_ROLES),
    "offset": _int(0, MAX_IMAGE_BYTES),
    "size_bytes": _int(0, MAX_TABLE_BYTES),
    "sha256": _hash(),
    "entry_size": _int_enum([108, 32]),
    "entry_count": _int(0, MAX_DT_ENTRIES),
}))
R3_RANGE_ROW = {
    "index": _int(0, MAX_COVERAGE_RANGES - 1),
    "offset": _int(0, MAX_IMAGE_BYTES - 1),
    "size_bytes": _int(1, MAX_IMAGE_BYTES),
}
R3_COVERAGE = _object({
    "kind": _enum(COVERAGE_KINDS),
    "ranges": _rows(R3_RANGE_ROW, 1, MAX_COVERAGE_RANGES, "index"),
    "covered_bytes": _int(1, MAX_IMAGE_BYTES),
})
R3_IMAGE = _object({
    "format": _enum(IMAGE_FORMATS),
    "version": _int(0, 4),
    "page_size": _int_enum(PAGE_SIZES),
    "os_version": _nullable(_int(0, 2**32 - 1)),
    "size_bytes": _int(MIN_HEADER_BYTES, MAX_IMAGE_BYTES),
    "sha256": _nullable(_hash()),
    "header": R3_HEADER,
    "components": R3_COMPONENTS,
    "table": R3_TABLE,
    "coverage": R3_COVERAGE,
})
IMAGE_ROW = {
    "partition_name": _text(IMAGE_NAME),
    "role": _enum(IMAGE_ROLES),
    "image": _nullable(R3_IMAGE),
}
IMAGE_PARTITION_NAMES = sorted(role + suffix for role in IMAGE_ROLES for suffix in IMAGE_SUFFIXES)
IMAGE_ROWS = _rows(IMAGE_ROW, len(IMAGE_PARTITION_NAMES), len(IMAGE_PARTITION_NAMES), "partition_name")


def _slot(role: str, count=1) -> dict:
    return {"role": role, "count": count}


def _layout(fmt, version, header_bytes, slots, fixed_page_size=None, table=None) -> dict:
    return {
        "format": fmt, "version": version, "header_bytes": header_bytes,
        "fixed_page_size": fixed_page_size, "slots": slots, "table": table,
    }


def r3_profile() -> dict:
    """The one supported R3 profile: what each format, version and partition role admits."""
    boot = "android-boot"
    vendor = "android-vendor-boot"
    dt = "android-dt-table"
    kernel_ramdisk = [_slot("kernel"), _slot("ramdisk")]
    return {
        "row_count": len(IMAGE_PARTITION_NAMES),
        "suffixes": list(IMAGE_SUFFIXES),
        "partitions": [
            {"role": "boot", "format": boot, "versions": [0, 1, 2, 3, 4]},
            {"role": "init_boot", "format": boot, "versions": [4]},
            {"role": "vendor_boot", "format": vendor, "versions": [3, 4]},
            {"role": "vendor_kernel_boot", "format": vendor, "versions": [3, 4]},
            {"role": "dtbo", "format": dt, "versions": [0]},
            {"role": "recovery", "format": boot, "versions": [0, 1, 2, 3, 4]},
        ],
        "page_sizes": list(PAGE_SIZES),
        "max_image_bytes": MAX_IMAGE_BYTES,
        "max_vendor_fragments": MAX_VENDOR_FRAGMENTS,
        "max_dt_entries": MAX_DT_ENTRIES,
        "max_coverage_ranges": MAX_COVERAGE_RANGES,
        "ramdisk_types": list(RAMDISK_TYPES),
        "fragment_role": FRAGMENT_ROLE,
        "init_boot_kernel_bytes": 0,
        "empty_bytes_sha256": hashlib.sha256(b"").hexdigest(),
        "layouts": [
            _layout(boot, 0, 1632, [*kernel_ramdisk, _slot("second")]),
            _layout(boot, 1, 1648, [*kernel_ramdisk, _slot("second"), _slot("recovery_dtbo")]),
            _layout(boot, 2, 1660, [*kernel_ramdisk, _slot("second"), _slot("recovery_dtbo"),
                                    _slot("dtb")]),
            _layout(boot, 3, 1580, kernel_ramdisk, fixed_page_size=4096),
            _layout(boot, 4, 1584, [*kernel_ramdisk, _slot("boot_signature")],
                    fixed_page_size=4096),
            _layout(vendor, 3, 2112, [_slot("vendor_ramdisk"), _slot("dtb")]),
            _layout(vendor, 4, 2128,
                    [_slot(FRAGMENT_ROLE, TABLE_COUNT), _slot("dtb"), _slot("bootconfig")],
                    table={"role": "vendor_ramdisk_table", "entry_bytes": 108,
                           "min_entries": 0, "max_entries": MAX_VENDOR_FRAGMENTS}),
            _layout(dt, 0, 32, [_slot("dt_entry", TABLE_COUNT)],
                    table={"role": "dt_entry_table", "entry_bytes": 32,
                           "min_entries": 1, "max_entries": MAX_DT_ENTRIES}),
        ],
    }
# The board id and revision are null together (no board selected) or set together.
DTB_FIELDS = {
    "dtb_count": _int(0, 64),
    "selected_board_id": _nullable(_int(0, 2**32 - 1)),
    "selected_board_revision": _nullable(_int(0, 2**32 - 1)),
    "dtbo_entry_count": _int(0, 256),
    "compatible_prefix": _identity("device.compatible"),
    "selection_source": _enum(["bootconfig", "device-tree", "dtbo-header"]),
}
DTB_CONSTRAINTS = [_null_together("selected_board_id", "selected_board_revision")]


def policy_registry() -> dict:
    registry = copy.deepcopy(_policy_registry())  # callers get a copy, never the constants
    check_policy(registry)
    return registry


def _policy_registry() -> dict:
    registry = _policy_registry_base()
    # The three budgets come from the preflight request constants, the one place they are
    # declared; the validator refuses a request row that differs from them.
    for row in preflight().requested_reads():
        registry["operations"][row["id"]]["budgets"] = {key: row[key] for key in BUDGET_KEYS}
    return registry


def _policy_registry_base() -> dict:
    p = preflight()
    return {
        "capture_limits": {
            "entries": CAPTURE_ENTRIES,
            "depth": CAPTURE_DEPTH,
            "file_bytes": MAX_FILE_BYTES,
            "total_bytes": TOTAL_CAPTURE_BYTES,
            "json_depth": MAX_DEPTH,
        },
        "operation_envelope": {
            "schema": OPERATION_SCHEMA,
            "read_domain": READ_DOMAIN,
            "keys": list(ENVELOPE_KEYS),
            "budget_keys": list(BUDGET_KEYS),
            "bytes_read": "fixture-payload-acquisition-within-max_fixture_input_bytes",
            "hardware_bytes_read": "none-no-hardware-transport-exists",
        },
        "exclusions": {
            "never_emits": list(p.NEVER_EMITS),
            "match": "token-run-boundary",
            "hash_values": HEX256.pattern,
            "hash_scope": "declared-hash-fields-only",
            "document_hash_paths": {
                "manifest": [
                    ["contract_sha256"], ["request_sha256"], ["operations", "*", "sha256"],
                ],
                "operation": [["request_sha256"]],
            },
            "identifier_patterns": [pattern.pattern for pattern in IDENTIFIER_PATTERNS],
        },
        "operations": {
            R1_ID: _operation_policy(R1_ID, {
                "codename": _identity("device.codename"),
                "soc": _identity("device.soc"),
                "compatible_prefix": _identity("device.compatible"),
                "current_slot": _enum(SLOTS),
                "slot_suffix": _enum(SLOT_SUFFIXES),
                "verified_boot_state": _enum(["green", "yellow", "orange", "red"]),
                "sources_agree": _bool(True),
            }, rules=["slot-suffix-matches-slot"]),
            R2_ID: _operation_policy(R2_ID, {
                "partitions": PARTITION_ROWS,
                "recovery_present": _bool(),
            }, _container("partitions", PARTITION_ROWS),
                recovery_pattern=r"recovery(_a|_b)?",
                rules=["slot-suffix-matches-name", "recovery-flag-matches-inventory"]),
            R3_ID: _operation_policy(R3_ID, {
                "images": IMAGE_ROWS,
            }, _container("images", IMAGE_ROWS),
                rules=list(R3_RULES), cross_rules=list(R3_CROSS_RULES), profile=r3_profile()),
            R4_ID: _operation_policy(R4_ID, DTB_FIELDS, constraints=DTB_CONSTRAINTS),
            R5_ID: _operation_policy(R5_ID, {
                "module_names": _list(_text(MODULE_NAME), 0, MAX_MODULES),
                "load_order_index": _list(_int(0, MAX_MODULES), 0, MAX_MODULES),
                "taint_flags": _list(_text(TAINT_FLAGS), 0, MAX_MODULES),
                "order_matches_declared": _bool(),
            }, reference_module_order=list(deploy().REFERENCE_MODULE_ORDER),
                rules=["parallel-lists-match-names", "unique-names", "sequential-index",
                       "order-claim-recomputed"]),
            R6_ID: _operation_policy(R6_ID, {
                "root_source_gpt_name": _text(PARTITION_NAME),
                "filesystem_type": _enum(FILESYSTEMS),
                "mount_options": _list(_enum(MOUNT_OPTIONS), 0, 16, True),
                "block_size": _int_enum([1024, 2048, 4096, 8192, 16384, 65536]),
                "rounded_total_bytes": _int(1, 2**50),
                "rounded_free_bytes": _int(0, 2**50),
            }, rounding_bytes=MEBIBYTE, rules=["sizes-rounded", "free-not-above-total"]),
            R7_ID: _operation_policy(R7_ID, {
                "kernel_release": _identity("kernel.release"),
                "notes_sha256": _identity("kernel.notes_sha256", HEX256),
                "allowlisted_cmdline": {"type": "request-allowlist"},
                "allowlisted_bootconfig_keys": {"type": "request-allowlist"},
            }, allowlist_unknown_keys="reject", rules=["cross-checked-against-r1"]),
        },
    }


def identity_values(contracts) -> dict:
    reference = contracts.reference
    return {
        "device.codename": reference["device"]["codename"],
        "device.compatible": reference["device"]["compatible"],
        "device.soc": reference["device"]["soc"],
        "kernel.notes_sha256": reference["kernel"]["notes_sha256"],
        "kernel.release": reference["kernel"]["release"],
    }


# --- policy consistency ---------------------------------------------------------


def policy_error(message: str):
    raise CollectError(f"policy registry is inconsistent: {message}")


SORT_KEY_TYPES = ("text", "int", "enum", "int_enum")


def check_spec_shape(spec, where: str, depth: int = 0) -> None:
    """A typed spec is well formed: known type, ordered bounds, nested specs sound.

    Recursion is bounded by POLICY_SPEC_DEPTH, so a hostile or drifted registry cannot
    nest the check without limit."""
    if depth > POLICY_SPEC_DEPTH:
        policy_error(f"{where} nests too deeply")
    if type(spec) is not dict or "type" not in spec:
        policy_error(f"{where} is not a typed spec")
    kind = spec["type"]
    if kind in ("int", "list", "rows") and spec["min"] > spec["max"]:
        policy_error(f"{where} has min above max")
    if kind == "list":
        check_spec_shape(spec["item"], f"{where} item", depth + 1)
    elif kind == "nullable":
        check_spec_shape(spec["of"], f"{where} value", depth + 1)
        if spec["of"]["type"] in ("null", "nullable"):
            policy_error(f"{where} nests a null type in a nullable")
    elif kind == "object":
        fields = spec.get("fields")
        if type(fields) is not dict or not fields or any(type(name) is not str for name in fields):
            policy_error(f"{where} object has no named fields")
        for name, field in fields.items():
            check_spec_shape(field, f"{where} {name}", depth + 1)
    elif kind == "rows":
        row = spec["row"]
        if type(row) is not dict or not row:
            policy_error(f"{where} rows have no row fields")
        for name, field in row.items():
            check_spec_shape(field, f"{where} {name}", depth + 1)
        names = row_key_fields(spec)
        if len(set(names)) != len(names) or any(name not in row for name in names):
            policy_error(f"{where} sort key names unknown or repeated row fields")
        if any(row[name]["type"] not in SORT_KEY_TYPES for name in names):
            policy_error(f"{where} sort key is not a sortable scalar field")
    elif kind not in (
        "enum", "int", "int_enum", "bool", "text", "hash", "identity", "null", "request-allowlist"
    ):
        policy_error(f"{where} has unknown type {kind}")


def check_constraint_shape(constraint: dict, fields: dict, where: str) -> None:
    """Constraints name known fields of the right type, so none can dangle."""
    kind = constraint["type"]
    if kind == "null_together":
        names = constraint["fields"]
        if len(names) < 2 or set(names) - set(fields):
            policy_error(f"{where} null_together names unknown fields")
        for name in names:
            if fields[name]["type"] not in ("nullable", "null"):
                policy_error(f"{where} null_together field {name} cannot be null")
    else:
        policy_error(f"{where} has unknown constraint {kind}")


def check_budgets_shape(budgets, where: str) -> None:
    if type(budgets) is not dict or set(budgets) != set(BUDGET_KEYS):
        policy_error(f"{where} budgets differ from the three separate bounds")
    if any(type(value) is not int or value < 1 for value in budgets.values()):
        policy_error(f"{where} budgets are not positive integers")


def check_r3_policy_shape(policy: dict, where: str) -> None:
    """The serialized R3 rules and profile are exactly what the validator implements and the
    typed bounds admit: a published rule with no implementation, or a profile constant that
    contradicts a typed bound, is refused."""
    if sorted(policy["rules"]) != sorted(R3_RULES) or len(set(policy["rules"])) != len(R3_RULES):
        policy_error(f"{where} rules differ from the implemented semantic rules")
    if sorted(policy["cross_rules"]) != sorted(R3_CROSS_RULES) or (
        len(set(policy["cross_rules"])) != len(R3_CROSS_RULES)
    ):
        policy_error(f"{where} cross rules differ from the implemented cross rules")
    profile = policy["profile"]
    rows = policy["fields"]["images"]
    image = rows["row"]["image"]["of"]["fields"]
    names = [entry["role"] + suffix for entry in profile["partitions"] for suffix in profile["suffixes"]]
    if len(set(names)) != len(names) or profile["row_count"] != len(names):
        policy_error(f"{where} profile partitions are not unique or miscounted")
    if not rows["min"] == rows["max"] == profile["row_count"]:
        policy_error(f"{where} row count differs from the profile")
    if profile["empty_bytes_sha256"] != hashlib.sha256(b"").hexdigest():
        policy_error(f"{where} empty-bytes hash is not the SHA-256 of empty bytes")
    if image["size_bytes"]["max"] != profile["max_image_bytes"]:
        policy_error(f"{where} image size bound differs from the profile")
    if image["coverage"]["fields"]["ranges"]["max"] != profile["max_coverage_ranges"]:
        policy_error(f"{where} coverage range bound differs from the profile")
    if image["components"]["max"] != profile["max_dt_entries"] or (
        profile["max_vendor_fragments"] > profile["max_dt_entries"]
    ):
        policy_error(f"{where} component bound differs from the profile")
    if image["page_size"]["values"] != profile["page_sizes"]:
        policy_error(f"{where} page sizes differ from the profile")
    seen = set()
    for layout in profile["layouts"]:
        key = (layout["format"], layout["version"])
        if key in seen or not layout["slots"] or not MIN_HEADER_BYTES <= layout["header_bytes"] <= MAX_HEADER_BYTES:
            policy_error(f"{where} profile layout is repeated or unbounded")
        seen.add(key)
        roles = [slot["role"] for slot in layout["slots"]]
        if len(set(roles)) != len(roles) or set(roles) - set(COMPONENT_ROLES):
            policy_error(f"{where} profile layout names unknown or repeated component roles")
        table = layout["table"]
        counted = [slot for slot in layout["slots"] if slot["count"] == TABLE_COUNT]
        if (table is None) != (not counted) or (table is not None and len(counted) != 1):
            policy_error(f"{where} profile layout and table disagree about counted slots")
        if table is not None and not (
            0 <= table["min_entries"] <= table["max_entries"] <= profile["max_dt_entries"]
            and table["entry_bytes"] * table["max_entries"] <= MAX_TABLE_BYTES
            and table["role"] in TABLE_ROLES
        ):
            policy_error(f"{where} profile table bounds are inconsistent")
    for entry in profile["partitions"]:
        if any((entry["format"], version) not in seen for version in entry["versions"]):
            policy_error(f"{where} profile partition names an unknown format version")


def check_policy(registry: dict) -> None:
    """Refuse a registry whose parts contradict each other (nulls, nesting, containers)."""
    envelope = registry["operation_envelope"]
    if envelope["schema"] != OPERATION_SCHEMA or envelope["read_domain"] != READ_DOMAIN or (
        envelope["keys"] != ENVELOPE_KEYS
    ):
        policy_error("operation envelope differs from the reviewed generation")
    for operation_id, policy in registry["operations"].items():
        where = operation_id.split("-")[0]
        fields = policy["fields"]
        for name, spec in fields.items():
            check_spec_shape(spec, f"{where} {name}")
        for constraint in policy["constraints"]:
            check_constraint_shape(constraint, fields, where)
        check_budgets_shape(policy["budgets"], where)
        container = policy["container"]
        if container is not None:
            rows = fields.get(container["rows_field"])
            if rows is None or rows["type"] != "rows" or container["row_fields"] != row_fields(rows):
                policy_error(f"{where} container differs from its row spec")
        if operation_id == R3_ID:
            try:
                check_r3_policy_shape(policy, where)
            except (KeyError, TypeError, IndexError):
                policy_error(f"{where} R3 policy is not the reviewed shape")


# --- implementation pin ---------------------------------------------------------
# The typed registry carries every constant and the field/null/variant rules, but the
# cross-check logic is code. The contract therefore pins the SHA-256 of the exact
# bytes of tools/lib/myron-collect-impl.py that the loader captured and is executing.
# The digest comes from the loader, which hashed and compiled one read of the file;
# nothing here reopens the path, and the source never holds its own digest.


def implementation_binding() -> dict:
    if Path(__file__).resolve() != (REPO / "tools/myron-collect").resolve():
        raise CollectError("collector is not running from its pinned path")
    digest = globals().get("CAPTURED_IMPLEMENTATION_SHA256")
    if type(digest) is not str or not HEX256.fullmatch(digest):
        raise CollectError("collector was not loaded through its trusted loader")
    return {
        "algorithm": IMPLEMENTATION_ALGORITHM,
        "path": IMPLEMENTATION_PATH,
        "sha256": digest,
    }


# --- contract -------------------------------------------------------------------


def expected_capture_contract(preflight_contract_sha256: str, contracts) -> dict:
    p = preflight()
    return {
        "schema": 1,
        "kind": CONTRACT_KIND,
        "format_version": VERSION,
        "components": {
            "preflight_contract": {
                "path": PREFLIGHT_CONTRACT_PATH,
                "sha256": preflight_contract_sha256,
            }
        },
        "pinned_versions": dict(PINNED_VERSIONS),
        "implementation": implementation_binding(),
        "capture_schema": p.CAPTURE_SCHEMA,
        "transport": TRANSPORT,
        "capture": {
            "kind": CAPTURE_KIND,
            "operation_kind": OPERATION_KIND,
            "operation_schema": OPERATION_SCHEMA,
            "read_domain": READ_DOMAIN,
            "legacy_generations": "reject-no-adapters",
            "total_max_bytes": TOTAL_CAPTURE_BYTES,
            "extra_entries": "reject",
            "trusted_local_files_only": True,
        },
        "evidence": {
            "kind": EVIDENCE_KIND,
            "level": EVIDENCE_LEVEL,
            "status": EVIDENCE_STATUS,
            "live": False,
            "executes": False,
            "kit_snapshot_reverified": False,
            "remote_commands": [],
            "human_approval_required": True,
        },
        "identity": identity_values(contracts),
        "requested_operations": p.requested_reads(),
        "forbidden_operations": list(p.FORBIDDEN_OPERATIONS),
        "redaction": p.redaction_policy(),
        "policy": policy_registry(),
        "blockers": list(deploy().BLOCKERS),
        "authority": p.authority(),
    }


def load_capture_contract(
    root: Path, preflight_contract_sha256: str, contracts
) -> tuple[dict, bytes, str]:
    d = deploy()
    data = d.read_file(
        f"{root}/{CAPTURE_CONTRACT_PATH}", "capture contract", d.MAX_SMALL_BYTES
    )
    value = d.strict_json(data, "capture contract")
    expected = expected_capture_contract(preflight_contract_sha256, contracts)
    if not kernel().strict_equal(value, expected):
        raise CollectError("capture contract differs from its derived form")
    if data != d.render_json(expected):
        raise CollectError("capture contract is not canonical")
    return value, data, d.sha256_bytes(data)


class Environment:
    def __init__(self, contracts, preflight_bytes, preflight_sha256, contract, contract_bytes, contract_sha256):
        self.contracts = contracts
        self.identity = identity_values(contracts)
        self.preflight_bytes = preflight_bytes
        self.preflight_sha256 = preflight_sha256
        self.contract = contract
        self.contract_bytes = contract_bytes
        self.contract_sha256 = contract_sha256


def load_environment(root: Path) -> Environment:
    p = preflight()
    d = p.deploy()
    s = p.snapshot()
    contracts = d.load_contracts(root)
    _, _, snapshot_sha256 = s.load_snapshot_contract(root, contracts)
    _, preflight_bytes, preflight_sha256 = p.load_preflight_contract(
        root, contracts, snapshot_sha256
    )
    contract, contract_bytes, contract_sha256 = load_capture_contract(
        root, preflight_sha256, contracts
    )
    return Environment(
        contracts, preflight_bytes, preflight_sha256, contract, contract_bytes, contract_sha256
    )


# --- strict value checks --------------------------------------------------------


def need_dict(value, keys, label: str) -> dict:
    if type(value) is not dict or set(value) != set(keys):
        raise CollectError(f"{label} fields differ")
    return value


def need_int(value, label: str, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        raise CollectError(f"{label} is outside {low}..{high}")
    return value


def need_bool(value, label: str) -> bool:
    if type(value) is not bool:
        raise CollectError(f"{label} is not a boolean")
    return value


def need_enum(value, label: str, allowed) -> str:
    if type(value) is not str or value not in allowed:
        raise CollectError(f"{label} is not an allowed value")
    return value


def need_text(value, label: str, pattern) -> str:
    if (
        type(value) is not str
        or not value.isascii()
        or not value.isprintable()
        or not pattern.fullmatch(value)
    ):
        raise CollectError(f"{label} does not match its pattern")
    return value


def need_hash(value, label: str) -> str:
    return need_text(value, label, HEX256)


def need_list(value, label: str, low: int, high: int) -> list:
    if type(value) is not list or not low <= len(value) <= high:
        raise CollectError(f"{label} must hold {low}..{high} entries")
    return value


def need_sorted_unique(names: list, label: str) -> None:
    if names != sorted(set(names)):
        raise CollectError(f"{label} is not unique and sorted")


def reject_string(value: str, label: str) -> None:
    forbidden = set(preflight().NEVER_EMITS)
    # An excluded name is one or more whole tokens, so underscore, hyphen and
    # other separators all match (android_id, android-id, x_raw_payload_2).
    window = max(len(name.split("_")) for name in forbidden)
    tokens = [token for token in re.split(r"[^a-z0-9]+", value.lower()) if token]
    for start in range(len(tokens)):
        for end in range(start + 1, min(len(tokens), start + window) + 1):
            if "_".join(tokens[start:end]) in forbidden:
                raise CollectError(f"{label} names an excluded identifier or payload field")
    if any(pattern.search(value) for pattern in IDENTIFIER_PATTERNS):
        raise CollectError(f"{label} contains an identifier-shaped value")


def hash_paths_of(spec: dict, path: tuple) -> set:
    """Locations of the declared hash fields under one typed spec (`*` is a list index)."""
    kind = spec["type"]
    if kind == "hash" or (kind == "identity" and spec.get("pattern") == HEX256.pattern):
        return {path}
    if kind == "nullable":
        return hash_paths_of(spec["of"], path)
    if kind == "list":
        return hash_paths_of(spec["item"], path + ("*",))
    found = set()
    if kind == "object":
        for name, field in spec["fields"].items():
            found |= hash_paths_of(field, path + (name,))
    elif kind == "rows":
        for name, field in spec["row"].items():
            found |= hash_paths_of(field, path + ("*", name))
    return found


def leaf_paths(spec: dict, path: tuple) -> list:
    """Every leaf of one typed spec as a path (`*` is a row index); a nullable adds none."""
    kind = spec["type"]
    if kind == "nullable":
        return leaf_paths(spec["of"], path)
    if kind == "object":
        return [leaf for name, field in spec["fields"].items()
                for leaf in leaf_paths(field, path + (name,))]
    if kind == "rows":
        return [leaf for name, field in spec["row"].items()
                for leaf in leaf_paths(field, path + ("*", name))]
    return [path]


def field_paths(policy: dict, *, container_prefix: bool) -> list:
    """The sorted dotted leaf paths an operation may emit. Rows of the container field are
    named by their own fields (`partition_name`), or, with CONTAINER_PREFIX, under the
    container (`images.partition_name`); nested rows keep their `*` segment either way."""
    container = policy["container"]
    paths = []
    for name, spec in policy["fields"].items():
        if container is not None and name == container["rows_field"]:
            root = (name,) if container_prefix else ()
            for row_name, field in spec["row"].items():
                paths += leaf_paths(field, root + (row_name,))
        else:
            paths += leaf_paths(spec, (name,))
    return sorted(".".join(path) for path in paths)


def hash_scope(registry: dict, document: str, operation_id: str | None = None) -> frozenset:
    """The only places a bare 64-hex value is allowed: declared hash and identity-hash fields."""
    paths = {tuple(path) for path in registry["exclusions"]["document_hash_paths"][document]}
    if operation_id is not None:
        for name, spec in registry["operations"][operation_id]["fields"].items():
            paths |= hash_paths_of(spec, ("data", name))
    return frozenset(paths)


def reject_identifiers(value, label: str, hash_paths, path: tuple = (), depth: int = 0) -> None:
    """Refuse identifier-shaped strings anywhere in a document, keys included.

    A bare 64-hex string passes only at a path in HASH_PATHS."""
    if depth > MAX_DEPTH:
        raise CollectError(f"{label} nests too deeply")
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is str:
                reject_string(key, label)
            reject_identifiers(item, label, hash_paths, path + (key,), depth + 1)
    elif type(value) is list:
        for item in value:
            reject_identifiers(item, label, hash_paths, path + ("*",), depth + 1)
    elif type(value) is str:
        if not (HEX256.fullmatch(value) and path in hash_paths):
            reject_string(value, label)


def check_json_depth(value, label: str, limit: int = MAX_DEPTH) -> None:
    """Refuse nesting past LIMIT, iteratively, before anything renders or recurses.

    Runs straight after strict_json: a deep document is rejected here, never expanded
    by the canonical renderer."""
    pending = [(value, 0)]
    while pending:
        item, depth = pending.pop()
        if depth > limit:
            raise CollectError(f"{label} nests too deeply")
        if type(item) is dict:
            pending.extend((child, depth + 1) for child in item.values())
        elif type(item) is list:
            pending.extend((child, depth + 1) for child in item)


def field_key(emit: str) -> str:
    return emit.replace("-", "_")


def need_enum_int(value, label: str, allowed) -> int:
    if type(value) is not int or value not in allowed:
        raise CollectError(f"{label} is not an allowed value")
    return value


# --- typed policy checks --------------------------------------------------------


def check_spec(spec: dict, value, label: str, identity: dict):
    kind = spec["type"]
    if kind == "enum":
        return need_enum(value, label, spec["values"])
    if kind == "int":
        return need_int(value, label, spec["min"], spec["max"])
    if kind == "int_enum":
        return need_enum_int(value, label, spec["values"])
    if kind == "bool":
        result = need_bool(value, label)
        if "const" in spec and result is not spec["const"]:
            raise CollectError(f"{label} must be {spec['const']}")
        return result
    if kind in ("text", "hash"):
        return need_text(value, label, re.compile(spec["pattern"]))
    if kind == "identity":
        if "pattern" in spec:
            need_text(value, label, re.compile(spec["pattern"]))
        if value != identity[spec["source"]]:
            raise CollectError(f"{label} differs from the contract identity")
        return value
    if kind == "null":
        if value is not None:
            raise CollectError(f"{label} must be null")
        return None
    if kind == "nullable":
        return None if value is None else check_spec(spec["of"], value, label, identity)
    if kind == "list":
        items = need_list(value, label, spec["min"], spec["max"])
        for item in items:
            check_spec(spec["item"], item, f"{label} item", identity)
        if spec["sorted_unique"]:
            need_sorted_unique(items, label)
        return items
    if kind == "object":
        need_dict(value, spec["fields"], label)
        return {
            name: check_spec(field, value[name], f"{label} {name}", identity)
            for name, field in spec["fields"].items()
        }
    if kind == "rows":
        return check_rows(spec, value, label, f"{label} row", identity)
    raise CollectError(f"{label} has an unknown policy type")


def check_constraints(constraints: list, values: dict, label: str) -> None:
    """Cross-field rules named by the policy, evaluated on already type-checked values."""
    for constraint in constraints:
        kind = constraint["type"]
        if kind == "null_together":
            if len({values[name] is None for name in constraint["fields"]}) != 1:
                raise CollectError(
                    f"{label} {', '.join(constraint['fields'])} must all be set or all be null"
                )
        else:
            raise CollectError(f"{label} has an unknown constraint type")


def check_rows(spec: dict, value, label: str, row_label: str, identity: dict) -> list[dict]:
    """Check each row against its exact fields, then the sort and uniqueness the spec names.

    Rows nest: a row field may itself be an object or rows, checked by the same recursion.
    The ordering rule is read from the spec here, once, for every rows spec."""
    rows = need_list(value, label, spec["min"], spec["max"])
    checked = []
    for row in rows:
        need_dict(row, row_fields(spec), f"{label} row")
        checked.append({
            name: check_spec(field, row[name], f"{row_label} {name}", identity)
            for name, field in spec["row"].items()
        })
    key = row_key_fields(spec)
    if key:
        keys = [tuple(values[name] for name in key) for values in checked]
        if keys != sorted(set(keys)):
            raise CollectError(f"{label} is not unique and sorted")
    return checked


# --- per-operation schemas ------------------------------------------------------


def check_r1(data: dict, policy: dict, identity: dict) -> None:
    fields = policy["fields"]
    values = {name: check_spec(spec, data[name], f"R1 {name}", identity) for name, spec in fields.items()}
    if values["slot_suffix"] != "_" + values["current_slot"]:
        raise CollectError("R1 slot and slot suffix disagree")


def check_r2(data: dict, policy: dict, identity: dict) -> None:
    spec = policy["fields"]["partitions"]
    names = []
    for values in check_rows(spec, data["partitions"], "R2 partitions", "R2 partition", identity):
        name, suffix = values["partition_name"], values["slot_suffix"]
        if suffix != (name[-2:] if name.endswith(("_a", "_b")) else ""):
            raise CollectError("R2 slot suffix differs from the partition name")
        names.append(name)
    recovery = any(re.fullmatch(policy["recovery_pattern"], name) for name in names)
    flag = check_spec(policy["fields"]["recovery_present"], data["recovery_present"], "R2 recovery present", identity)
    if flag != recovery:
        raise CollectError("R2 recovery flag differs from the inventory")


# --- R3 semantic rules ----------------------------------------------------------
# The typed spec bounds every field; these named rules check what a type cannot: the
# profile for each format and version, exact extents, canonical coverage, and that a hash
# exists exactly where the coverage reaches. Each rule reads its constants from the
# serialized profile and budgets, so the contract states exactly what is enforced. They
# judge claims in a fixture: no image bytes exist here, nothing is recomputed or verified.


def base_role(name: str) -> str:
    return name[:-2] if name.endswith(("_a", "_b")) else name


def present_images(rows: list):
    return [(row, row["image"]) for row in rows if row["image"] is not None]


def layout_of(profile: dict, image: dict) -> dict:
    for layout in profile["layouts"]:
        if layout["format"] == image["format"] and layout["version"] == image["version"]:
            return layout
    raise CollectError("R3 image format and version have no profile layout")


def extent_end(offset: int, size: int) -> int:
    end = offset + size
    if end > 2**32:
        raise CollectError("R3 extent overflows 32 bits")
    return end


def covers(ranges: list, offset: int, size: int) -> bool:
    return any(
        item["offset"] <= offset and offset + size <= item["offset"] + item["size_bytes"]
        for item in ranges
    )


def r3_exact_rows(rows, profile, budgets) -> None:
    names = sorted(
        entry["role"] + suffix for entry in profile["partitions"] for suffix in profile["suffixes"]
    )
    if [row["partition_name"] for row in rows] != names or len(names) != profile["row_count"]:
        raise CollectError("R3 images are not exactly the supported partition rows")


def r3_role_from_name(rows, profile, budgets) -> None:
    for row in rows:
        if row["role"] != base_role(row["partition_name"]):
            raise CollectError("R3 role differs from its partition name")


def r3_format_version(rows, profile, budgets) -> None:
    allowed = {entry["role"]: entry for entry in profile["partitions"]}
    for row, image in present_images(rows):
        entry = allowed.get(row["role"])
        if entry is None or image["format"] != entry["format"] or image["version"] not in entry["versions"]:
            raise CollectError("R3 image format or version is outside its partition profile")


def r3_page_size(rows, profile, budgets) -> None:
    for _row, image in present_images(rows):
        fixed = layout_of(profile, image)["fixed_page_size"]
        if image["page_size"] not in profile["page_sizes"] or (
            fixed is not None and image["page_size"] != fixed
        ):
            raise CollectError("R3 image page size is outside its format profile")


def r3_os_version(rows, profile, budgets) -> None:
    for _row, image in present_images(rows):
        # Raw packed uint32 where the header carries one (literal 0 included), else null.
        if (image["format"] == "android-boot") == (image["os_version"] is None):
            raise CollectError("R3 image os_version is not the raw value or null its format requires")


def r3_header_region(rows, profile, budgets) -> None:
    for _row, image in present_images(rows):
        header = image["header"]
        if header["offset"] != 0 or header["size_bytes"] != layout_of(profile, image)["header_bytes"]:
            raise CollectError("R3 header region is not at offset 0 with its exact structure size")


def r3_table(rows, profile, budgets) -> None:
    for _row, image in present_images(rows):
        wanted, table = layout_of(profile, image)["table"], image["table"]
        if wanted is None:
            if table is not None:
                raise CollectError("R3 image carries a table its format does not have")
            continue
        if table is None:
            raise CollectError("R3 image lacks the table its format requires")
        if table["role"] != wanted["role"] or table["entry_size"] != wanted["entry_bytes"]:
            raise CollectError("R3 table role or entry size differs from its profile")
        if not wanted["min_entries"] <= table["entry_count"] <= wanted["max_entries"]:
            raise CollectError("R3 table entry count is outside its profile")
        if table["size_bytes"] != table["entry_count"] * table["entry_size"]:
            raise CollectError("R3 table size is not entry count times entry size")
        if table["size_bytes"] == 0 and table["sha256"] != profile["empty_bytes_sha256"]:
            raise CollectError("R3 empty table hash is not the SHA-256 of empty bytes")


def r3_components(rows, profile, budgets) -> None:
    for row, image in present_images(rows):
        layout, table = layout_of(profile, image), image["table"]
        expected = []
        for slot in layout["slots"]:
            if slot["count"] == TABLE_COUNT:
                if table is None:
                    raise CollectError("R3 component slots need the table their format requires")
                count = table["entry_count"]
            else:
                count = slot["count"]
            expected += [(slot["role"], index) for index in range(count)]
        found = [(item["role"], item["index"]) for item in image["components"]]
        if found != sorted(expected):
            raise CollectError("R3 components differ from the slots of the format version")
        for item in image["components"]:
            fragment = item["role"] == profile["fragment_role"]
            if (item["ramdisk_type"] is not None) != fragment or (
                fragment and item["ramdisk_type"] not in profile["ramdisk_types"]
            ):
                raise CollectError("R3 ramdisk_type is set only on vendor ramdisk fragments")
            if row["role"] == "init_boot" and item["role"] == "kernel" and (
                item["size_bytes"] != profile["init_boot_kernel_bytes"]
            ):
                raise CollectError("R3 init_boot kernel size is not zero")


def r3_extents(rows, profile, budgets) -> None:
    for _row, image in present_images(rows):
        limit = image["size_bytes"]
        if limit > profile["max_image_bytes"]:
            raise CollectError("R3 image is larger than the profile bound")
        header = image["header"]
        extents = [(header["offset"], header["size_bytes"])]
        table = image["table"]
        zero_offsets = [] if table is None or table["size_bytes"] else [table["offset"]]
        if table is not None and table["size_bytes"]:
            extents.append((table["offset"], table["size_bytes"]))
        for item in image["components"]:
            if item["size_bytes"]:
                extents.append((item["offset"], item["size_bytes"]))
            else:
                zero_offsets.append(item["offset"])
        if any(offset > limit for offset in zero_offsets):
            raise CollectError("R3 empty extent lies past the image")
        previous_end = 0
        for offset, size in sorted(extents):
            if extent_end(offset, size) > limit:
                raise CollectError("R3 extent runs past the image")
            if offset < previous_end:
                raise CollectError("R3 extents overlap")
            previous_end = offset + size


def r3_coverage_canonical(rows, profile, budgets) -> None:
    for _row, image in present_images(rows):
        coverage, limit = image["coverage"], image["size_bytes"]
        ranges = coverage["ranges"]
        if len(ranges) > profile["max_coverage_ranges"]:
            raise CollectError("R3 coverage holds more ranges than the profile allows")
        previous_end = None
        for position, item in enumerate(ranges):
            if item["index"] != position:
                raise CollectError("R3 coverage range indices are not sequential")
            end = extent_end(item["offset"], item["size_bytes"])
            if end > limit:
                raise CollectError("R3 coverage range runs past the image")
            if previous_end is not None:
                if item["offset"] < previous_end:
                    raise CollectError("R3 coverage ranges overlap or are not sorted")
                if item["offset"] == previous_end:
                    raise CollectError("R3 coverage ranges are adjacent and not merged")
            previous_end = end
        if coverage["covered_bytes"] != sum(item["size_bytes"] for item in ranges):
            raise CollectError("R3 covered_bytes is not the exact sum of its ranges")


def r3_coverage_kind(rows, profile, budgets) -> None:
    for _row, image in present_images(rows):
        coverage, limit = image["coverage"], image["size_bytes"]
        ranges = coverage["ranges"]
        header, table = image["header"], image["table"]
        if not covers(ranges, header["offset"], header["size_bytes"]):
            raise CollectError("R3 coverage does not reach the whole header")
        if table is not None and table["size_bytes"] and not covers(
            ranges, table["offset"], table["size_bytes"]
        ):
            raise CollectError("R3 coverage does not reach the whole table")
        if coverage["kind"] == "full-image":
            if [(item["offset"], item["size_bytes"]) for item in ranges] != [(0, limit)]:
                raise CollectError("R3 full-image coverage is not exactly the whole image")
        elif coverage["covered_bytes"] >= limit:
            raise CollectError("R3 metadata-only coverage leaves no unverified byte; use full-image")


def r3_hash_iff_covered(rows, profile, budgets) -> None:
    for _row, image in present_images(rows):
        coverage = image["coverage"]
        if (image["sha256"] is not None) != (coverage["kind"] == "full-image"):
            raise CollectError("R3 image sha256 is required for full-image coverage and null otherwise")
        for item in image["components"]:
            reached = item["size_bytes"] > 0 and covers(
                coverage["ranges"], item["offset"], item["size_bytes"]
            )
            if (item["sha256"] is not None) != reached:
                raise CollectError("R3 component sha256 is present only where its whole extent is covered")


def r3_hash_equal_for_identical_extents(rows, profile, budgets) -> None:
    """Two declarations of exactly the same non-empty (offset, size) bytes within one image
    describe the same bytes, so their hashes must be equal and non-null together. Only equal
    extents are compared: an extent contained in or overlapping another is a different claim."""
    for _row, image in present_images(rows):
        declared = [((0, image["size_bytes"]), image["sha256"]),
                    ((image["header"]["offset"], image["header"]["size_bytes"]),
                     image["header"]["sha256"])]
        table = image["table"]
        if table is not None:
            declared.append(((table["offset"], table["size_bytes"]), table["sha256"]))
        declared += [((item["offset"], item["size_bytes"]), item["sha256"])
                     for item in image["components"]]
        seen = {}
        for extent, digest in declared:
            if extent[1] == 0:
                continue  # an empty extent names no byte; zero-size hashes keep their own rules
            seen.setdefault(extent, []).append(digest)
        for digests in seen.values():
            if len(digests) > 1 and (None in digests or len(set(digests)) != 1):
                raise CollectError("R3 declarations of identical extents carry different hashes")


def r3_coverage_budgets(rows, profile, budgets) -> None:
    metadata = sum(
        image["coverage"]["covered_bytes"] for _row, image in present_images(rows)
        if image["coverage"]["kind"] == "metadata-only"
    )
    full = sum(
        image["coverage"]["covered_bytes"] for _row, image in present_images(rows)
        if image["coverage"]["kind"] == "full-image"
    )
    if metadata > budgets["max_hardware_read_bytes"]:
        raise CollectError("R3 metadata coverage exceeds the hardware read budget")
    if full > budgets["max_fixture_input_bytes"]:
        raise CollectError("R3 full-image coverage exceeds the fixture input budget")


R3_RULES = {
    "r3-exact-partition-rows": r3_exact_rows,
    "r3-role-from-partition-name": r3_role_from_name,
    "r3-format-version-profile": r3_format_version,
    "r3-page-size-profile": r3_page_size,
    "r3-os-version-semantics": r3_os_version,
    "r3-header-region": r3_header_region,
    "r3-table-profile": r3_table,
    "r3-component-slots": r3_components,
    "r3-extents-bounded-disjoint": r3_extents,
    "r3-coverage-canonical": r3_coverage_canonical,
    "r3-coverage-by-kind": r3_coverage_kind,
    "r3-hash-iff-covered": r3_hash_iff_covered,
    "r3-hash-equal-for-identical-extents": r3_hash_equal_for_identical_extents,
    "r3-coverage-budgets": r3_coverage_budgets,
}


def r3_presence(rows, partitions, profile) -> None:
    inventory = {row["partition_name"] for row in partitions}
    for row in rows:
        if (row["partition_name"] in inventory) != (row["image"] is not None):
            raise CollectError("R3 presence differs from the R2 inventory")


def r3_capacity(rows, partitions, profile) -> None:
    sizes = {row["partition_name"]: row["size_bytes"] for row in partitions}
    for row, image in present_images(rows):
        if image["size_bytes"] > sizes.get(row["partition_name"], 0):
            raise CollectError("R3 image is larger than its R2 partition")


R3_CROSS_RULES = {
    "r3-presence-matches-r2-inventory": r3_presence,
    "r3-image-fits-r2-partition": r3_capacity,
}


def check_r3(data: dict, policy: dict, identity: dict) -> list:
    """The typed rows, then every named semantic rule the serialized policy lists."""
    rows = check_spec(policy["fields"]["images"], data["images"], "R3 images", identity)
    for name in policy["rules"]:
        rule = R3_RULES.get(name)
        if rule is None:
            raise CollectError("R3 policy names a rule with no implementation")
        rule(rows, policy["profile"], policy["budgets"])
    return rows


def check_r3_against_r2(images: list, partitions: list, policy: dict) -> None:
    """The R3 rows against the R2 inventory they were bound to: presence and capacity."""
    for name in policy["cross_rules"]:
        rule = R3_CROSS_RULES.get(name)
        if rule is None:
            raise CollectError("R3 policy names a cross rule with no implementation")
        rule(images, partitions, policy["profile"])


def check_r4(data: dict, policy: dict, identity: dict) -> None:
    values = {
        name: check_spec(spec, data[name], f"R4 {name}", identity)
        for name, spec in policy["fields"].items()
    }
    check_constraints(policy["constraints"], values, "R4")


def check_r5(data: dict, policy: dict, identity: dict) -> None:
    fields = policy["fields"]
    names = check_spec(fields["module_names"], data["module_names"], "R5 module names", identity)
    exact = lambda name: {**fields[name], "min": len(names), "max": len(names)}
    index = check_spec(exact("load_order_index"), data["load_order_index"], "R5 load order", identity)
    check_spec(exact("taint_flags"), data["taint_flags"], "R5 taint flags", identity)
    if len(set(names)) != len(names):
        raise CollectError("R5 module names repeat")
    for position, value in enumerate(index):
        if value != position:
            raise CollectError("R5 load order index is not sequential")
    declared = [name.replace("-", "_") for name in policy["reference_module_order"]]
    seen = [name.replace("-", "_") for name in names]
    matches = [name for name in seen if name in declared] == declared
    flag = check_spec(fields["order_matches_declared"], data["order_matches_declared"], "R5 order flag", identity)
    if flag != matches:
        raise CollectError("R5 order claim differs from the module list")


def check_r6(data: dict, policy: dict, identity: dict) -> None:
    fields = policy["fields"]
    values = {name: check_spec(spec, data[name], f"R6 {name}", identity) for name, spec in fields.items()}
    unit = policy["rounding_bytes"]
    total, free = values["rounded_total_bytes"], values["rounded_free_bytes"]
    if total % unit or free % unit or free > total:
        raise CollectError("R6 sizes are not rounded to 1 MiB or free exceeds total")


def check_policy_entries(rows, label: str, policy: dict) -> dict:
    allowed = {row["key"]: row for row in policy["entries"]}
    rows = need_list(rows, label, 0, len(allowed))
    keys, found = [], {}
    for row in rows:
        need_dict(row, ["key", "value"], f"{label} entry")
        key = row["key"]
        if type(key) is not str or key not in allowed:
            raise CollectError(f"{label} has an unlisted key")
        need_enum(row["value"], f"{label} value", allowed[key]["allowed_values"])
        keys.append(key)
        found[key] = row["value"]
    need_sorted_unique(keys, label)
    return found


def check_r7(data: dict, policy: dict, identity: dict, spec: dict) -> dict:
    fields = policy["fields"]
    check_spec(fields["kernel_release"], data["kernel_release"], "R7 kernel release", identity)
    check_spec(fields["notes_sha256"], data["notes_sha256"], "R7 notes hash", identity)
    request_policy = spec["field_policy"]
    if request_policy["kernel_command_line"]["unknown_keys"] != policy["allowlist_unknown_keys"] or (
        request_policy["bootconfig"]["unknown_keys"] != policy["allowlist_unknown_keys"]
    ):
        raise CollectError("R7 policy no longer rejects unknown keys")
    cmdline = check_policy_entries(
        data["allowlisted_cmdline"], "R7 command line", request_policy["kernel_command_line"]
    )
    bootconfig = check_policy_entries(
        data["allowlisted_bootconfig_keys"], "R7 bootconfig", request_policy["bootconfig"]
    )
    return {"cmdline": cmdline, "bootconfig": bootconfig}


OPERATION_CHECKS = {
    R1_ID: check_r1,
    R2_ID: check_r2,
    R3_ID: check_r3,
    R4_ID: check_r4,
    R5_ID: check_r5,
    R6_ID: check_r6,
}


def operation_path(operation_id: str) -> str:
    return f"operations/{operation_id}.json"


def validate_operation(
    raw: bytes, spec: dict, request_sha256: str, identity: dict
) -> tuple[dict, dict | None]:
    d = deploy()
    operation_id = spec["id"]
    registry = policy_registry()
    policy = registry["operations"].get(operation_id)
    if policy is None:
        raise CollectError(f"unknown operation {operation_id}")
    budgets = {key: spec.get(key) for key in BUDGET_KEYS}
    if budgets != policy["budgets"] or "max_bytes" in spec:
        raise CollectError(f"{operation_id} request budgets differ from the policy's three bounds")
    if len(raw) > budgets["max_output_bytes"]:
        raise CollectError(
            f"{operation_id} exceeds its {budgets['max_output_bytes']}-byte output bound"
        )
    document = d.strict_json(raw, operation_id)
    check_json_depth(document, operation_id)
    if raw != d.render_json(document):
        raise CollectError(f"{operation_id} is not canonical JSON")
    reject_identifiers(document, operation_id, hash_scope(registry, "operation", operation_id))
    need_dict(document, registry["operation_envelope"]["keys"], operation_id)
    if type(document["schema"]) is not int or document["schema"] != OPERATION_SCHEMA:
        raise CollectError(f"{operation_id} schema differs")
    if document["kind"] != OPERATION_KIND or document["id"] != operation_id:
        raise CollectError(f"{operation_id} identity differs")
    if document["request_sha256"] != request_sha256:
        raise CollectError(f"{operation_id} request binding differs")
    if document["transport"] != TRANSPORT or document["read_only"] is not True:
        raise CollectError(f"{operation_id} transport or read-only claim differs")
    if document["read_domain"] != READ_DOMAIN:
        raise CollectError(f"{operation_id} read domain differs")
    need_int(
        document["bytes_read"], f"{operation_id} bytes_read", 1, budgets["max_fixture_input_bytes"]
    )
    if sorted(field_key(emit) for emit in spec["emits"]) != field_paths(policy, container_prefix=False):
        raise CollectError(f"{operation_id} emitted fields differ from the policy registry")
    data = need_dict(document["data"], set(policy["fields"]), f"{operation_id} data")
    if operation_id == R7_ID:
        return document, check_r7(data, policy, identity, spec)
    OPERATION_CHECKS[operation_id](data, policy, identity)
    return document, None


def cross_check(documents: dict, r7: dict) -> None:
    r1 = documents["R1-identity-and-slot"]["data"]
    partitions = documents[R2_ID]["data"]["partitions"]
    r2 = {row["partition_name"] for row in partitions}
    check_r3_against_r2(
        documents[R3_ID]["data"]["images"], partitions, policy_registry()["operations"][R3_ID]
    )
    if documents["R6-storage-and-mount-model"]["data"]["root_source_gpt_name"] not in r2:
        raise CollectError("R6 root partition is not in the R2 inventory")
    for source in (r7["cmdline"], r7["bootconfig"]):
        if source.get("androidboot.slot_suffix", r1["slot_suffix"]) != r1["slot_suffix"]:
            raise CollectError("R7 slot suffix disagrees with R1")
        if source.get("androidboot.slot", r1["current_slot"]) != r1["current_slot"]:
            raise CollectError("R7 slot disagrees with R1")
    state = r7["bootconfig"].get("androidboot.verifiedbootstate", r1["verified_boot_state"])
    if state != r1["verified_boot_state"]:
        raise CollectError("R7 verified boot state disagrees with R1")


# --- request and capture --------------------------------------------------------


class Inputs:
    def __init__(self, request, request_sha256, request_ids, capture):
        self.request = request
        self.request_sha256 = request_sha256
        self.request_ids = request_ids
        self.capture = capture


class Capture:
    def __init__(self, manifest, documents, sizes, capture_sha256, directory_ids):
        self.manifest = manifest
        self.documents = documents
        self.sizes = sizes
        self.capture_sha256 = capture_sha256
        self.directory_ids = directory_ids


def read_request(path: str, env: Environment):
    p = preflight()
    d = deploy()
    document, ids, _identity = p.read_request(
        path, env.contracts, env.preflight_bytes, env.preflight_sha256
    )
    spec = p.request_spec(env.preflight_bytes, document)
    sums = next(data for name, kind, mode, data in spec if name == "SHA256SUMS")
    return document, d.sha256_bytes(sums), ids


def manifest_document(env: Environment, request_sha256: str, request: dict, files: dict) -> dict:
    d = deploy()
    return {
        "schema": 1,
        "kind": CAPTURE_KIND,
        "format_version": VERSION,
        "contract_sha256": env.contract_sha256,
        "request_sha256": request_sha256,
        "capture_schema": preflight().CAPTURE_SCHEMA,
        "transport": TRANSPORT,
        "live": False,
        "operations": [
            {
                "id": row["id"],
                "sha256": d.sha256_bytes(files[operation_path(row["id"])]),
                "bytes": len(files[operation_path(row["id"])]),
            }
            for row in request["requested_reads"]
        ],
    }


def read_capture(path: str, env: Environment, request: dict, request_sha256: str) -> Capture:
    d = deploy()
    descriptor, identity = d.open_trusted_artifact(path, "capture")
    try:
        tree = d.walk_tree(
            descriptor, capture_limits(), allow_symlinks=False, keep_data=True,
            trusted_ownership=True, label="capture",
        )
    finally:
        os.close(descriptor)
    reads = request["requested_reads"]
    expected = {".": "dir", "operations": "dir", "capture.json": "file"}
    expected.update({operation_path(row["id"]): "file" for row in reads})
    actual = {entry.path: entry.kind for entry in tree.entries}
    if actual != expected:
        extra = sorted(set(actual) - set(expected))
        missing = sorted(set(expected) - set(actual))
        raise CollectError(f"capture tree differs (extra {extra}, missing {missing})")
    for entry in tree.entries:
        if entry.kind == "file" and entry.mode & 0o111:
            raise CollectError(f"capture file is executable: {entry.path}")
    if tree.file_bytes > TOTAL_CAPTURE_BYTES:
        raise CollectError("capture exceeds the total byte bound")
    manifest = d.strict_json(tree.data["capture.json"], "capture.json")
    check_json_depth(manifest, "capture.json")
    if tree.data["capture.json"] != d.render_json(manifest):
        raise CollectError("capture.json is not canonical")
    reject_identifiers(manifest, "capture.json", hash_scope(policy_registry(), "manifest"))
    expected_manifest = manifest_document(env, request_sha256, request, tree.data)
    if not kernel().strict_equal(manifest, expected_manifest):
        raise CollectError("capture.json differs from its operations or bindings")
    documents, r7 = {}, None
    for row in reads:
        document, result = validate_operation(
            tree.data[operation_path(row["id"])], row, request_sha256, env.identity
        )
        documents[row["id"]] = document
        if result is not None:
            r7 = result
    cross_check(documents, r7)
    sums = "".join(
        f"{entry.sha256}  {entry.path}\n" for entry in tree.entries if entry.kind == "file"
    )
    d.recheck_trusted_artifact(path, identity, "capture")
    return Capture(
        manifest, documents,
        {row["id"]: len(tree.data[operation_path(row["id"])]) for row in reads},
        d.sha256_bytes(sums.encode("ascii")), tree.directory_ids,
    )


def gather(args, env: Environment) -> Inputs:
    d = deploy()
    if d.paths_overlap(args.request, args.capture):
        raise CollectError("capture and request paths overlap")
    request, request_sha256, request_ids = read_request(args.request, env)
    capture = read_capture(args.capture, env, request, request_sha256)
    if request_ids & capture.directory_ids:
        raise CollectError("capture aliases the request tree")
    return Inputs(request, request_sha256, request_ids, capture)


# --- documents ------------------------------------------------------------------


def plan_operation(row: dict) -> dict:
    policy = policy_registry()["operations"][row["id"]]
    container = policy["container"] or {"rows_field": None, "row_fields": []}
    return {
        "id": row["id"],
        "path": policy["input_path"],
        "purpose": list(row["purpose"]),
        "read_only": row["read_only"],
        **{key: row[key] for key in BUDGET_KEYS},
        "emits": list(row["emits"]),
        "fields": [field_key(emit) for emit in row["emits"]],
        "field_policy": row["field_policy"],
        "never_emits": list(row["never_emits"]),
        "stop_conditions": list(row["stop_conditions"]),
        "rows_field": container["rows_field"],
        "row_fields": list(container["row_fields"]),
        "policy": policy,
    }


def plan_document(env: Environment, request: dict, request_sha256: str) -> dict:
    return {
        "schema": 1,
        "kind": PLAN_KIND,
        "format_version": VERSION,
        "contract_sha256": env.contract_sha256,
        "request_sha256": request_sha256,
        "transport": TRANSPORT,
        "evidence_level": EVIDENCE_LEVEL,
        "implementation": implementation_binding(),
        "live": False,
        "executes": False,
        "remote_commands": [],
        "forbidden_operations": list(request["forbidden_operations"]),
        "redaction": dict(request["redaction"]),
        "policy": {
            key: value for key, value in policy_registry().items() if key != "operations"
        },
        "capture_tree": {
            "manifest": "capture.json",
            "operations": [plan_operation(row) for row in request["requested_reads"]],
            "total_max_bytes": TOTAL_CAPTURE_BYTES,
            "extra_entries": "reject",
        },
        "evidence_files": [
            "STATUS.txt", "SHA256SUMS", "contracts/capture-contract.json",
            "evidence.json", "status.json",
        ],
        "human_approval_required": True,
        "blockers": list(deploy().BLOCKERS),
        "authority": authority(),
    }


def evidence_document(env: Environment, inputs: Inputs) -> dict:
    reads = inputs.request["requested_reads"]
    return {
        "schema": 1,
        "kind": EVIDENCE_KIND,
        "format_version": VERSION,
        "contract_sha256": env.contract_sha256,
        "request_sha256": inputs.request_sha256,
        "capture_sha256": inputs.capture.capture_sha256,
        "transport": TRANSPORT,
        "evidence_level": EVIDENCE_LEVEL,
        "status": EVIDENCE_STATUS,
        "live": False,
        "executes": False,
        "kit_snapshot_reverified": False,
        "remote_commands": [],
        "human_approval_required": True,
        "operations": [
            {
                "id": row["id"],
                "sha256": next(
                    item["sha256"] for item in inputs.capture.manifest["operations"]
                    if item["id"] == row["id"]
                ),
                "bytes": inputs.capture.sizes[row["id"]],
                "read_domain": READ_DOMAIN,
                "bytes_read": inputs.capture.documents[row["id"]]["bytes_read"],
                **{key: row[key] for key in BUDGET_KEYS},
                "data": inputs.capture.documents[row["id"]]["data"],
            }
            for row in reads
        ],
        "blockers": blocker_rows(),
        "authority": authority(),
    }


def evidence_spec(env: Environment, inputs: Inputs) -> list:
    d = deploy()
    files = {
        "contracts/capture-contract.json": env.contract_bytes,
        "evidence.json": d.render_json(evidence_document(env, inputs)),
        "status.json": d.render_json(status_document()),
        "STATUS.txt": STATUS_TEXT,
    }
    files["SHA256SUMS"] = "".join(
        f"{d.sha256_bytes(files[path])}  {path}\n" for path in sorted(files)
    ).encode("ascii")
    spec = [("contracts", "dir", 0o755, None)]
    spec += [(path, "file", 0o644, data) for path, data in files.items()]
    spec.sort(key=lambda item: item[0].encode("utf-8"))
    return spec


def result_summary(status: str, inputs: Inputs, spec: list) -> dict:
    d = deploy()
    sums = next(data for path, kind, mode, data in spec if path == "SHA256SUMS")
    return {
        "status": status,
        "evidence_level": EVIDENCE_LEVEL,
        "evidence_sha256": d.sha256_bytes(sums),
        "request_sha256": inputs.request_sha256,
        "capture_sha256": inputs.capture.capture_sha256,
        "operation_count": len(inputs.capture.documents),
        "blocker_count": len(d.BLOCKERS),
        "live": False,
        "executes": False,
        "kit_snapshot_reverified": False,
        **authority(),
    }


# --- commands -------------------------------------------------------------------


def command_plan(env: Environment, args) -> dict:
    request, request_sha256, _ids = read_request(args.request, env)
    return plan_document(env, request, request_sha256)


def command_verify_plan(env: Environment, args) -> dict:
    d = deploy()
    request, request_sha256, _ids = read_request(args.request, env)
    expected = plan_document(env, request, request_sha256)
    raw = d.read_file(args.plan, "capture plan", d.MAX_SMALL_BYTES)
    document = d.strict_json(raw, "capture plan")
    check_json_depth(document, "capture plan", PLAN_MAX_DEPTH)
    if raw != d.render_json(document):
        raise CollectError("capture plan is not canonical")
    if not kernel().strict_equal(document, expected):
        raise CollectError("capture plan differs from the request")
    return {
        "status": "verified",
        "request_sha256": request_sha256,
        "operation_count": len(expected["capture_tree"]["operations"]),
        "live": False,
        "executes": False,
        **authority(),
    }


def command_collect(env: Environment, args) -> dict:
    d = deploy()
    inputs = gather(args, env)
    spec = evidence_spec(env, inputs)
    expected = d.spec_entries(spec)
    protected = [args.request, args.capture]
    protected_ids = frozenset(inputs.request_ids | inputs.capture.directory_ids)

    def verify_built(temporary_path: str, descriptor: int) -> None:
        again = gather(args, env)
        if evidence_spec(env, again) != spec:
            raise CollectError("request or capture changed during collection")
        tree = d.walk_tree(
            descriptor, d.STAGE_LIMITS, allow_symlinks=False, label="capture evidence"
        )
        d.diff_entries(tree.entries, expected, "capture evidence")

    d.publish(args.out, protected, protected_ids, spec, verify_built)
    return result_summary("collected", inputs, spec)


def command_verify_evidence(env: Environment, args) -> dict:
    d = deploy()
    inputs = gather(args, env)
    spec = evidence_spec(env, inputs)
    if any(d.paths_overlap(args.evidence, path) for path in (args.request, args.capture)):
        raise CollectError("evidence overlaps an input")
    descriptor, identity = d.open_trusted_artifact(args.evidence, "capture evidence")
    try:
        tree = d.walk_tree(
            descriptor, d.STAGE_LIMITS, allow_symlinks=False, keep_data=True,
            trusted_ownership=True, label="capture evidence",
        )
    finally:
        os.close(descriptor)
    d.diff_entries(tree.entries, d.spec_entries(spec), "capture evidence")
    if tree.directory_ids & (inputs.request_ids | inputs.capture.directory_ids):
        raise CollectError("evidence aliases an input tree")
    d.recheck_trusted_artifact(args.evidence, identity, "capture evidence")
    return result_summary("verified", inputs, spec)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("show", help="print the offline capture contract")
    plan = commands.add_parser("plan", help="print the value-free collection plan")
    plan.add_argument("--request", required=True)
    verify_plan = commands.add_parser("verify-plan", help="recompute a saved plan")
    verify_plan.add_argument("--request", required=True)
    verify_plan.add_argument("--plan", required=True)
    collect = commands.add_parser("collect", help="validate a fixture and write evidence")
    collect.add_argument("--request", required=True)
    collect.add_argument("--capture", required=True)
    collect.add_argument("--out", required=True)
    verify = commands.add_parser("verify-evidence", help="recompute fixture evidence")
    verify.add_argument("--request", required=True)
    verify.add_argument("--capture", required=True)
    verify.add_argument("--evidence", required=True)
    return parser


def main(argv: list[str] | None = None, contracts_root: Path | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        p = preflight()
    except CollectError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    d = p.deploy()
    s = p.snapshot()
    root = contracts_root or REPO
    try:
        env = load_environment(root)
        if args.command == "show":
            result = env.contract
        elif args.command == "plan":
            result = command_plan(env, args)
        elif args.command == "verify-plan":
            result = command_verify_plan(env, args)
        elif args.command == "collect":
            result = command_collect(env, args)
        else:
            result = command_verify_evidence(env, args)
    except (CollectError, p.PreflightError, s.SnapshotError, *d.handled_errors()) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
