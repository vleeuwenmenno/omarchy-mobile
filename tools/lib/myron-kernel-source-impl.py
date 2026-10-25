# SPDX-License-Identifier: MIT
# Implementation of tools/myron-kernel-source (Phases 2.17 and 2.18). Executed by the trusted
# loader in the loader's namespace; never run directly. Offline, read-only: no
# subprocess, no network, no writes, no bytecode. See docs/myron/KERNEL-SOURCE-GATE.md.

import hashlib
import json
import os
import re
import stat
import sys
import xml.parsers.expat

TOOL_VERSION = "0.2.0"
CONTRACT_SCHEMA = 1
CONTRACT_PATH = "device/myron/kernel-source-contract.json"
KERNEL_CONTRACT_PATH = "device/myron/kernel-contract.json"
KERNEL_CONTRACT_SHA256 = "80321c737de5dd4ac7a671a83453c225ae23b7c2c1313e6cba0f8811ddcc8193"
KERNEL_CONTRACT_SIZE = 2781
QUALIFICATION_SHA256 = "9dffb6b7de667c7b922d451a6a569a998b8e0c8a78c4a004c1165e5dee0983c9"
PROJECT_COUNT = 50
LINK_COUNT = 4
OVERRIDE_PATHS = ("common", "build/kernel")
MANIFEST_PROJECTS = (("common", "kernel/common"), ("build/kernel", "kernel/build"))
PATCH_TARGET = "common"
PATCH_NAMES = (
    "0001-bluetooth-qca-preinitialized-ibs.patch",
    "0002-bluetooth-qca-vote-msm-geni-uart-clock.patch",
    "0003-gki-export-rmnet-module.patch",
    "0007-ipc-export-namespace-symbols.patch",
)
BUNDLE_FILES = (
    # (path, role, size, sha256, byte cap)
    ("source-lock.json", "source-lock", 10578,
     "fdf5ce28910e227bf8d22f08234d3023283e020542b38c3b9fba694f0d285f91", 64 * 1024),
    ("stamped-manifest.xml", "manifest", 269,
     "a08766933b4082d81e87a48d0f49dc11c47129ce087de9194b84291d80dc9112", 4 * 1024),
    ("vt.fragment", "fragment", 345,
     "2808f002d7eb9ac3a2ed6c0148440c6107f8c1ca29c152a84981d2eac47cc5c0", 4 * 1024),
    ("patches/0001-bluetooth-qca-preinitialized-ibs.patch", "patch", 2192,
     "21eba92d87356b41115b5bbfd90943d1f3ae331fe4c0522d498e1ce7c1bda399", 64 * 1024),
    ("patches/0002-bluetooth-qca-vote-msm-geni-uart-clock.patch", "patch", 3659,
     "b3be02fc2c92c81542e570df02a42777ae1e7ac9bf7d5f6e4f204142ec2d32ac", 64 * 1024),
    ("patches/0003-gki-export-rmnet-module.patch", "patch", 658,
     "4d95dd11c1a002f94a25a36953a1c0303132b4c2c1af57d8291baa0176da5e6c", 64 * 1024),
    ("patches/0007-ipc-export-namespace-symbols.patch", "patch", 1032,
     "7ed11e94e5d242b24e5bec1213810a1b38d31a55817c29c74e8d2709d5ac54ac", 64 * 1024),
)
BUNDLE_DIRECTORIES = ("patches",)

INVOCATION_MAX_BYTES = 512 * 1024
CONTRACT_MAX_BYTES = 64 * 1024
OUTPUT_MAX_BYTES = 64 * 1024
JSON_MAX_DEPTH = 8
JSON_MAX_STRING = 1024
JSON_MAX_ITEMS = 64
JSON_MAX_NODES = 2048
PATH_MAX_LENGTH = 256
FDINFO_PATH = "/proc/self/fdinfo"
FDINFO_MAX_BYTES = 4096

ARGUMENT_MAX_BYTES = 4096
MAX_ARGUMENTS = 3

PATCH_PROFILE_ID = "myron-patch-structure-v3"
PATCH_ARTIFACTS = 4
PATCH_FILE_SECTIONS_MAX = 16
PATCH_HUNKS_MAX = 64
PATCH_BYTES_MAX = 64 * 1024
PATCH_LINE_MAX = 8192
PATCH_PATH_MAX = 256
PATCH_DIGITS_MAX = 10
PATCH_VALUE_MAX = 2 ** 31 - 1
ENVELOPE_BYTES_MAX = 16 * 1024
ENVELOPE_LINES_MAX = 256
ENVELOPE_HEADER_LINES_MAX = 32
ENVELOPE_STAT_ROWS_MAX = 16
NO_NEWLINE_MARKER = "\\ No newline at end of file"
CLASSIFICATIONS = ("conformant", "noncanonical", "malformed", "unsupported", "limit-exceeded")
REASON_CODES = {
    "conformant": (),
    "noncanonical": ("coordinate-mismatch", "hunk-order", "duplicate-file-section",
                     "no-modifying-hunk"),
    "malformed": ("truncated", "bad-diff-header", "missing-file-header", "path-mismatch",
                  "no-hunks", "bad-hunk-header", "count-mismatch", "marker-placement",
                  "bad-index-line", "bad-envelope", "missing-separator", "bad-stat-block",
                  "bad-footer"),
    "unsupported": ("wrapper-or-prologue", "trailing-text", "non-ascii", "nul-byte",
                    "carriage-return", "extended-header", "mode-change", "new-or-deleted-file",
                    "rename-or-copy", "binary-patch", "combined-diff",
                    "symlink-or-submodule-mode", "file-mode", "unsafe-path",
                    "envelope-header", "mime-encoding", "pgp-signature", "no-diff-envelope",
                    "unknown-stat", "unknown-footer"),
    "limit-exceeded": ("artifact-bytes", "line-length", "path-length", "numeric-digits",
                       "numeric-value", "file-section-limit", "hunk-limit", "envelope-bytes", "envelope-lines",
                       "header-lines", "stat-rows"),
}
EXIT_CODES = {"0": "every patch matches the structural profile", "3": "bundle identity matched and at least one patch does not match the profile",
              "1": "identity or security prerequisite failed, or unexpected internal error",
              "2": "command-line misuse"}
HUNK_PATTERN = re.compile(
    r"@@ -(0|[1-9][0-9]*)(?:,(0|[1-9][0-9]*))? \+(0|[1-9][0-9]*)(?:,(0|[1-9][0-9]*))? @@(?: .*)?\Z")
MBOX_PATTERN = re.compile(r"From [0-9a-f]{40} Mon Sep 17 00:00:00 2001\Z")
ENVELOPE_HEADERS = ("From: ", "Date: ", "Subject: ")
HEADER_ONLY_PREFIX = "From: "
HEADER_NAME_PATTERN = re.compile(r"([\x21-\x39\x3b-\x7e]+):")
STAT_ROW_PATTERN = re.compile(r" ([^ ]+) +\| +(0|[1-9][0-9]*)(?: [+-]+)?\Z")
STAT_SUMMARY_PATTERN = re.compile(
    r" (0|[1-9][0-9]*) files? changed(?:, (0|[1-9][0-9]*) insertions?\(\+\))?"
    r"(?:, (0|[1-9][0-9]*) deletions?\(-\))?\Z")
VERSION_PATTERN = re.compile(r"[0-9]{1,3}(?:\.[0-9]{1,3}){1,3}\Z")
INDEX_PATTERN = re.compile(r"index ([0-9a-f]{4,40})\.\.([0-9a-f]{4,40})(?: ([0-7]{6}))?\Z")
HEADER_REASONS = (
    ("old mode ", "mode-change"), ("new mode ", "mode-change"),
    ("new file mode ", "new-or-deleted-file"), ("deleted file mode ", "new-or-deleted-file"),
    ("rename ", "rename-or-copy"), ("copy ", "rename-or-copy"),
    ("similarity index ", "rename-or-copy"), ("dissimilarity index ", "rename-or-copy"),
    ("Binary files ", "binary-patch"), ("GIT binary patch", "binary-patch"),
    ("diff --cc ", "combined-diff"), ("diff --combined ", "combined-diff"),
)

FAILURE = "myron-kernel-source: E_REFUSED"
USAGE_FAILURE = "myron-kernel-source: E_USAGE"

HEX40 = re.compile(r"[0-9a-f]{40}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
PATH_COMPONENT = re.compile(r"[A-Za-z0-9._+-]{1,64}\Z")
URL_PATTERN = re.compile(
    r"https://android\.googlesource\.com/"
    r"[A-Za-z0-9_+-][A-Za-z0-9._+-]*(?:/[A-Za-z0-9_+-][A-Za-z0-9._+-]*)*\Z"
)
MANIFEST_DECLARATION = b'<?xml version="1.0" encoding="UTF-8"?>\n<manifest>\n'
MANIFEST_TAIL = b"</manifest>\n"

# Test-only seam for injected races. The CLI never sets it and no environment
# variable or argument reaches it.
_HOOK = None

UNVERIFIED = (
    "source-availability",
    "revision-ancestry",
    "patch-applicability",
    "fragment-use",
    "toolchain",
    "build-output",
)
AUTHORITY = (
    "source_availability", "revision_ancestry", "patch_applicability", "fragment_use",
    "toolchain", "build_output", "activation", "deployment",
)


class Refusal(Exception):
    """A refusal. `reason` is a fixed slug for tests and is never printed."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class UsageError(Exception):
    """Command-line misuse."""


def refuse(reason: str):
    raise Refusal(reason)


def hook(stage: str, **context) -> None:
    if _HOOK is not None:
        _HOOK(stage, context)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def render_json(value) -> bytes:
    data = (json.dumps(value, indent=2, ensure_ascii=True) + "\n").encode("ascii")
    if len(data) > OUTPUT_MAX_BYTES:
        refuse("output-bound")
    return data


class Budget:
    """Total bytes one invocation may read."""

    def __init__(self, limit: int = INVOCATION_MAX_BYTES):
        self.remaining = limit

    def charge(self, count: int) -> None:
        self.remaining -= count
        if self.remaining < 0:
            refuse("invocation-bound")


# ---------------------------------------------------------------- strict JSON

def _scan_depth(text: str) -> None:
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
            if depth > JSON_MAX_DEPTH:
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


def _walk_bounds(value, depth, nodes):
    nodes[0] += 1
    if nodes[0] > JSON_MAX_NODES or depth > JSON_MAX_DEPTH:
        refuse("json-bound")
    if isinstance(value, str):
        _check_string(value)
    elif isinstance(value, dict):
        if len(value) > JSON_MAX_ITEMS:
            refuse("json-bound")
        for key, item in value.items():
            _check_string(key)
            _walk_bounds(item, depth + 1, nodes)
    elif isinstance(value, list):
        if len(value) > JSON_MAX_ITEMS:
            refuse("json-bound")
        for item in value:
            _walk_bounds(item, depth + 1, nodes)
    elif value is None or isinstance(value, (bool, int)):
        return
    else:
        refuse("json-type")


def _check_string(text: str) -> None:
    if len(text) > JSON_MAX_STRING:
        refuse("json-bound")
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        refuse("json-surrogate")


def parse_json_object(data: bytes):
    """Strict, bounded JSON object parse of already captured bytes."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        refuse("json-utf8")
    if text.startswith("﻿"):
        refuse("json-utf8")
    _scan_depth(text)
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
    _walk_bounds(value, 1, [0])
    return value


def is_int(value, expected=None) -> bool:
    return type(value) is int and (expected is None or value == expected)


def is_hex40(value) -> bool:
    return type(value) is str and HEX40.match(value) is not None


def is_hex64(value) -> bool:
    return type(value) is str and HEX64.match(value) is not None


# ---------------------------------------------------------- source-lock profile

def safe_relative_path(value) -> bool:
    if type(value) is not str or not value or len(value) > PATH_MAX_LENGTH or not value.isascii():
        return False
    for component in value.split("/"):
        if component in ("", ".", "..", ".git") or PATH_COMPONENT.match(component) is None:
            return False
        if component.startswith("-"):
            return False
    return True


def related(first: str, second: str) -> bool:
    return first == second or first.startswith(second + "/") or second.startswith(first + "/")


def within(path: str, project: str) -> bool:
    return path == project or path.startswith(project + "/")


def validate_source_lock(data: bytes, *, qualification_sha256: str, gki_revision: str,
                         project_count: int = PROJECT_COUNT, link_count: int = LINK_COUNT,
                         override_paths=OVERRIDE_PATHS) -> dict:
    lock = parse_json_object(data)
    if set(lock) != {"schema", "qualification", "manifest_revision", "superproject_revision",
                     "source_overrides", "projects", "links"}:
        refuse("lock-keys")
    if not is_int(lock["schema"], 1):
        refuse("lock-schema")
    if type(lock["qualification"]) is not str or \
            sha256_bytes(lock["qualification"].encode("utf-8")) != qualification_sha256:
        refuse("lock-qualification")
    for key in ("manifest_revision", "superproject_revision"):
        if not is_hex40(lock[key]):
            refuse("lock-revision")
    overrides = lock["source_overrides"]
    if type(overrides) is not dict or set(overrides) != set(override_paths):
        refuse("lock-overrides")
    if not all(is_hex40(value) for value in overrides.values()):
        refuse("lock-overrides")
    projects = lock["projects"]
    if type(projects) is not list or len(projects) != project_count:
        refuse("lock-projects")
    paths = []
    urls = set()
    revisions = {}
    project_urls = {}
    for record in projects:
        if type(record) is not dict or set(record) != {"path", "url", "revision"}:
            refuse("lock-project-keys")
        path, url, revision = record["path"], record["url"], record["revision"]
        if not safe_relative_path(path):
            refuse("lock-project-path")
        if type(url) is not str or len(url) > PATH_MAX_LENGTH + 64 or URL_PATTERN.match(url) is None:
            refuse("lock-project-url")
        if not is_hex40(revision):
            refuse("lock-project-revision")
        if url in urls:
            refuse("lock-project-url-duplicate")
        urls.add(url)
        for earlier in paths:
            if related(path, earlier):
                refuse("lock-project-overlap")
        paths.append(path)
        revisions[path] = revision
        project_urls[path] = url
    for path in override_paths:
        if path not in revisions or overrides[path] != revisions[path]:
            refuse("lock-override-mismatch")
    if overrides[override_paths[0]] != gki_revision:
        refuse("lock-gki-revision")
    links = lock["links"]
    if type(links) is not list or len(links) != link_count:
        refuse("lock-links")
    link_paths = []
    link_targets = []
    for record in links:
        if type(record) is not dict or set(record) != {"path", "target"}:
            refuse("lock-link-keys")
        path, target = record["path"], record["target"]
        if not safe_relative_path(path) or not safe_relative_path(target):
            refuse("lock-link-path")
        if path in link_paths or target in link_targets:
            refuse("lock-link-duplicate")
        for project in paths:
            if related(path, project):
                refuse("lock-link-collision")
        for earlier in link_paths:
            if related(path, earlier):
                refuse("lock-link-collision")
        owners = [project for project in paths if within(target, project)]
        if len(owners) != 1:
            refuse("lock-link-target")
        link_paths.append(path)
        link_targets.append(target)
    for target in link_targets:
        for path in link_paths:
            if related(target, path):
                refuse("lock-link-target")
    return {"projects": revisions, "urls": project_urls, "overrides": dict(overrides),
            "links": len(links)}


# -------------------------------------------------------------- manifest profile

def validate_manifest(data: bytes, lock: dict, manifest_projects=MANIFEST_PROJECTS,
                      override_paths=OVERRIDE_PATHS) -> int:
    if not data.isascii() or not data.startswith(MANIFEST_DECLARATION) or \
            not data.endswith(MANIFEST_TAIL):
        refuse("manifest-form")
    for needle in (b"<!", b"&", b":", b"<?xml ", b"\r", b"\t"):
        if needle in data[len(b'<?xml'):]:
            refuse("manifest-forbidden")
    events = []
    state = {"depth": 0, "text": False}

    def start(name, attributes):
        state["depth"] += 1
        events.append((state["depth"], name, attributes))

    def end(_name):
        state["depth"] -= 1

    def text(content):
        if content.strip(" \n"):
            refuse("manifest-text")

    def forbidden(*_arguments):
        refuse("manifest-forbidden")

    parser = xml.parsers.expat.ParserCreate()
    parser.ordered_attributes = True
    parser.buffer_text = False
    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = text
    parser.CommentHandler = forbidden
    parser.ProcessingInstructionHandler = forbidden
    parser.StartDoctypeDeclHandler = forbidden
    parser.EntityDeclHandler = forbidden
    parser.NotationDeclHandler = forbidden
    parser.StartCdataSectionHandler = forbidden
    parser.ExternalEntityRefHandler = forbidden
    parser.SkippedEntityHandler = forbidden
    parser.SetParamEntityParsing(xml.parsers.expat.XML_PARAM_ENTITY_PARSING_NEVER)
    try:
        parser.Parse(data, True)
    except Refusal:
        raise
    except Exception:
        refuse("manifest-syntax")
    if len(events) != 1 + len(manifest_projects):
        refuse("manifest-children")
    depth, name, attributes = events[0]
    if (depth, name, attributes) != (1, "manifest", []):
        refuse("manifest-root")
    for (path, project_name), (depth, name, attributes) in zip(manifest_projects, events[1:]):
        if depth != 2 or name != "project" or len(attributes) != 6:
            refuse("manifest-project")
        if attributes[0::2] != ["path", "name", "revision"]:
            refuse("manifest-project")
        got_path, got_name, got_revision = attributes[1::2]
        if (got_path, got_name) != (path, project_name):
            refuse("manifest-project")
        if not is_hex40(got_revision) or lock["projects"].get(path) != got_revision or \
                lock["overrides"].get(path) != got_revision:
            refuse("manifest-revision")
        if lock["urls"].get(path) != "https://android.googlesource.com/" + project_name:
            refuse("manifest-url")
    return len(manifest_projects)


# ------------------------------------------------------------ descriptor helpers

OPEN_FLAGS = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW


def identity(info) -> tuple:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_nlink, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


def mount_identifier(descriptor: int) -> int:
    try:
        fd = os.open(f"{FDINFO_PATH}/{descriptor}", os.O_RDONLY | os.O_CLOEXEC)
    except OSError:
        refuse("mount-unavailable")
    try:
        data = os.read(fd, FDINFO_MAX_BYTES)
    except OSError:
        refuse("mount-unavailable")
    finally:
        os.close(fd)
    for line in data.decode("ascii", "replace").splitlines():
        key, _, value = line.partition(":")
        if key == "mnt_id":
            try:
                return int(value.strip())
            except ValueError:
                refuse("mount-unavailable")
    refuse("mount-unavailable")


def canonical_absolute(root) -> list:
    if type(root) is not str or not root.startswith("/") or "\0" in root or \
            len(root.encode("utf-8", "surrogateescape")) > ARGUMENT_MAX_BYTES:
        refuse("root-form")
    components = root[1:].split("/")
    if not components or any(c in ("", ".", "..") for c in components):
        refuse("root-form")
    return components


def check_ancestor(info) -> None:
    if not stat.S_ISDIR(info.st_mode) or info.st_uid not in (0, os.geteuid()):
        refuse("ancestor-unsafe")
    if info.st_mode & 0o022 and not (info.st_mode & stat.S_ISVTX and info.st_uid == 0):
        refuse("ancestor-unsafe")


def open_root(root) -> int:
    """No-follow descriptor for the bundle root with every ancestor checked."""
    components = canonical_absolute(root)
    descriptor = os.open("/", OPEN_FLAGS | os.O_DIRECTORY)
    try:
        check_ancestor(os.fstat(descriptor))
        for index, component in enumerate(components):
            try:
                following = os.open(component, OPEN_FLAGS | os.O_DIRECTORY, dir_fd=descriptor)
            except OSError:
                refuse("root-open")
            os.close(descriptor)
            descriptor = following
            if index != len(components) - 1:
                check_ancestor(os.fstat(descriptor))
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def enumerate_names(descriptor: int, expected: set) -> None:
    """List one directory, stopping at one more entry than expected."""
    seen = set()
    with os.scandir(descriptor) as entries:
        for entry in entries:
            seen.add(entry.name)
            if len(seen) > len(expected):
                refuse("directory-extra")
    if seen != expected:
        refuse("directory-membership")


def check_private_directory(info, mount: int, descriptor: int) -> None:
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or \
            stat.S_IMODE(info.st_mode) != 0o700:
        refuse("directory-unsafe")
    if mount_identifier(descriptor) != mount:
        refuse("mount-crossing")


def read_bounded(descriptor: int, size: int, budget: Budget) -> bytes:
    """Read exactly the pinned size, asking for size+1 so growth is detected."""
    budget.charge(size + 1)
    data = b""
    while len(data) <= size:
        block = os.read(descriptor, size + 1 - len(data))
        if not block:
            break
        data += block
    if len(data) != size:
        refuse("file-size")
    return data


def capture_file(directory: int, name: str, size: int, mount: int, budget: Budget,
                 path: str) -> bytes:
    try:
        before = os.lstat(name, dir_fd=directory)
    except OSError:
        refuse("file-missing")
    if not stat.S_ISREG(before.st_mode):
        refuse("file-type")
    try:
        descriptor = os.open(name, OPEN_FLAGS | os.O_NONBLOCK, dir_fd=directory)
    except OSError:
        refuse("file-open")
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            refuse("file-type")
        if identity(info) != identity(before):
            refuse("file-race")
        if info.st_uid != os.geteuid() or info.st_nlink != 1 or \
                stat.S_IMODE(info.st_mode) != 0o600:
            refuse("file-unsafe")
        if info.st_size != size:
            refuse("file-size")
        if mount_identifier(descriptor) != mount:
            refuse("mount-crossing")
        hook("file-opened", path=path)
        data = read_bounded(descriptor, size, budget)
        hook("file-read", path=path)
        after = os.fstat(descriptor)
        if identity(after) != identity(info):
            refuse("file-race")
    finally:
        os.close(descriptor)
    try:
        named = os.lstat(name, dir_fd=directory)
    except OSError:
        refuse("file-race")
    if identity(named) != identity(info):
        refuse("file-race")
    return data


def verify_bundle(root, files, directories, budget: Budget) -> dict:
    """Capture every pinned file once and return {path: bytes}; refuse on any difference."""
    top_names = {path for path, *_ in files if "/" not in path} | set(directories)
    top = open_root(root)
    children = {}
    try:
        info = os.fstat(top)
        mount = mount_identifier(top)
        check_private_directory(info, mount, top)
        enumerate_names(top, top_names)
        opened = {}
        directory_info = {}
        try:
            for name in directories:
                try:
                    child = os.open(name, OPEN_FLAGS | os.O_DIRECTORY, dir_fd=top)
                except OSError:
                    refuse("directory-open")
                opened[name] = child
                directory_info[name] = os.fstat(child)
                check_private_directory(directory_info[name], mount, child)
                if identity(os.lstat(name, dir_fd=top)) != identity(directory_info[name]):
                    refuse("directory-race")
                enumerate_names(child, {path.split("/", 1)[1] for path, *_ in files
                                        if path.startswith(name + "/")})
            hook("directories-enumerated", path="")
            for path, _role, size, digest, cap in files:
                if size > cap:
                    refuse("file-bound")
                parts = path.split("/")
                directory = top if len(parts) == 1 else opened[parts[0]]
                data = capture_file(directory, parts[-1], size, mount, budget, path)
                if sha256_bytes(data) != digest:
                    refuse("file-hash")
                children[path] = data
            hook("files-read", path="")
            if identity(os.fstat(top)) != identity(info):
                refuse("directory-race")
            enumerate_names(top, top_names)
            for name in directories:
                child = opened[name]
                if identity(os.fstat(child)) != identity(directory_info[name]):
                    refuse("directory-race")
                if identity(os.lstat(name, dir_fd=top)) != identity(directory_info[name]):
                    refuse("directory-race")
                enumerate_names(child, {path.split("/", 1)[1] for path, *_ in files
                                        if path.startswith(name + "/")})
        finally:
            for child in opened.values():
                os.close(child)
    finally:
        os.close(top)
    again = open_root(root)
    try:
        if identity(os.fstat(again)) != identity(info):
            refuse("directory-race")
    finally:
        os.close(again)
    return children


def capture_bundle(root, spec: dict, budget: Budget = None) -> tuple:
    """Verify identity and the pinned structure once; return (summary, captured bytes).

    The captured buffers are the only bytes any later stage may use."""
    budget = budget or Budget()
    files = spec["files"]
    captured = verify_bundle(root, files, spec["directories"], budget)
    lock = validate_source_lock(
        captured["source-lock.json"], qualification_sha256=spec["qualification_sha256"],
        gki_revision=spec["gki_revision"], project_count=spec["project_count"],
        link_count=spec["link_count"])
    manifest_projects = validate_manifest(captured["stamped-manifest.xml"], lock)
    patches = [path for path, role, *_ in files if role == "patch"]
    if [p.split("/", 1)[1] for p in patches] != list(spec["patch_names"]):
        refuse("patch-order")
    summary = {"files": len(files), "directories": len(spec["directories"]),
               "projects": len(lock["projects"]), "links": lock["links"],
               "overrides": len(lock["overrides"]), "manifest_projects": manifest_projects,
               "patches": len(patches)}
    return summary, captured


def check_bundle(root, spec: dict, budget: Budget = None) -> dict:
    """Closure, lock, manifest and pinned patch order; patch bodies are not examined."""
    return capture_bundle(root, spec, budget)[0]


# ------------------------------------------------------- patch structure profile

def patch_profile() -> dict:
    """The versioned structural profile: the contract's own text and the analyzer's limits."""
    return {
        "id": PATCH_PROFILE_ID,
        "artifacts": PATCH_ARTIFACTS,
        "file_sections": {"min": 1, "max": PATCH_FILE_SECTIONS_MAX},
        "hunks": {"min": 1, "max": PATCH_HUNKS_MAX, "modifying_per_section_min": 1},
        "artifact_bytes": PATCH_BYTES_MAX,
        "line_bytes_max": PATCH_LINE_MAX,
        "path_bytes_max": PATCH_PATH_MAX,
        "numeric": {"digits_max": PATCH_DIGITS_MAX, "value_max": PATCH_VALUE_MAX,
                    "leading_zeros": False},
        "encoding": "ascii-lf-no-nul-no-cr",
        "format": "bare-or-named-envelope-git-unified-diff-modification-only",
        "envelope": {
            "selection": "only at byte zero: the exact mbox line selects the mbox variant, a "
                         "first line starting exactly 'From: ' selects the header-only variant; "
                         "never searched for, resynchronized or backtracked to a later diff or "
                         "separator",
            "prelude_bytes_max": ENVELOPE_BYTES_MAX,
            "prelude_lines_max": ENVELOPE_LINES_MAX,
            "header_lines_max": ENVELOPE_HEADER_LINES_MAX,
            "stat_rows_max": ENVELOPE_STAT_ROWS_MAX,
            "values": "framing and bounds only; author, address, date, subject, message and "
                      "commit id are not interpreted, decoded, retained, hashed or emitted",
            "acceptance": "a named framing match only; not authorship, authenticity, "
                          "provenance, Git generation, message, diffstat or applicability",
        },
        "grammar": [
            "artifact := bare-diff EOF | envelope diff-sections ending",
            "bare-diff := file-section{1..16}; nothing before, between or after",
            "envelope := mbox-envelope | header-only-envelope",
            "mbox-envelope := mbox-line headers LF message '---' LF [stat-block]",
            "header-only-envelope := from-field [date-field] subject-field LF message "
            "'---' LF [stat-block]; selected only when the first line starts 'From: '",
            "mbox-line := 'From ' HEX{40} ' Mon Sep 17 00:00:00 2001' LF",
            "headers := from-field date-field subject-field, in that order, once each",
            "from-field := 'From: ' OPAQUE LF continuation*; date-field := 'Date: ' OPAQUE LF "
            "continuation*; subject-field := 'Subject: ' OPAQUE LF continuation*; "
            "continuation := (SP | HTAB) OPAQUE LF; Date is optional only in the header-only "
            "variant",
            "OPAQUE := nonempty printable ASCII and HTAB",
            "message := (printable ASCII, HTAB or empty) LF lines up to the first exact '---' "
            "line; the separator is never retried; a diff-looking line before it is message "
            "text",
            "separator := '---' LF immediately followed by 'diff --git' or by a stat-block "
            "immediately followed by 'diff --git'",
            "stat-block := row{1..16} summary LF; row := ' REL' SP+ '|' SP+ COUNT "
            "[' ' [+-]+] LF; summary := ' N file[s] changed' [', N insertion[s](+)'] "
            "[', N deletion[s](-)'] LF; framing only, no agreement with hunks",
            "ending := EOF | '-- ' LF VERSION LF EOF, after at least one complete file "
            "section; VERSION := N(.N){1..3}, N of 1..3 digits",
            "file-section := 'diff --git a/REL b/REL' LF [index-line] '--- a/REL' LF "
            "'+++ b/REL' LF hunk+",
            "index-line := 'index HEX{4,40}..HEX{4,40}' [' 100644' | ' 100755'] LF",
            "hunk := '@@ -S[,C] +S[,C] @@' [' ' TEXT] LF body",
            "body := lines prefixed ' ', '-' or '+', consumed by the declared old and new "
            "counts, each optionally followed by '\\ No newline at end of file' LF",
            "REL := ASCII 0x21-0x7e without double quote or backslash, components not empty, "
            "'.', '..' or '.git'; the same in all four places of a section",
        ],
        "coordinate_policy": {
            "name": "cumulative-boundary-v1",
            "boundary": "start - 1 if count > 0 else start",
            "expected_new_boundary": "old boundary + sum of prior (new_count - old_count)",
            "order": "old side and new side monotonic and non-overlapping within a file section",
            "reset": "every file section and every artifact; nothing carries across the series",
            "shared_paths": "repeated-file participation only; no dependency, order or "
                            "applicability claim",
        },
        "excluded": ["any mail framing other than the named envelope and ending",
                     "unknown, extra, duplicate or reordered headers; MIME or transfer encodings",
                     "cover letter without a diff; PGP; unknown stat block or signature",
                     "new, deleted, renamed or copied file",
                     "binary or combined diff", "mode change or mode-only section",
                     "symlink or submodule mode", "quoted, escaped or control-character path",
                     "any other extended header", "any unconsumed text"],
        "classifications": list(CLASSIFICATIONS),
        "reason_codes": {name: list(codes) for name, codes in REASON_CODES.items()},
        "exit_codes": dict(EXIT_CODES),
        "claims": ["patch_structure_admission"],
        "patch_applicability": False,
        "application_performed": False,
    }


class Stop(Exception):
    """Analysis of one artifact ended in a non-admitted class. Never printed."""

    def __init__(self, classification: str, reason: str):
        super().__init__(reason)
        self.classification = classification
        self.reason = reason


def stop(classification: str, reason: str):
    raise Stop(classification, reason)


class LineReader:
    """Lines of one captured buffer, each checked against the byte profile as it is reached."""

    def __init__(self, data: bytes, profile: dict):
        if len(data) > profile["artifact_bytes"]:
            stop("limit-exceeded", "artifact-bytes")
        self.line_max = profile["line_bytes_max"]
        lines = data.split(b"\n")
        self.tail = lines.pop()
        self.lines = lines
        self.index = 0
        self.envelope = profile["envelope"]
        self.prelude_bytes = self.prelude_lines = 0

    def peek(self):
        if self.index < len(self.lines):
            raw = self.lines[self.index]
        elif self.index == len(self.lines) and self.tail:
            raw = self.tail
        else:
            return None
        if len(raw) > self.line_max:
            stop("limit-exceeded", "line-length")
        if b"\0" in raw:
            stop("unsupported", "nul-byte")
        if b"\r" in raw:
            stop("unsupported", "carriage-return")
        if not raw.isascii():
            stop("unsupported", "non-ascii")
        if self.index == len(self.lines):
            stop("malformed", "truncated")
        return raw.decode("ascii")

    def take(self):
        line = self.peek()
        if line is not None:
            self.index += 1
        return line

    def take_prelude(self):
        """Take one envelope line and account it against the prelude bounds."""
        line = self.take()
        if line is None:
            stop("malformed", "truncated")
        self.prelude_bytes += len(line) + 1
        self.prelude_lines += 1
        if self.prelude_bytes > self.envelope["prelude_bytes_max"]:
            stop("limit-exceeded", "envelope-bytes")
        if self.prelude_lines > self.envelope["prelude_lines_max"]:
            stop("limit-exceeded", "envelope-lines")
        return line


def check_patch_path(path: str, profile: dict) -> None:
    if len(path) > profile["path_bytes_max"]:
        stop("limit-exceeded", "path-length")
    if not path or any(not 0x21 <= ord(c) <= 0x7e or c in '"\\' for c in path):
        stop("unsupported", "unsafe-path")
    for component in path.split("/"):
        if component in ("", ".", "..") or component.lower() == ".git":
            stop("unsupported", "unsafe-path")


def expect_name(line: str, marker: str, side: str, relative: str, profile: dict) -> None:
    if line == marker + side + relative:
        return
    name = line[len(marker):]
    if name == "/dev/null":
        stop("unsupported", "new-or-deleted-file")
    if name.startswith(side):
        check_patch_path(name[len(side):], profile)
        stop("malformed", "path-mismatch")
    stop("malformed", "missing-file-header")


def parse_index_line(line: str) -> None:
    match = INDEX_PATTERN.match(line)
    if match is None:
        stop("malformed", "bad-index-line")
    mode = match.group(3)
    if mode in ("120000", "160000"):
        stop("unsupported", "symlink-or-submodule-mode")
    if mode not in (None, "100644", "100755"):
        stop("unsupported", "file-mode")


def parse_hunk(reader: LineReader, profile: dict, ended: list) -> tuple:
    """One hunk; ended = [old, new] no-newline flags that persist across the section."""
    line = reader.take()
    match = HUNK_PATTERN.match(line)
    if match is None:
        stop("malformed", "bad-hunk-header")
    for digits in match.groups():
        if digits is not None:
            if len(digits) > profile["numeric"]["digits_max"]:
                stop("limit-exceeded", "numeric-digits")
            if int(digits) > profile["numeric"]["value_max"]:
                stop("limit-exceeded", "numeric-value")
    old_start, new_start = int(match.group(1)), int(match.group(3))
    old_count = 1 if match.group(2) is None else int(match.group(2))
    new_count = 1 if match.group(4) is None else int(match.group(4))
    old_seen = new_seen = 0
    previous = None
    modifying = old_count != new_count
    while old_seen < old_count or new_seen < new_count:
        line = reader.peek()
        if line is None:
            stop("malformed", "truncated")
        kind = line[:1]
        if kind == "\\":
            if previous not in (" ", "-", "+") or line != NO_NEWLINE_MARKER:
                stop("malformed", "marker-placement")
            ended[0] = ended[0] or previous in (" ", "-")
            ended[1] = ended[1] or previous in (" ", "+")
            previous = "\\"
            reader.take()
            continue
        if kind not in (" ", "-", "+"):
            stop("malformed", "count-mismatch")
        takes_old = kind in (" ", "-")
        takes_new = kind in (" ", "+")
        if (takes_old and old_seen >= old_count) or (takes_new and new_seen >= new_count):
            stop("malformed", "count-mismatch")
        if (takes_old and ended[0]) or (takes_new and ended[1]):
            stop("malformed", "marker-placement")
        old_seen += takes_old
        new_seen += takes_new
        modifying = modifying or kind != " "
        previous = kind
        reader.take()
    line = reader.peek()
    if line is not None and line.startswith("\\"):
        if previous not in (" ", "-", "+") or line != NO_NEWLINE_MARKER:
            stop("malformed", "marker-placement")
        ended[0] = ended[0] or previous in (" ", "-")
        ended[1] = ended[1] or previous in (" ", "+")
        reader.take()
    return old_start, old_count, new_start, new_count, modifying


def parse_section(reader: LineReader, profile: dict, hunks_so_far: int) -> tuple:
    """One file section: (relative path, hunk tuples)."""
    rest = reader.take()[len("diff --git "):]
    if rest.startswith('"'):
        stop("unsupported", "unsafe-path")
    parts = rest.split(" ")
    if len(parts) > 2:
        stop("unsupported", "unsafe-path")
    if len(parts) != 2 or not parts[0].startswith("a/") or not parts[1].startswith("b/"):
        stop("malformed", "bad-diff-header")
    relative, other = parts[0][2:], parts[1][2:]
    check_patch_path(relative, profile)
    check_patch_path(other, profile)
    if relative != other:
        stop("malformed", "path-mismatch")
    seen_index = False
    while True:
        line = reader.peek()
        if line is None:
            stop("malformed", "truncated")
        if line.startswith("--- "):
            break
        if line.startswith("index ") and not seen_index:
            parse_index_line(line)
            seen_index = True
            reader.take()
            continue
        if line.startswith(("diff --git ", "@@", "+++ ")):
            stop("malformed", "missing-file-header")
        for prefix, reason in HEADER_REASONS:
            if line.startswith(prefix):
                stop("unsupported", reason)
        stop("unsupported", "extended-header")
    expect_name(reader.take(), "--- ", "a/", relative, profile)
    line = reader.take()
    if line is None:
        stop("malformed", "truncated")
    if not line.startswith("+++ "):
        stop("malformed", "missing-file-header")
    expect_name(line, "+++ ", "b/", relative, profile)
    hunks = []
    ended = [False, False]
    while True:
        line = reader.peek()
        if line is None or not line.startswith("@@"):
            break
        if line.startswith("@@@"):
            stop("unsupported", "combined-diff")
        if hunks_so_far + len(hunks) + 1 > profile["hunks"]["max"]:
            stop("limit-exceeded", "hunk-limit")
        hunks.append(parse_hunk(reader, profile, ended))
    if not hunks:
        stop("malformed", "truncated" if line is None else "no-hunks")
    return relative, hunks


def section_reasons(hunks: list) -> set:
    """Coordinate and modification consistency of one parsed section."""
    reasons = set()
    if not any(hunk[4] for hunk in hunks):
        reasons.add("no-modifying-hunk")
    delta = 0
    old_end = new_end = None
    for old_start, old_count, new_start, new_count, _modifying in hunks:
        if (old_count > 0 and old_start == 0) or (new_count > 0 and new_start == 0):
            reasons.add("coordinate-mismatch")
        old_boundary = old_start - 1 if old_count > 0 else old_start
        new_boundary = new_start - 1 if new_count > 0 else new_start
        if old_end is not None and (old_boundary < old_end or new_boundary < new_end):
            reasons.add("hunk-order")
        if new_boundary != old_boundary + delta:
            reasons.add("coordinate-mismatch")
        old_end = old_boundary + old_count
        new_end = new_boundary + new_count
        delta += new_count - old_count
    return reasons


def opaque(text: str) -> bool:
    return bool(text) and all(c == "\t" or " " <= c <= "~" for c in text)


def unexpected_header(line: str) -> None:
    """A line where only a recognized framing line may stand: classify it, never accept it."""
    match = HEADER_NAME_PATTERN.match(line)
    if match is None:
        stop("malformed", "bad-envelope")
    if match.group(1).lower().startswith(("mime-", "content-")):
        stop("unsupported", "mime-encoding")
    stop("unsupported", "envelope-header")


def parse_envelope_headers(reader: LineReader, profile: dict, header_only: bool) -> None:
    """mbox variant: the mbox line is taken first and all three headers are required.
    Header-only variant: the first line is the From header and Date alone is optional."""
    if not header_only:
        reader.take_prelude()
    header_lines = 0
    limit = profile["envelope"]["header_lines_max"]
    for name in ENVELOPE_HEADERS:
        line = reader.peek()
        if line is None:
            stop("malformed", "truncated")
        if header_only and name == "Date: " and not line.startswith(name):
            continue
        if not line.startswith(name):
            unexpected_header(line)
        if header_lines + 1 > limit:
            stop("limit-exceeded", "header-lines")
        if not opaque(line[len(name):]):
            stop("malformed", "bad-envelope")
        reader.take_prelude()
        header_lines += 1
        while True:
            line = reader.peek()
            if line is None:
                stop("malformed", "truncated")
            if line[:1] not in (" ", "\t"):
                break
            if not opaque(line[1:]):
                stop("malformed", "bad-envelope")
            if header_lines + 1 > limit:
                stop("limit-exceeded", "header-lines")
            reader.take_prelude()
            header_lines += 1
    line = reader.peek()
    if line is None:
        stop("malformed", "truncated")
    if line != "":
        unexpected_header(line)
    reader.take_prelude()


def parse_envelope_message(reader: LineReader) -> None:
    """Message text up to the first exact separator; it is never searched for again."""
    while True:
        line = reader.peek()
        if line is None:
            stop("malformed", "missing-separator")
        if line == "---":
            reader.take_prelude()
            return
        if line and not opaque(line):
            stop("malformed", "bad-envelope")
        if line.startswith("-----BEGIN PGP"):
            stop("unsupported", "pgp-signature")
        reader.take_prelude()


def parse_stat_block(reader: LineReader, profile: dict) -> None:
    numeric = profile["numeric"]

    def count(digits):
        if len(digits) > numeric["digits_max"]:
            stop("limit-exceeded", "numeric-digits")
        if int(digits) > numeric["value_max"]:
            stop("limit-exceeded", "numeric-value")

    rows = 0
    while True:
        line = reader.peek()
        if line is None:
            stop("malformed", "truncated")
        row = STAT_ROW_PATTERN.match(line)
        if row is None:
            break
        if rows + 1 > profile["envelope"]["stat_rows_max"]:
            stop("limit-exceeded", "stat-rows")
        try:
            check_patch_path(row.group(1), profile)
        except Stop as error:
            if error.classification == "limit-exceeded":
                raise
            stop("malformed", "bad-stat-block")
        count(row.group(2))
        reader.take_prelude()
        rows += 1
    summary = STAT_SUMMARY_PATTERN.match(line)
    if rows == 0 or summary is None:
        stop("malformed", "bad-stat-block")
    for digits in summary.groups():
        if digits is not None:
            count(digits)
    reader.take_prelude()
    line = reader.peek()
    if line is None:
        stop("malformed", "truncated")
    if line != "":
        stop("unsupported", "unknown-stat")
    reader.take_prelude()


def parse_envelope(reader: LineReader, profile: dict, header_only: bool) -> None:
    """Named envelope variant up to, not including, the first diff line."""
    parse_envelope_headers(reader, profile, header_only)
    parse_envelope_message(reader)
    line = reader.peek()
    if line is None:
        stop("malformed", "truncated")
    if line.startswith(" "):
        parse_stat_block(reader, profile)
        line = reader.peek()
        if line is None:
            stop("malformed", "truncated")
    if line.startswith("diff --git "):
        return
    stop("unsupported", "combined-diff" if line.startswith(
        ("diff --cc ", "diff --combined ")) else "no-diff-envelope")


def parse_footer(reader: LineReader) -> None:
    """'-- ' LF VERSION LF EOF after a completed section; nothing else is an ending."""
    reader.take()
    line = reader.take()
    if line is None:
        stop("malformed", "bad-footer")
    if VERSION_PATTERN.match(line) is None:
        stop("unsupported", "unknown-footer")
    if reader.peek() is not None:
        stop("unsupported", "trailing-text")


def analyze_artifact(data: bytes, profile: dict) -> tuple:
    """(allowlisted result, relative paths); the paths are returned only on a complete parse."""
    try:
        reader = LineReader(data, profile)
        first = reader.peek()
        if first is None:
            stop("malformed", "truncated")
        header_only = first.startswith(HEADER_ONLY_PREFIX)
        enveloped = header_only or MBOX_PATTERN.match(first) is not None
        if enveloped:
            parse_envelope(reader, profile, header_only)
        elif not first.startswith("diff --git "):
            stop("unsupported", "combined-diff" if first.startswith(
                ("diff --cc ", "diff --combined ")) else "wrapper-or-prologue")
        reasons = set()
        paths = []
        hunk_total = 0
        while True:
            line = reader.peek()
            if line is None:
                break
            if enveloped and paths and line == "-- ":
                parse_footer(reader)
                break
            if not line.startswith("diff --git "):
                stop("unsupported", "combined-diff" if line.startswith(
                    ("diff --cc ", "diff --combined ")) else "trailing-text")
            if len(paths) + 1 > profile["file_sections"]["max"]:
                stop("limit-exceeded", "file-section-limit")
            relative, hunks = parse_section(reader, profile, hunk_total)
            if relative in paths:
                reasons.add("duplicate-file-section")
            paths.append(relative)
            hunk_total += len(hunks)
            reasons |= section_reasons(hunks)
    except Stop as error:
        return {"classification": error.classification, "parse_complete": False,
                "file_count": None, "hunk_count": None,
                "reason_codes": [error.reason]}, None
    return {"classification": "noncanonical" if reasons else "conformant",
            "parse_complete": True, "file_count": len(paths), "hunk_count": hunk_total,
            "reason_codes": sorted(reasons)}, paths


def analyze_patch_series(patches: tuple, profile: dict) -> dict:
    """Pure structural analysis of captured patch buffers: no I/O, allowlisted metadata only."""
    if type(patches) is not tuple or len(patches) != profile["artifacts"] or \
            any(type(patch) is not bytes for patch in patches):
        refuse("patch-series")
    results = []
    path_sets = []
    for data in patches:
        result, paths = analyze_artifact(data, profile)
        results.append(result)
        path_sets.append(None if paths is None else set(paths))
    complete = all(paths is not None for paths in path_sets)
    entries = []
    for index, result in enumerate(results):
        entry = {"patch_index": index + 1, **result}
        if complete:
            others = set().union(*(p for i, p in enumerate(path_sets) if i != index))
            entry["repeated_file_group_count"] = len(path_sets[index] & others)
        entries.append(entry)
    return {"structural_profile_matched": all(r["classification"] == "conformant"
                                              for r in results),
            "patches": entries}


def analysis_document(analysis: dict) -> dict:
    return {
        "schema": CONTRACT_SCHEMA,
        "kind": "myron-kernel-source-patch-analysis",
        "version": TOOL_VERSION,
        "profile": PATCH_PROFILE_ID,
        "scope": "patch-structure-only",
        "bundle_identity": "matched",
        "structural_profile_matched": analysis["structural_profile_matched"],
        "patches": analysis["patches"],
        "application_performed": False,
        "authority": {name: False for name in AUTHORITY},
        "activation": {"mode": "disabled", "blocker": "unchanged"},
        "unverified": list(UNVERIFIED),
    }


def validate_analysis_document(document: dict, profile: dict) -> None:
    """Refuse anything but the allowlisted shape, so no stray value can reach stdout."""
    def exact(value, keys):
        if type(value) is not dict or list(value) != list(keys):
            refuse("analysis-invalid")

    exact(document, ("schema", "kind", "version", "profile", "scope", "bundle_identity",
                     "structural_profile_matched", "patches", "application_performed",
                     "authority", "activation", "unverified"))
    fixed = {"schema": CONTRACT_SCHEMA, "kind": "myron-kernel-source-patch-analysis",
             "version": TOOL_VERSION, "profile": PATCH_PROFILE_ID, "scope": "patch-structure-only",
             "bundle_identity": "matched"}
    for key, value in fixed.items():
        if type(document[key]) is not type(value) or document[key] != value:
            refuse("analysis-invalid")
    if document["application_performed"] is not False or \
            document["activation"] != {"mode": "disabled", "blocker": "unchanged"} or \
            document["unverified"] != list(UNVERIFIED):
        refuse("analysis-invalid")
    exact(document["authority"], AUTHORITY)
    if any(value is not False for value in document["authority"].values()):
        refuse("analysis-invalid")
    patches = document["patches"]
    if type(patches) is not list or len(patches) != profile["artifacts"]:
        refuse("analysis-invalid")
    grouped = ["repeated_file_group_count" in entry for entry in patches
               if type(entry) is dict]
    if len(grouped) != len(patches) or len(set(grouped)) != 1:
        refuse("analysis-invalid")
    complete = True
    for index, entry in enumerate(patches):
        exact(entry, ("patch_index", "classification", "parse_complete", "file_count",
                      "hunk_count", "reason_codes") +
              (("repeated_file_group_count",) if grouped[0] else ()))
        if entry["patch_index"] != index + 1 or type(entry["patch_index"]) is not int:
            refuse("analysis-invalid")
        name = entry["classification"]
        if type(name) is not str or name not in REASON_CODES:
            refuse("analysis-invalid")
        parsed = name in ("conformant", "noncanonical")
        complete = complete and parsed
        reasons = entry["reason_codes"]
        if entry["parse_complete"] is not parsed or type(reasons) is not list or \
                reasons != sorted(set(reasons)) or \
                any(type(r) is not str or r not in REASON_CODES[name] for r in reasons):
            refuse("analysis-invalid")
        if name == "conformant" and reasons or name == "noncanonical" and not reasons or \
                name not in ("conformant", "noncanonical") and len(reasons) != 1:
            refuse("analysis-invalid")
        for key, low, high in (("file_count", 1, profile["file_sections"]["max"]),
                               ("hunk_count", 1, profile["hunks"]["max"])):
            value = entry[key]
            if parsed:
                if type(value) is not int or not low <= value <= high:
                    refuse("analysis-invalid")
            elif value is not None:
                refuse("analysis-invalid")
        if grouped[0]:
            value = entry["repeated_file_group_count"]
            if type(value) is not int or not 0 <= value <= profile["file_sections"]["max"]:
                refuse("analysis-invalid")
    if grouped[0] and not complete:
        refuse("analysis-invalid")
    matched = document["structural_profile_matched"]
    if matched is not all(entry["classification"] == "conformant" for entry in patches):
        refuse("analysis-invalid")


def analyze_command(root, spec: dict, budget: Budget = None) -> tuple:
    """Identity first, then analysis of the same captured buffers; (output bytes, exit status)."""
    _summary, captured = capture_bundle(root, spec, budget)
    patches = tuple(captured[path] for path, role, *_ in spec["files"] if role == "patch")
    analysis = analyze_patch_series(patches, spec["profile"])
    document = analysis_document(analysis)
    validate_analysis_document(document, spec["profile"])
    return render_json(document), 0 if analysis["structural_profile_matched"] else 3


# --------------------------------------------------------------- repository side

def repo_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.realpath(globals()["__file__"])))


def read_repo_file(relative: str, limit: int, budget: Budget, exact: int = None) -> bytes:
    flags = OPEN_FLAGS
    chain = [os.open(repo_root(), flags | os.O_DIRECTORY)]
    parts = relative.split("/")
    try:
        for part in parts[:-1]:
            chain.append(os.open(part, flags | os.O_DIRECTORY, dir_fd=chain[-1]))
        descriptor = os.open(parts[-1], flags | os.O_NONBLOCK, dir_fd=chain[-1])
    except OSError:
        refuse("repository-read")
    finally:
        for fd in chain:
            os.close(fd)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o022:
            refuse("repository-unsafe")
        if info.st_size > limit or (exact is not None and info.st_size != exact):
            refuse("repository-size")
        data = read_bounded(descriptor, info.st_size, budget)
        if identity(os.fstat(descriptor)) != identity(info):
            refuse("repository-race")
    finally:
        os.close(descriptor)
    return data


def expected_contract() -> dict:
    return {
        "schema": CONTRACT_SCHEMA,
        "kind": "myron-kernel-source-contract",
        "version": TOOL_VERSION,
        "kernel_contract": {
            "path": KERNEL_CONTRACT_PATH,
            "sha256": KERNEL_CONTRACT_SHA256,
            "size": KERNEL_CONTRACT_SIZE,
        },
        "bundle": {
            "root": "external-private-absolute-path",
            "directories": list(BUNDLE_DIRECTORIES),
            "files": [{"path": path, "role": role, "size": size, "sha256": digest}
                      for path, role, size, digest, _cap in BUNDLE_FILES],
            "derived_from_kernel_contract": [
                "source.lock_sha256", "source.manifest_sha256", "source.patches"],
            "new_pin": "vt.fragment",
            "qualification_sha256": QUALIFICATION_SHA256,
            "patch_order": list(PATCH_NAMES),
            "patch_target": PATCH_TARGET,
            "patches_not_pinned": ["0004", "0005", "0006"],
        },
        "source_lock_profile": {
            "schema": 1,
            "projects": PROJECT_COUNT,
            "links": LINK_COUNT,
            "overrides": list(OVERRIDE_PATHS),
            "gki_revision_binding": "kernel.gki_source_revision",
            "manifest_projects": [{"path": p, "name": n} for p, n in MANIFEST_PROJECTS],
        },
        "filesystem": {
            "root_mode": "0700", "directory_mode": "0700", "file_mode": "0600",
            "link_count": 1, "mount_check": "fdinfo-mnt_id-fail-closed",
            "atomic_snapshot": False, "same_user_writer_protection": False,
        },
        "limits": {
            "invocation_bytes": INVOCATION_MAX_BYTES,
            "contract_and_lock_bytes": CONTRACT_MAX_BYTES,
            "manifest_and_fragment_bytes": 4096,
            "patch_bytes": 64 * 1024,
            "json_depth": JSON_MAX_DEPTH,
            "output_bytes": OUTPUT_MAX_BYTES,
        },
        "patch_structure_profile": patch_profile(),
        "bytes_distributed": False,
        "authority": {name: False for name in AUTHORITY},
        "activation": {"mode": "disabled", "blocker": "unchanged"},
        "unverified": list(UNVERIFIED),
    }


def load_environment(budget: Budget = None) -> dict:
    """Validate the repository contract and its kernel-contract binding."""
    budget = budget or Budget()
    kernel_bytes = read_repo_file(KERNEL_CONTRACT_PATH, CONTRACT_MAX_BYTES, budget,
                                  exact=KERNEL_CONTRACT_SIZE)
    if sha256_bytes(kernel_bytes) != KERNEL_CONTRACT_SHA256:
        refuse("kernel-contract-hash")
    kernel = parse_json_object(kernel_bytes)
    contract_bytes = read_repo_file(CONTRACT_PATH, CONTRACT_MAX_BYTES, budget)
    if contract_bytes != render_json(expected_contract()):
        refuse("contract-mismatch")
    parse_json_object(contract_bytes)
    source = kernel.get("source")
    if type(source) is not dict or type(source.get("patches")) is not dict:
        refuse("kernel-source")
    if source.get("lock_sha256") != BUNDLE_FILES[0][3] or \
            source.get("manifest_sha256") != BUNDLE_FILES[1][3]:
        refuse("kernel-source")
    patch_pins = {path.split("/", 1)[1]: digest
                  for path, role, _size, digest, _cap in BUNDLE_FILES if role == "patch"}
    if list(source["patches"]) != list(PATCH_NAMES) or source["patches"] != patch_pins:
        refuse("kernel-patches")
    revision = kernel.get("kernel", {}).get("gki_source_revision")
    if not is_hex40(revision):
        refuse("kernel-revision")
    activation = kernel.get("activation")
    if type(activation) is not dict or activation.get("mode") != "disabled" or \
            activation.get("source_lock_reproduction") != "not_verified":
        refuse("kernel-activation")
    return {"contract_bytes": contract_bytes, "gki_revision": revision}


def production_spec(environment: dict) -> dict:
    return {
        "files": BUNDLE_FILES,
        "directories": BUNDLE_DIRECTORIES,
        "qualification_sha256": QUALIFICATION_SHA256,
        "gki_revision": environment["gki_revision"],
        "project_count": PROJECT_COUNT,
        "link_count": LINK_COUNT,
        "patch_names": PATCH_NAMES,
        "profile": patch_profile(),
    }


def plan_document() -> dict:
    return {
        "kind": "myron-kernel-source-plan",
        "version": TOOL_VERSION,
        "schema": CONTRACT_SCHEMA,
        "input": {
            "root": "user-supplied absolute private path",
            "directories": list(BUNDLE_DIRECTORIES),
            "files": [{"path": path, "role": role} for path, role, *_ in BUNDLE_FILES],
        },
        "checks": [
            "root path canonical, no symlink component, safe ownership and ancestor modes",
            "bundle directories mode 0700, files mode 0600, one link, not executable",
            "exact closure, no extra entries, bounded enumeration",
            "descriptor-confined no-follow reads at pinned size plus one",
            "same mount inside the bundle, fail closed when unavailable",
            "SHA-256 and size of each file against the contract",
            "source lock, manifest and pinned patch order (patch bodies are not examined)",
            "metadata, name and membership rechecks after reading",
            "analyze-patches only, after all of the above: bounded structural analysis of the "
            "same captured patch buffers against the named profile; no patch is applied",
        ],
        "limitations": [
            "no atomic snapshot of the bundle",
            "no protection against a same-user or privileged writer",
            "a structural match is not applicability, source availability or build correctness",
        ],
        "authority": {name: False for name in AUTHORITY},
        "activation": {"mode": "disabled", "blocker": "unchanged"},
    }


def verification_document(summary: dict) -> dict:
    return {
        "kind": "myron-kernel-source-verification",
        "version": TOOL_VERSION,
        "schema": CONTRACT_SCHEMA,
        "result": "private-bundle-identity-matched",
        "scope": "identity-closure-lock-manifest-and-patch-order-only",
        "bundle": summary,
        "unverified": list(UNVERIFIED),
        "authority": {name: False for name in AUTHORITY},
        "activation": {"mode": "disabled", "blocker": "unchanged"},
    }


def emit(data: bytes) -> None:
    if len(data) > OUTPUT_MAX_BYTES:
        refuse("output-bound")
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()


def run(arguments: list) -> tuple:
    """(output bytes, exit status) for one invocation."""
    if arguments == ["show"]:
        return load_environment()["contract_bytes"], 0
    if arguments == ["plan"]:
        load_environment()
        return render_json(plan_document()), 0
    if len(arguments) == 3 and arguments[0] == "verify" and arguments[1] == "--root":
        budget = Budget()
        environment = load_environment(budget)
        summary = check_bundle(arguments[2], production_spec(environment), budget)
        return render_json(verification_document(summary)), 0
    if len(arguments) == 3 and arguments[0] == "analyze-patches" and arguments[1] == "--root":
        budget = Budget()
        environment = load_environment(budget)
        return analyze_command(arguments[2], production_spec(environment), budget)
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
        output, status = run(arguments)
        emit(output)
    except UsageError:
        sys.stderr.write(USAGE_FAILURE + "\n")
        return 2
    except BaseException:
        sys.stderr.write(FAILURE + "\n")
        return 1
    return status


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
