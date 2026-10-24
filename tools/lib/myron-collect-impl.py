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
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import re
import stat

sys.dont_write_bytecode = True

VERSION = "0.1.0"
REPO = Path(__file__).resolve().parent.parent
PREFLIGHT_TOOL = REPO / "tools/myron-preflight"
PINNED_VERSIONS = {"preflight": "0.2.0", "snapshot": "0.2.0", "deployment": "0.4.0"}
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
MAX_MODULES = 256
MEBIBYTE = 1024 * 1024
HEX256 = re.compile(r"[0-9a-f]{64}")
PARTITION_NAME = re.compile(r"[a-z0-9_]{1,36}")
MODULE_NAME = re.compile(r"[A-Za-z0-9_-]{1,56}")
TAINT_FLAGS = re.compile(r"[A-Z]{0,8}")
OS_VERSION = re.compile(r"[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}")
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


def _case(when: bool, fields: dict, constraints=()) -> dict:
    return {"when": when, "fields": fields, "constraints": list(constraints)}


def _variants(discriminator: str, cases: list) -> dict:
    return {"discriminator": discriminator, "cases": cases}


def _rows(row: dict, low: int, high: int, key: str, variants=None) -> dict:
    spec = {"type": "rows", "row": row, "min": low, "max": high, "sorted_unique_by": key}
    if variants is not None:
        spec["variants"] = variants
    return spec


def _null_together(*fields: str) -> dict:
    return {"type": "null_together", "fields": list(fields)}


def _list_lengths(lists, count: str) -> dict:
    return {"type": "list_lengths", "lists": list(lists), "count": count}


def row_fields(spec: dict) -> list:
    """Every field a row may carry: the base fields, then each variant's fields."""
    names = list(spec["row"])
    for case in spec.get("variants", {}).get("cases", []):
        names += [name for name in case["fields"] if name not in names]
    return names


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
IMAGE_ROW = {
    "partition_name": _text(IMAGE_NAME),
    "absent": _bool(),
}
# The header fields depend on `absent`: an absent image has null headers, empty
# lists and no segments; a present image has every header field set.
IMAGE_ABSENT = {
    "header_version": _null(),
    "page_size": _null(),
    "os_version": _null(),
    "component_sizes": _list(_int(0, 2**32), 0, 0),
    "component_offsets": _list(_int(0, 2**32), 0, 0),
    "segment_count": _int(0, 0),
    "header_sha256": _null(),
}
IMAGE_PRESENT = {
    "header_version": _int(0, 4),
    "page_size": _int_enum([2048, 4096, 8192, 16384]),
    "os_version": _text(OS_VERSION),
    "component_sizes": _list(_int(0, 2**32), 1, 8),
    "component_offsets": _list(_int(0, 2**32), 1, 8),
    "segment_count": _int(1, 8),
    "header_sha256": _hash(),
}
IMAGE_SEGMENT_LISTS = ["component_sizes", "component_offsets"]
IMAGE_VARIANTS = _variants("absent", [
    _case(True, IMAGE_ABSENT, [_list_lengths(IMAGE_SEGMENT_LISTS, "segment_count")]),
    _case(False, IMAGE_PRESENT, [_list_lengths(IMAGE_SEGMENT_LISTS, "segment_count")]),
])
IMAGE_ROWS = _rows(IMAGE_ROW, 1, 12, "partition_name", IMAGE_VARIANTS)
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
    p = preflight()
    return {
        "capture_limits": {
            "entries": CAPTURE_ENTRIES,
            "depth": CAPTURE_DEPTH,
            "file_bytes": MAX_FILE_BYTES,
            "total_bytes": TOTAL_CAPTURE_BYTES,
            "json_depth": MAX_DEPTH,
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
            }, _container("images", IMAGE_ROWS)),
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


def check_spec_shape(spec, where: str) -> None:
    """A typed spec is well formed: known type, ordered bounds, nested specs sound."""
    if type(spec) is not dict or "type" not in spec:
        policy_error(f"{where} is not a typed spec")
    kind = spec["type"]
    if kind in ("int", "list") and spec["min"] > spec["max"]:
        policy_error(f"{where} has min above max")
    if kind == "list":
        check_spec_shape(spec["item"], f"{where} item")
    elif kind == "nullable":
        check_spec_shape(spec["of"], f"{where} value")
        if spec["of"]["type"] in ("null", "nullable"):
            policy_error(f"{where} nests a null type in a nullable")
    elif kind == "rows":
        for name, field in spec["row"].items():
            check_spec_shape(field, f"{where} {name}")
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
    elif kind == "list_lengths":
        names = constraint["lists"]
        if not names or set(names) - set(fields) or constraint["count"] not in fields:
            policy_error(f"{where} list_lengths names unknown fields")
        if any(fields[name]["type"] != "list" for name in names):
            policy_error(f"{where} list_lengths names a non-list field")
        if fields[constraint["count"]]["type"] != "int":
            policy_error(f"{where} list_lengths count is not an integer")
    else:
        policy_error(f"{where} has unknown constraint {kind}")


def check_rows_shape(name: str, spec: dict, where: str) -> None:
    variants = spec.get("variants")
    if variants is None:
        return
    discriminator = variants["discriminator"]
    selector = spec["row"].get(discriminator)
    if selector is None or selector["type"] != "bool" or "const" in selector:
        policy_error(f"{where} discriminator {discriminator} is not a free boolean field")
    cases = variants["cases"]
    whens = [case["when"] for case in cases]
    if any(type(when) is not bool for when in whens) or sorted(whens) != [False, True]:
        policy_error(f"{where} variants must cover true and false exactly once")
    names = [set(case["fields"]) for case in cases]
    if names[0] != names[1] or names[0] & set(spec["row"]):
        policy_error(f"{where} variants do not share one disjoint field set")
    for case in cases:
        for field, field_spec in case["fields"].items():
            check_spec_shape(field_spec, f"{where} {field} when {case['when']}")
        for constraint in case["constraints"]:
            check_constraint_shape(
                constraint, {**spec["row"], **case["fields"]}, f"{where} when {case['when']}"
            )


def check_policy(registry: dict) -> None:
    """Refuse a registry whose parts contradict each other (nulls, variants, containers)."""
    for operation_id, policy in registry["operations"].items():
        where = operation_id.split("-")[0]
        fields = policy["fields"]
        for name, spec in fields.items():
            check_spec_shape(spec, f"{where} {name}")
            if spec["type"] == "rows":
                check_rows_shape(name, spec, f"{where} {name}")
        for constraint in policy["constraints"]:
            check_constraint_shape(constraint, fields, where)
        container = policy["container"]
        if container is not None:
            rows = fields.get(container["rows_field"])
            if rows is None or rows["type"] != "rows" or container["row_fields"] != row_fields(rows):
                policy_error(f"{where} container differs from its row spec")


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
    if kind == "rows":
        fields = dict(spec["row"])
        for case in spec.get("variants", {}).get("cases", []):
            fields.update(case["fields"])
        for name, field in fields.items():
            found |= hash_paths_of(field, path + ("*", name))
    return found


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
        elif kind == "list_lengths":
            count = values[constraint["count"]]
            if any(len(values[name]) != count for name in constraint["lists"]):
                raise CollectError(f"{label} lists differ from {constraint['count']}")
        else:
            raise CollectError(f"{label} has an unknown constraint type")


def check_rows(spec: dict, value, label: str, row_label: str, identity: dict) -> list[dict]:
    """Check each row against the base fields and the variant its discriminator selects."""
    rows = need_list(value, label, spec["min"], spec["max"])
    variants = spec.get("variants")
    checked = []
    for row in rows:
        need_dict(row, row_fields(spec), f"{label} row")
        values = {
            name: check_spec(field, row[name], f"{row_label} {name}", identity)
            for name, field in spec["row"].items()
        }
        if variants is not None:
            selector = values[variants["discriminator"]]
            case = next((item for item in variants["cases"] if item["when"] is selector), None)
            if case is None:
                raise CollectError(f"{row_label} has no policy variant for {selector}")
            for name, field in case["fields"].items():
                values[name] = check_spec(field, row[name], f"{row_label} {name}", identity)
            check_constraints(case["constraints"], values, row_label)
        checked.append(values)
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
    need_sorted_unique(names, "R2 partitions")
    recovery = any(re.fullmatch(policy["recovery_pattern"], name) for name in names)
    flag = check_spec(policy["fields"]["recovery_present"], data["recovery_present"], "R2 recovery present", identity)
    if flag != recovery:
        raise CollectError("R2 recovery flag differs from the inventory")


def check_r3(data: dict, policy: dict, identity: dict) -> None:
    rows = check_rows(
        policy["fields"]["images"], data["images"], "R3 images", "R3 image", identity
    )
    need_sorted_unique([values["partition_name"] for values in rows], "R3 images")


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
    if len(raw) > spec["max_bytes"]:
        raise CollectError(f"{operation_id} exceeds its {spec['max_bytes']}-byte bound")
    document = d.strict_json(raw, operation_id)
    check_json_depth(document, operation_id)
    if raw != d.render_json(document):
        raise CollectError(f"{operation_id} is not canonical JSON")
    reject_identifiers(document, operation_id, hash_scope(registry, "operation", operation_id))
    need_dict(
        document,
        ["schema", "kind", "id", "request_sha256", "transport", "read_only", "bytes_read", "data"],
        operation_id,
    )
    if type(document["schema"]) is not int or document["schema"] != 1:
        raise CollectError(f"{operation_id} schema differs")
    if document["kind"] != OPERATION_KIND or document["id"] != operation_id:
        raise CollectError(f"{operation_id} identity differs")
    if document["request_sha256"] != request_sha256:
        raise CollectError(f"{operation_id} request binding differs")
    if document["transport"] != TRANSPORT or document["read_only"] is not True:
        raise CollectError(f"{operation_id} transport or read-only claim differs")
    limit = spec["max_bytes"]
    need_int(document["bytes_read"], f"{operation_id} bytes_read", 1, limit)
    emitted = {field_key(emit) for emit in spec["emits"]}
    container = policy["container"]
    keys = emitted
    if container is not None:
        if not set(container["row_fields"]) <= emitted:
            raise CollectError(f"{operation_id} row fields are not emitted fields")
        keys = (emitted - set(container["row_fields"])) | {container["rows_field"]}
    if keys != set(policy["fields"]):
        raise CollectError(f"{operation_id} emitted fields differ from the policy registry")
    data = need_dict(document["data"], keys, f"{operation_id} data")
    if operation_id == R7_ID:
        return document, check_r7(data, policy, identity, spec)
    OPERATION_CHECKS[operation_id](data, policy, identity)
    return document, None


def cross_check(documents: dict, r7: dict) -> None:
    r1 = documents["R1-identity-and-slot"]["data"]
    r2 = {row["partition_name"] for row in documents["R2-gpt-and-recovery-inventory"]["data"]["partitions"]}
    for image in documents["R3-boot-image-headers"]["data"]["images"]:
        if (image["partition_name"] in r2) == image["absent"]:
            raise CollectError("R3 presence differs from the R2 inventory")
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
        "max_bytes": row["max_bytes"],
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
                "bytes_read": inputs.capture.documents[row["id"]]["bytes_read"],
                "max_bytes": row["max_bytes"],
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
