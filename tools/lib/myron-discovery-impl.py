# SPDX-License-Identifier: MIT
# Implementation of tools/myron-discovery (Phase 2.19). Executed by the trusted loader
# in the loader's namespace; never run directly. Offline: no subprocess, no network,
# no writes, no bytecode, no environment. It validates a SYNTHETIC Stage 1 discovery
# plan against a pinned, finite, public review context. A pass is structural only and
# authorizes nothing. See docs/myron/DISCOVERY-CONTRACT.md.

import hashlib
import json
import os
import re
import stat
import sys

TOOL_VERSION = "0.1.0"
CONTRACT_PATH = "device/myron/discovery-contract.json"
CONTRACT_SCHEMA = "myron-discovery-contract/1"
CONTRACT_KIND = "myron-discovery-planning-contract"
PLAN_SCHEMA = "myron-discovery-plan/1"
PLAN_KIND = "myron-discovery-plan"
PLAN_DOMAIN = "synthetic-discovery-plan"
RESULT_SCHEMA = "myron-discovery-check-result/1"
RESULT_KIND = "myron-discovery-check-result"
STAGE = 1

FAILURE = "myron-discovery: E_REFUSED"
USAGE_FAILURE = "myron-discovery: E_USAGE"
ARGUMENT_MAX_BYTES = 4096
MAX_ARGUMENTS = 2

# Parser ceilings: bounds on the bytes this program will read and parse. They are not
# discovery limits and say nothing about any hardware read.
CONTRACT_MAX_BYTES = 64 * 1024
OUTPUT_MAX_BYTES = 64 * 1024
PLAN_MAX_BYTES = 16 * 1024
PLAN_PARSER = {"max_depth": 4, "max_nodes": 256, "max_string": 64, "max_items": 16}
CONTRACT_PARSER = {"max_depth": 6, "max_nodes": 1024, "max_string": 512, "max_items": 64}

# Hypothetical Stage 1 limits of the synthetic planning model. They are not the
# reviewed Stage 0 limits and no hardware read is allowed by them.
STAGE1_SYNTHETIC_LIMITS = {"max_calls": 6, "max_returned_bytes": 16384, "max_elapsed_ms": 30000}

AUTHORITY_FLAGS = (
    "atomic_snapshot_proof", "atomicity_proven", "bootable", "deployment_authorized",
    "flashable", "hardware_qualified", "hardware_read_authorized", "image_ready",
    "rollback_proven",
)
BLOCKERS = (
    "kernel-source-lock-reproduction-not-verified",
    "module-abi-import-and-load-order-not-verified",
    "private-runtime-asset-bytes-not-bound-to-kit",
    "atomic-snapshot-and-rollback-not-proven",
    "no-bootable-image-or-captured-boot-chain",
    "composed-kit-not-hardware-qualified",
    "no-independent-deployment-review-or-authorization",
)
STAGE0_PREREQUISITES = (
    "verified-real-kit-snapshot-and-preflight-request",
    "bound-hashes-of-code-contract-and-request",
    "target-identity-and-independent-host-identity-source",
    "exact-stage1-metadata-sources",
    "byte-call-and-time-limits",
    "private-no-overwrite-output-location",
    "operator-confirmed-recovery-and-access-path",
)
UNSUPPORTED_STAGES = (
    (2, "exact-gpt-ranges-per-approved-source"),
    (3, "image-discriminator-header-and-table-ranges"),
    (4, "r4-base-dtb-source-and-selection-witness"),
)
NON_GOALS = (
    "real-request", "acquisition-schema", "producer", "transport", "capture",
    "hardware-bytes", "parser-adapter", "approval-issuance", "deployment-readiness",
    "converter-to-capture-fixtures",
)

# The finite public synthetic review context. Every name is a dummy: no real host key,
# endpoint, source name, path, output location, identifier or private hash appears here.
REVIEW_CONTEXT = {
    "target_refs": ["synthetic-target-ref-1"],
    "trust_refs": ["synthetic-trust-ref-1"],
    "output_refs": ["synthetic-output-ref-1"],
    "recovery_refs": ["synthetic-recovery-ref-1"],
    "stop_policy_ids": ["synthetic-stop-on-first-anomaly"],
    "metadata_profiles": [
        {"metadata_profile_id": "synthetic-profile-identity",
         "command_ids": ["synthetic-command-identity"]},
        {"metadata_profile_id": "synthetic-profile-topology",
         "command_ids": ["synthetic-command-topology", "synthetic-command-geometry"]},
    ],
    "sources": [
        {"source_ref": "synthetic-source-ref-1",
         "metadata_profile_id": "synthetic-profile-identity"},
        {"source_ref": "synthetic-source-ref-2",
         "metadata_profile_id": "synthetic-profile-topology"},
        {"source_ref": "synthetic-source-ref-3",
         "metadata_profile_id": "synthetic-profile-topology"},
    ],
    "commands": [
        {"command_id": "synthetic-command-identity", "max_returned_bytes": 1024,
         "max_timeout_ms": 2000},
        {"command_id": "synthetic-command-topology", "max_returned_bytes": 4096,
         "max_timeout_ms": 5000},
        {"command_id": "synthetic-command-geometry", "max_returned_bytes": 1024,
         "max_timeout_ms": 2000},
    ],
    # Required Stage 1 coverage of the synthetic model, in this exact order: the
    # independent identity/trust check first, then each topology source's topology and
    # geometry operations. A plan may lower budgets but may not omit or reorder these.
    "stage1_required_operations": [
        {"phase": "identity-trust-check", "source_ref": "synthetic-source-ref-1",
         "command_id": "synthetic-command-identity"},
        {"phase": "topology-source-a", "source_ref": "synthetic-source-ref-2",
         "command_id": "synthetic-command-topology"},
        {"phase": "topology-source-a", "source_ref": "synthetic-source-ref-2",
         "command_id": "synthetic-command-geometry"},
        {"phase": "topology-source-b", "source_ref": "synthetic-source-ref-3",
         "command_id": "synthetic-command-topology"},
        {"phase": "topology-source-b", "source_ref": "synthetic-source-ref-3",
         "command_id": "synthetic-command-geometry"},
    ],
    "topology_command_id": "synthetic-command-topology",
    "min_distinct_topology_sources": 2,
}

PLAN_KEYS = ("schema", "kind", "domain", "stage", "bindings", "target_ref", "trust_ref",
             "output_ref", "recovery_ref", "sources", "operations", "limits",
             "stop_policy_id")
BINDING_KEYS = ("contract_sha256", "implementation_sha256", "synthetic_review_context_sha256")
SOURCE_KEYS = ("source_ref", "metadata_profile_id")
OPERATION_KEYS = ("sequence", "source_ref", "command_id", "max_returned_bytes", "timeout_ms")
LIMIT_KEYS = ("max_calls", "max_returned_bytes", "max_elapsed_ms")

# Keys that name a capability this phase must never grow. The closed schema already
# rejects every unknown key; this list only gives such a key its own refusal reason.
FORBIDDEN_KEY_FRAGMENTS = (
    "approv", "evidence", "ledger", "provenance", "retry", "retries", "concurren",
    "parallel", "execut", "transport", "shell", "argv", "command_line", "path", "url",
    "offset", "range", "lba", "partition", "glob", "wildcard", "host_key", "endpoint",
    "capture", "fixture", "hardware", "live", "request",
)
FOREIGN_DOMAIN_FRAGMENTS = ("fixture", "hardware", "live", "capture", "private")

HEX64 = re.compile(r"[0-9a-f]{64}\Z")
OPEN_FLAGS = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW


class Refusal(Exception):
    """A refusal. `reason` is a fixed slug for tests and is never printed."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class UsageError(Exception):
    """Command-line misuse."""


def refuse(reason: str):
    raise Refusal(reason)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def render_json(value) -> bytes:
    data = (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode("ascii")
    if len(data) > OUTPUT_MAX_BYTES:
        refuse("output-bound")
    return data


def canonical_json(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def review_context_sha256() -> str:
    return sha256_bytes(canonical_json(REVIEW_CONTEXT))


# ---------------------------------------------------------------- strict JSON (pure)

def _scan_depth(text: str, limit: int) -> None:
    depth = 0
    in_string = False
    escaped = False
    for char in text:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char in "[{":
            depth += 1
            if depth > limit:
                refuse("json-depth")
        elif char in "]}":
            depth -= 1


def _object_pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            refuse("json-duplicate-key")
        value[key] = item
    return value


def _refuse_constant(_name):
    refuse("json-nonfinite")


def _refuse_float(_text):
    refuse("json-float")


def _check_string(text: str, limit: int) -> None:
    if len(text) > limit or not text.isascii() or any(ord(c) < 0x20 or ord(c) == 0x7f for c in text):
        refuse("json-string")


def _walk_bounds(value, depth: int, nodes: list, parser: dict) -> None:
    nodes[0] += 1
    if nodes[0] > parser["max_nodes"] or depth > parser["max_depth"]:
        refuse("json-bound")
    if type(value) is dict:
        if len(value) > parser["max_items"]:
            refuse("json-bound")
        for key, item in value.items():
            _check_string(key, parser["max_string"])
            _walk_bounds(item, depth + 1, nodes, parser)
    elif type(value) is list:
        if len(value) > parser["max_items"]:
            refuse("json-bound")
        for item in value:
            _walk_bounds(item, depth + 1, nodes, parser)
    elif type(value) is str:
        _check_string(value, parser["max_string"])
    elif type(value) is int or value is None or type(value) is bool:
        return
    else:
        refuse("json-type")


def parse_json_object(data: bytes, parser: dict):
    """Strict, bounded JSON object parse of already captured bytes."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        refuse("json-utf8")
    if text.startswith("﻿"):
        refuse("json-utf8")
    _scan_depth(text, parser["max_depth"])
    try:
        value = json.JSONDecoder(
            object_pairs_hook=_object_pairs,
            parse_float=_refuse_float,
            parse_constant=_refuse_constant,
        ).decode(text)
    except Refusal:
        raise
    except (ValueError, RecursionError):
        refuse("json-syntax")
    if not isinstance(value, dict):
        refuse("json-type")
    _walk_bounds(value, 1, [0], parser)
    return value


# ---------------------------------------------------------------- contract (pure)

def expected_contract() -> dict:
    """The one canonical public contract. The repository file must equal its rendering."""
    return {
        "schema": CONTRACT_SCHEMA,
        "kind": CONTRACT_KIND,
        "version": TOOL_VERSION,
        "domain": PLAN_DOMAIN,
        "purpose": "offline synthetic Stage 1 discovery planning; structural mechanism only",
        "authority": {name: False for name in AUTHORITY_FLAGS},
        "blockers": list(BLOCKERS),
        "stage0": {
            "status": "unresolved",
            "waived": False,
            "prerequisites": list(STAGE0_PREREQUISITES),
            "prerequisites_satisfied": False,
        },
        "stages": {
            "supported": [STAGE],
            "unsupported_deferred": [
                {"stage": number, "name": name, "status": "unsupported-documentation-only"}
                for number, name in UNSUPPORTED_STAGES
            ],
        },
        "plan": {
            "schema": PLAN_SCHEMA,
            "kind": PLAN_KIND,
            "domain": PLAN_DOMAIN,
            "stage": STAGE,
            "keys": list(PLAN_KEYS),
            "binding_keys": list(BINDING_KEYS),
            "source_keys": list(SOURCE_KEYS),
            "operation_keys": list(OPERATION_KEYS),
            "limit_keys": list(LIMIT_KEYS),
            "rules": [
                "closed exact key sets, exact types, no booleans as integers",
                "references resolve only inside the review context",
                "sources are unique, in review-context order, and are exactly all review-context sources",
                "operations are serial, sequence is 1..n in list order",
                "one operation per source and command pair; the command belongs to the source profile",
                "operations are exactly the review context's stage1_required_operations in that order: identity and trust check first, then each topology source's topology and geometry commands; none omitted, added or reordered",
                "at least min_distinct_topology_sources distinct sources carry the topology command",
                "plans may lower per-operation budgets to positive values below the command ceilings",
                "max_calls equals the operation count",
                "operation bytes and timeouts are at most the command ceilings",
                "aggregate operation bytes at most limits.max_returned_bytes",
                "serial timeout sum at most limits.max_elapsed_ms",
                "limits at most the synthetic Stage 1 ceilings",
            ],
        },
        "parser_ceilings": {
            "contract_max_bytes": CONTRACT_MAX_BYTES,
            "plan_max_bytes": PLAN_MAX_BYTES,
            "plan_max_depth": PLAN_PARSER["max_depth"],
            "plan_max_items": PLAN_PARSER["max_items"],
            "plan_max_nodes": PLAN_PARSER["max_nodes"],
            "plan_max_string": PLAN_PARSER["max_string"],
        },
        "stage1_synthetic_limits": dict(STAGE1_SYNTHETIC_LIMITS),
        "stage1_synthetic_limits_note": "hypothetical planning ceilings, not reviewed Stage 0 limits",
        "review_context": REVIEW_CONTEXT,
        "review_context_sha256": review_context_sha256(),
        "binding": {
            "contract": "sha256-of-exact-contract-file-bytes",
            "implementation": "sha256-of-captured-implementation-bytes",
            "synthetic_review_context": "sha256-of-canonical-json-of-review_context",
            "graph": "plan binds contract, implementation and review context; the contract carries no digest of itself or of the implementation",
            "loader_excluded": True,
            "covers_runtime_dependencies": False,
        },
        "check_result": check_result_document(),
        "exit_codes": {"0": "show done or plan structurally valid", "1": "refused", "2": "usage"},
        "non_goals": list(NON_GOALS),
    }


def check_result_document() -> dict:
    """The one fixed success document. It contains nothing derived from any input."""
    return {
        "schema": RESULT_SCHEMA,
        "kind": RESULT_KIND,
        "status": "synthetic-plan-structurally-valid",
        "stage": STAGE,
        "meaning": "structure-only",
        "hardware_read_authorized": False,
        "execution_supported": False,
        "approval_issued": False,
        "evidence_collected": False,
        "blockers_cleared": False,
        "stage0_prerequisites_satisfied": False,
    }


# ---------------------------------------------------------------- plan validation (pure)

def _exact_keys(value, keys) -> None:
    if type(value) is not dict:
        refuse("type")
    if set(value) != set(keys):
        refuse("keys")


def _positive_int(value) -> int:
    if type(value) is not int or value < 1:
        refuse("budget-type")
    return value


def _reference(value, allowed) -> str:
    if type(value) is not str or value not in allowed:
        refuse("reference")
    return value


def _scan_forbidden(value) -> None:
    if type(value) is dict:
        for key, item in value.items():
            lowered = key.lower()
            if any(fragment in lowered for fragment in FORBIDDEN_KEY_FRAGMENTS):
                refuse("forbidden-field")
            _scan_forbidden(item)
    elif type(value) is list:
        for item in value:
            _scan_forbidden(item)


def validate_plan(plan: dict, contract: dict, actual: dict) -> None:
    """Pure structural check of one plan. Raises Refusal; returns None on a pass.

    `actual` carries the digests the caller computed from the exact captured contract
    and implementation bytes. This function performs no I/O of any kind."""
    context = contract["review_context"]
    limits_ceiling = contract["stage1_synthetic_limits"]
    if type(plan) is not dict:
        refuse("type")
    _scan_forbidden(plan)
    _exact_keys(plan, PLAN_KEYS)
    if plan["schema"] != PLAN_SCHEMA:
        refuse("schema")
    if plan["kind"] != PLAN_KIND:
        refuse("kind")
    domain = plan["domain"]
    if type(domain) is not str or domain != PLAN_DOMAIN:
        refuse("domain")
    if type(plan["stage"]) is not int:
        refuse("stage")
    if plan["stage"] != STAGE:
        refuse("stage-unsupported")

    bindings = plan["bindings"]
    _exact_keys(bindings, BINDING_KEYS)
    expected = {
        "contract_sha256": actual["contract_sha256"],
        "implementation_sha256": actual["implementation_sha256"],
        "synthetic_review_context_sha256": sha256_bytes(canonical_json(context)),
    }
    for name in BINDING_KEYS:
        value = bindings[name]
        if type(value) is not str or HEX64.match(value) is None or value != expected[name]:
            refuse("binding")

    _reference(plan["target_ref"], context["target_refs"])
    _reference(plan["trust_ref"], context["trust_refs"])
    _reference(plan["output_ref"], context["output_refs"])
    _reference(plan["recovery_ref"], context["recovery_refs"])
    _reference(plan["stop_policy_id"], context["stop_policy_ids"])

    profiles = {p["metadata_profile_id"]: p["command_ids"] for p in context["metadata_profiles"]}
    context_sources = [(s["source_ref"], s["metadata_profile_id"]) for s in context["sources"]]
    commands = {c["command_id"]: c for c in context["commands"]}

    sources = plan["sources"]
    if type(sources) is not list or not sources:
        refuse("sources")
    chosen = []
    for entry in sources:
        _exact_keys(entry, SOURCE_KEYS)
        reference = _reference(entry["source_ref"], [s for s, _ in context_sources])
        profile = entry["metadata_profile_id"]
        if type(profile) is not str or (reference, profile) not in context_sources:
            refuse("source-profile")
        chosen.append(reference)
    if len(set(chosen)) != len(chosen):
        refuse("source-duplicate")
    order = [s for s, _ in context_sources]
    if [order.index(s) for s in chosen] != sorted(order.index(s) for s in chosen):
        refuse("source-order")
    if chosen != order:
        refuse("required-sources")
    profile_of = dict(context_sources)

    operations = plan["operations"]
    if type(operations) is not list or not operations:
        refuse("operations")
    seen_pairs = set()
    used = set()
    total_bytes = 0
    total_ms = 0
    for index, operation in enumerate(operations, start=1):
        _exact_keys(operation, OPERATION_KEYS)
        sequence = operation["sequence"]
        if type(sequence) is not int:
            refuse("sequence")
        if sequence != index:
            refuse("sequence")
        source_ref = operation["source_ref"]
        if type(source_ref) is not str or source_ref not in chosen:
            refuse("dangling-source")
        command_id = operation["command_id"]
        if type(command_id) is not str or command_id not in commands:
            refuse("command")
        if command_id not in profiles[profile_of[source_ref]]:
            refuse("command-profile")
        if (source_ref, command_id) in seen_pairs:
            refuse("operation-duplicate")
        seen_pairs.add((source_ref, command_id))
        used.add(source_ref)
        returned = _positive_int(operation["max_returned_bytes"])
        timeout = _positive_int(operation["timeout_ms"])
        if returned > commands[command_id]["max_returned_bytes"]:
            refuse("operation-bytes")
        if timeout > commands[command_id]["max_timeout_ms"]:
            refuse("operation-timeout")
        total_bytes += returned
        total_ms += timeout
    if used != set(chosen):
        refuse("source-unused")

    required = [(r["source_ref"], r["command_id"]) for r in context["stage1_required_operations"]]
    planned = [(o["source_ref"], o["command_id"]) for o in operations]
    if set(planned) != set(required) or len(planned) != len(required):
        refuse("required-coverage")
    if planned != required:
        refuse("required-order")
    topology_sources = {s for s, c in planned if c == context["topology_command_id"]}
    if len(topology_sources) < context["min_distinct_topology_sources"]:
        refuse("topology-sources")

    limits = plan["limits"]
    _exact_keys(limits, LIMIT_KEYS)
    max_calls = _positive_int(limits["max_calls"])
    max_bytes = _positive_int(limits["max_returned_bytes"])
    max_ms = _positive_int(limits["max_elapsed_ms"])
    if max_calls > limits_ceiling["max_calls"] or max_bytes > limits_ceiling["max_returned_bytes"] \
            or max_ms > limits_ceiling["max_elapsed_ms"]:
        refuse("limits-ceiling")
    if max_calls != len(operations):
        refuse("calls")
    if total_bytes > max_bytes:
        refuse("aggregate-bytes")
    if total_ms > max_ms:
        refuse("elapsed")


# ---------------------------------------------------------------- reading (I/O, no validation)

def repo_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.realpath(globals()["__file__"])))


def stable_identity(info) -> tuple:
    """Everything about an open file that must not change between two fstat calls."""
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_nlink, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


def read_repo_file(relative: str, limit: int) -> bytes:
    """One trusted repository file via a no-follow chain, bounded, stable while read."""
    chain = [os.open(repo_root(), OPEN_FLAGS | os.O_DIRECTORY)]
    parts = relative.split("/")
    try:
        for part in parts[:-1]:
            chain.append(os.open(part, OPEN_FLAGS | os.O_DIRECTORY, dir_fd=chain[-1]))
        descriptor = os.open(parts[-1], OPEN_FLAGS | os.O_NONBLOCK, dir_fd=chain[-1])
    except OSError:
        refuse("repository-read")
    finally:
        for fd in chain:
            os.close(fd)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() \
                or info.st_mode & 0o022 or info.st_nlink != 1:
            refuse("repository-unsafe")
        if info.st_size > limit:
            refuse("repository-size")
        data = b""
        while len(data) <= info.st_size:
            block = os.read(descriptor, info.st_size + 1 - len(data))
            if not block:
                break
            data += block
        if len(data) != info.st_size:
            refuse("repository-race")
        if stable_identity(os.fstat(descriptor)) != stable_identity(info):
            refuse("repository-race")
    finally:
        os.close(descriptor)
    return data


def read_stdin(limit: int, descriptor: int = 0) -> bytes:
    """At most `limit` bytes from the given descriptor; one more byte refuses."""
    data = b""
    while len(data) <= limit:
        try:
            block = os.read(descriptor, limit + 1 - len(data))
        except OSError:
            refuse("stdin")
        if not block:
            break
        data += block
    if len(data) > limit:
        refuse("stdin-bound")
    return data


def load_environment() -> dict:
    contract_bytes = read_repo_file(CONTRACT_PATH, CONTRACT_MAX_BYTES)
    if contract_bytes != render_json(expected_contract()):
        refuse("contract-mismatch")
    contract = parse_json_object(contract_bytes, CONTRACT_PARSER)
    return {
        "contract_bytes": contract_bytes,
        "contract": contract,
        "actual": {
            "contract_sha256": sha256_bytes(contract_bytes),
            "implementation_sha256": globals()["CAPTURED_IMPLEMENTATION_SHA256"],
        },
    }


def check_plan(data: bytes, environment: dict) -> bytes:
    plan = parse_json_object(data, PLAN_PARSER)
    validate_plan(plan, environment["contract"], environment["actual"])
    return render_json(check_result_document())


def emit(data: bytes) -> None:
    if len(data) > OUTPUT_MAX_BYTES:
        refuse("output-bound")
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()


def run(arguments: list) -> bytes:
    if arguments == ["show"]:
        return load_environment()["contract_bytes"]
    if arguments == ["check-plan", "--stdin"]:
        environment = load_environment()
        return check_plan(read_stdin(PLAN_MAX_BYTES), environment)
    raise UsageError()


def main(arguments: list) -> int:
    if arguments == ["--version"]:
        sys.stdout.write(TOOL_VERSION + "\n")
        return 0
    if len(arguments) > MAX_ARGUMENTS or any(
            type(a) is not str or len(a.encode("utf-8", "surrogateescape")) > ARGUMENT_MAX_BYTES
            for a in arguments):
        sys.stderr.write(USAGE_FAILURE + "\n")
        return 2
    try:
        output = run(arguments)
        emit(output)
    except UsageError:
        sys.stderr.write(USAGE_FAILURE + "\n")
        return 2
    except BaseException:
        sys.stderr.write(FAILURE + "\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
