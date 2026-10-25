# SPDX-License-Identifier: MIT
# shellcheck shell=bash
# Shared by tools/build-packages, tools/build-rootfs, tools/repo-build and
# tools/repo-push (sourced, not run; the caller has cd'd to the repository
# root). The explicit, separate, development-only UNSIGNED package repository:
#
#   out/dev-unsigned/repo/aarch64      only `tools/build-packages --dev-unsigned`
#                                      writes it; only `tools/build-rootfs
#                                      --dev-unsigned` (Myron, --stage-only) reads it
#   out/repo/aarch64                   the signed repository; never holds unsigned
#                                      bytes, never holds the marker below
#
# The dev repository carries a marker file INSIDE aarch64 with exact bytes. The
# signed and release paths (build-packages, build-rootfs, repo-build, repo-push)
# refuse a marker or a repository that resolves into out/dev-unsigned before they
# change anything or contact a phone. Nothing reads an environment variable to
# choose the mode: --dev-unsigned is the only switch.

DEV_REPO_ROOT=out/dev-unsigned
DEV_REPO_DIR=$DEV_REPO_ROOT/repo/aarch64
SIGNED_REPO_DIR=out/repo/aarch64
DEV_REPO_MARKER_NAME=.omamobile-dev-unsigned
DEV_REPO_MARKER_TEXT=$'development-only: unsigned package repository\nrelease-authority: false\ndeployment-authorized: false\n'
DEV_REPO_SIGLEVEL='Optional TrustedOnly'
DEV_MANIFEST_LINE='repository signatures: none (unsigned development build; not a release)'
SIGNED_MANIFEST_LINE='repository signatures: signed release'

devrepo_die() {
  if declare -F alarm_die >/dev/null; then alarm_die "$*"; fi
  printf '\e[31merror:\e[0m %s\n' "$*" >&2
  exit 1
}

# The sed program that adds the per-run [omamobile] stanza before [omarchy] in a
# build container's pacman.conf. Signed (no argument): the global
# SigLevel = Required DatabaseOptional applies. dev: only this stanza relaxes to
# Optional TrustedOnly; the upstream repositories keep their verification.
devrepo_stanza_sed() { # [dev]
  local sig=''
  [[ ${1:-} != dev ]] || sig="SigLevel = $DEV_REPO_SIGLEVEL"'\n'
  printf '%s%s%s' '0,/^\[omarchy\]/s//[omamobile]\n' "$sig" \
    'Server = file:\/\/\/repo\/$arch\n\n[omarchy]/'
}

# Dev mode starts only on a machine without signing material. keys/ itself
# being a link counts, as does a dangling keys/fingerprint or keys/gnupg.
devrepo_refuse_signing_material() {
  local p
  for p in keys keys/fingerprint keys/gnupg; do
    if [[ $p == keys ]]; then
      [[ ! -L $p && ( ! -e $p || -d $p ) ]] && continue
    fi
    if [[ -e $p || -L $p ]]; then
      devrepo_die "--dev-unsigned refuses to run where signing material exists ($p): use the signed tools, or move the maintainer's keys/ away"
    fi
  done
}

# marker_state DIR: prints absent|exact. Anything else (a symlink, dangling
# or not, a directory, a FIFO, other bytes) is an error with a message.
devrepo_marker_state() { # DIR
  python3 -I - "$1/$DEV_REPO_MARKER_NAME" "$DEV_REPO_MARKER_TEXT" <<'PY'
import os
import stat
import sys

path, expected = sys.argv[1], sys.argv[2].encode()
try:
    before = os.lstat(path)
except FileNotFoundError:
    print("absent")
    raise SystemExit(0)
except OSError as error:
    raise SystemExit(f"development marker {path}: {error.strerror}")
if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
    raise SystemExit(f"development marker is not a regular file: {path}")
try:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
except OSError as error:
    raise SystemExit(f"development marker {path}: {error.strerror}")
try:
    opened = os.fstat(descriptor)
    if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1 or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
        raise SystemExit(f"development marker changed while being read: {path}")
    data = os.read(descriptor, 4096)
finally:
    os.close(descriptor)
if data != expected:
    raise SystemExit(f"development marker does not hold the exact bytes: {path}")
print("exact")
PY
}

# Signed and release paths: no marker of any type beside the packages, the
# repository must not resolve into the dev tree (a symlinked out/repo), and
# signed artifacts must be independent regular files. Package links are never
# valid: in particular, a link into the development repository would let a dev
# rebuild change the bytes observed beside an old signature.
devrepo_reject_signed_repo() { # AARCH64_DIR
  local dir=$1 real dev component
  if [[ -e $dir/$DEV_REPO_MARKER_NAME || -L $dir/$DEV_REPO_MARKER_NAME ]]; then
    devrepo_die "$dir holds the development-only unsigned repository marker: signed and release paths refuse it (use tools/build-packages --dev-unsigned for the development repository)"
  fi
  real=$(realpath -m -- "$dir") || devrepo_die "cannot resolve $dir"
  dev=$(realpath -m -- "$DEV_REPO_ROOT")
  if [[ $real == "$dev" || $real == "$dev"/* ]]; then
    devrepo_die "$dir resolves into the development-only repository $DEV_REPO_ROOT: signed and release paths refuse it"
  fi
  for component in out out/repo "$dir"; do
    if [[ -L $component || ( -e $component && ! -d $component ) ]]; then
      devrepo_die "$component is not a real signed-repository directory (links are refused)"
    fi
  done
  [[ ! -d $dir ]] || python3 -I - "$dir" "$DEV_REPO_MARKER_NAME" <<'PY'
import os
import stat
import sys

root, marker = sys.argv[1:]
database_links = {
    "omamobile.db": "omamobile.db.tar.gz",
    "omamobile.db.sig": "omamobile.db.tar.gz.sig",
    "omamobile.files": "omamobile.files.tar.gz",
    "omamobile.files.sig": "omamobile.files.tar.gz.sig",
}
database_files = {
    "omamobile.db", "omamobile.db.tar.gz", "omamobile.db.tar.gz.sig",
    "omamobile.files", "omamobile.files.tar.gz", "omamobile.files.tar.gz.sig",
    "omamobile.db.tar.gz.old", "omamobile.db.tar.gz.old.sig",
    "omamobile.files.tar.gz.old", "omamobile.files.tar.gz.old.sig",
}
try:
    entries = list(os.scandir(root))
except OSError as error:
    raise SystemExit(f"cannot inspect signed repository: {error.strerror}")
for entry in entries:
    name = entry.name
    if name == marker:
        continue  # The shell-side check above supplies the specific error.
    try:
        metadata = entry.stat(follow_symlinks=False)
    except OSError as error:
        raise SystemExit(f"cannot inspect signed repository entry {name}: {error.strerror}")
    if stat.S_ISLNK(metadata.st_mode):
        if name not in database_links:
            raise SystemExit(f"signed repository artifact is a link: {name}")
        try:
            target = os.readlink(entry.path)
        except OSError as error:
            raise SystemExit(f"cannot read signed repository database link {name}: {error.strerror}")
        if target != database_links[name]:
            raise SystemExit(f"signed repository database link has the wrong target: {name}")
        continue
    is_package = name.endswith((".pkg.tar.zst", ".pkg.tar.xz"))
    is_package_signature = name.endswith((".pkg.tar.zst.sig", ".pkg.tar.xz.sig"))
    if name not in database_files and not is_package and not is_package_signature:
        raise SystemExit(f"unexpected signed repository entry: {name}")
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise SystemExit(f"signed repository artifact is not an independent regular file: {name}")
PY
}

# Every component of out/dev-unsigned/repo/aarch64 must be a real directory
# (never a link). `create` makes the missing ones; `check` insists they exist.
devrepo_dirs() { # create|check
  python3 -I - "$1" out out/dev-unsigned out/dev-unsigned/repo out/dev-unsigned/repo/aarch64 <<'PY'
import os
import stat
import sys

mode, paths = sys.argv[1], sys.argv[2:]
for path in paths:
    try:
        metadata = os.lstat(path)
    except FileNotFoundError:
        if mode != "create":
            raise SystemExit(f"no development repository directory: {path}")
        try:
            os.mkdir(path, 0o755)
        except OSError as error:
            raise SystemExit(f"cannot create {path}: {error.strerror}")
        continue
    except OSError as error:
        raise SystemExit(f"{path}: {error.strerror}")
    if not stat.S_ISDIR(metadata.st_mode):
        raise SystemExit(f"{path} is not a real directory (links are refused)")
PY
}

# An exclusive (writers) or shared (the rootfs reader) lock on a file OUTSIDE
# aarch64. Fails at once instead of waiting behind a multi-hour build.
devrepo_lock() { # VARNAME LOCKFILE ex|sh
  local var=$1 file=$2 kind=$3 fd flag opened wanted opened_id path_id links
  case $kind in ex) flag=-x ;; sh) flag=-s ;; *) devrepo_die "bad lock kind $kind" ;; esac
  if [[ -L $file || ( -e $file && ! -f $file ) ]]; then
    devrepo_die "$file is not a regular lock file"
  fi
  exec {fd}>>"$file" || devrepo_die "cannot open the repository lock $file"
  opened=$(readlink -f -- "/proc/$$/fd/$fd") || devrepo_die "cannot resolve the opened repository lock $file"
  wanted=$(realpath -m -- "$file") || devrepo_die "cannot resolve the repository lock $file"
  opened_id=$(stat -Lc '%d:%i' "/proc/$$/fd/$fd") || devrepo_die "cannot inspect the opened repository lock $file"
  path_id=$(stat -Lc '%d:%i' "$file") || devrepo_die "cannot inspect the repository lock $file"
  links=$(stat -Lc '%h' "/proc/$$/fd/$fd") || devrepo_die "cannot inspect the repository lock $file"
  [[ ! -L $file && $opened == "$wanted" && $opened_id == "$path_id" && $links == 1 ]] ||
    devrepo_die "$file changed while the repository lock was opened"
  if ! flock -n "$flag" "$fd" 2>/dev/null; then
    devrepo_die "another repository writer or rootfs build holds $file: wait for it to finish"
  fi
  printf -v "$var" '%s' "$fd"
}

# No *.sig of any kind, dangling links and directories included.
devrepo_scan_signatures() { # DIR
  local hit
  hit=$(find "$1" -name '*.sig' -print -quit) || devrepo_die "cannot scan $1 for signatures"
  [[ -z $hit ]] || devrepo_die "$1 holds a signature file ($hit): a development repository is signature-free and never deletes signatures"
}

# Every mutable repository file must have its own inode. Without this check a
# package hardlinked to out/repo could be overwritten while its old signature
# stayed beside it. Database links are the only links allowed, and they must be
# the exact repo-add names and targets.
devrepo_validate_contents() { # AARCH64_DIR
  local dir=$1 state
  state=$(devrepo_marker_state "$dir" 2>&1) || devrepo_die "$state"
  [[ $state == exact ]] || devrepo_die "$dir lacks the development marker"
  python3 -I - "$dir" "$DEV_REPO_MARKER_NAME" <<'PY'
import os
import stat
import sys

root, marker = sys.argv[1:]
database_files = {"omamobile.db.tar.gz", "omamobile.files.tar.gz"}
database_links = {
    "omamobile.db": "omamobile.db.tar.gz",
    "omamobile.files": "omamobile.files.tar.gz",
}
seen_database = set()
try:
    entries = list(os.scandir(root))
except OSError as error:
    raise SystemExit(f"cannot inspect development repository: {error.strerror}")
for entry in entries:
    name = entry.name
    try:
        metadata = entry.stat(follow_symlinks=False)
    except OSError as error:
        raise SystemExit(f"cannot inspect development repository entry {name}: {error.strerror}")
    if name == marker:
        continue
    if name in database_links:
        if not stat.S_ISLNK(metadata.st_mode):
            raise SystemExit(f"development repository database link is not a link: {name}")
        try:
            target = os.readlink(entry.path)
        except OSError as error:
            raise SystemExit(f"cannot read development repository database link {name}: {error.strerror}")
        if target != database_links[name]:
            raise SystemExit(f"development repository database link has the wrong target: {name}")
        seen_database.add(name)
        continue
    is_package = name.endswith((".pkg.tar.zst", ".pkg.tar.xz"))
    if name in database_files or is_package:
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise SystemExit(f"development repository file is not an independent regular file: {name}")
        if name in database_files:
            seen_database.add(name)
        continue
    raise SystemExit(f"unexpected development repository entry: {name}")
if seen_database and seen_database != database_files | set(database_links):
    raise SystemExit("development repository database set is incomplete")
PY
}

# Writers: under the lock, the aarch64 directory is either already marked
# exactly, or new and empty and gets the marker atomically (a hard link fails
# when the name exists, so nothing is replaced). The marker is never removed.
devrepo_ensure_marker() { # AARCH64_DIR
  local dir=$1 state tmp
  state=$(devrepo_marker_state "$dir" 2>&1) || devrepo_die "$state"
  [[ $state == exact ]] && return 0
  if [[ -n $(find "$dir" -mindepth 1 -print -quit) ]]; then
    devrepo_die "$dir has content but no development marker: refusing to adopt it"
  fi
  tmp=$(mktemp -- "$dir/../.marker.XXXXXXXX") || devrepo_die "cannot stage the development marker"
  printf '%s' "$DEV_REPO_MARKER_TEXT" >"$tmp"
  chmod 644 "$tmp"
  if ! ln -T -- "$tmp" "$dir/$DEV_REPO_MARKER_NAME"; then
    rm -f -- "$tmp"
    devrepo_die "cannot create the development marker in $dir"
  fi
  rm -f -- "$tmp"
  state=$(devrepo_marker_state "$dir" 2>&1) || devrepo_die "$state"
  [[ $state == exact ]] || devrepo_die "the development marker was not created exactly"
}

# Readers (the dev rootfs): the marker is exact, there is a database, no signature.
devrepo_require_dev_repo() { # AARCH64_DIR
  local dir=$1 state
  state=$(devrepo_dirs check 2>&1) || devrepo_die "$state"
  state=$(devrepo_marker_state "$dir" 2>&1) || devrepo_die "$state"
  [[ $state == exact ]] || devrepo_die "$dir lacks the development marker: build it with tools/build-packages --dev-unsigned"
  devrepo_scan_signatures "$dir"
  devrepo_validate_contents "$dir"
  [[ -f $dir/omamobile.db ]] || devrepo_die "no [omamobile] database in $dir: build it with tools/build-packages --dev-unsigned"
}

# Publish a freshly indexed, signature-free database from a private workspace.
devrepo_publish_index() { # WORKDIR AARCH64_DIR PACKAGE_COUNT
  local work=$1 repo=$2 count=$3 names f descriptions
  names=$(cd "$work" && ls -A | LC_ALL=C sort | tr '\n' ' ')
  [[ $names == *omamobile.db* ]] || devrepo_die "repo-add produced no database"
  for f in omamobile.db.tar.gz omamobile.files.tar.gz; do
    [[ -f $work/$f && ! -L $work/$f ]] || devrepo_die "repo-add produced no $f"
  done
  for f in omamobile.db omamobile.files; do
    [[ -L $work/$f && $(readlink -- "$work/$f") == "$f.tar.gz" ]] || devrepo_die "repo-add produced an unexpected $f"
  done
  for f in $names; do
    case $f in
      omamobile.db|omamobile.db.tar.gz|omamobile.files|omamobile.files.tar.gz) ;;
      *) devrepo_die "the index workspace holds an unexpected entry: $f" ;;
    esac
  done
  devrepo_scan_signatures "$work"
  [[ $(bsdtar -tf "$work/omamobile.db.tar.gz" | grep -c '/desc$') == "$count" ]] ||
    devrepo_die "the database does not list exactly $count packages"
  descriptions=$(mktemp -- "$work/.descriptions.XXXXXXXX") || devrepo_die "cannot stage the database signature scan"
  if ! bsdtar -xOf "$work/omamobile.db.tar.gz" --include='*/desc' >"$descriptions"; then
    rm -f -- "$descriptions"
    devrepo_die "cannot extract the database descriptions"
  fi
  # Do not use grep -q on the bsdtar pipe: an early match closes the pipe,
  # bsdtar reports EPIPE, and pipefail would turn the true match into false.
  if grep -Fx '%PGPSIG%' "$descriptions" >/dev/null; then
    rm -f -- "$descriptions"
    devrepo_die "the database carries a package signature"
  fi
  rm -f -- "$descriptions"
  mv -f -- "$work/omamobile.db.tar.gz" "$repo/omamobile.db.tar.gz"
  mv -f -- "$work/omamobile.files.tar.gz" "$repo/omamobile.files.tar.gz"
  mv -fT -- "$work/omamobile.db" "$repo/omamobile.db"
  mv -fT -- "$work/omamobile.files" "$repo/omamobile.files"
}

# The identity of one package, read the way repo-add reads it (db_write_entry:
# `read -r line` strips surrounding blanks, `#` lines are skipped, then
# IFS=' =' splits var from value). pkgname, pkgver and arch must each appear
# exactly once and in the canonical `key = value` form, so no alternate spacing
# ("  pkgname = x", "pkgver 9-1", "arch=any") can override the validated value
# when repo-add indexes the package. pgpsig in any form is refused too.
# Prints "name<TAB>version<TAB>arch" or fails with a message.
devrepo_pkginfo_identity() { # PACKAGE_FILE
  python3 -I - "$1" <<'PY'
import re
import subprocess
import sys

package = sys.argv[1]
base = package.rsplit("/", 1)[-1]
patterns = {
    "pkgname": re.compile(r"[a-z0-9@._+:-]+"),
    "pkgver": re.compile(r"[A-Za-z0-9._+~:-]+"),
    "arch": re.compile(r"aarch64|any"),
}
label = {"pkgname": "pkgname", "pkgver": "pkgver", "arch": "arch (aarch64 or any)"}
allowed = {
    "pkgname", "pkgbase", "xdata", "pkgver", "pkgdesc", "url",
    "builddate", "packager", "size", "arch", "license", "replaces",
    "group", "conflict", "provides", "backup", "depend", "optdepend",
    "makedepend", "checkdepend",
}
result = subprocess.run(["bsdtar", "-xOqf", package, ".PKGINFO"], capture_output=True)
if result.returncode != 0:
    raise SystemExit(f"cannot read .PKGINFO from {base}")
try:
    text = result.stdout.decode("utf-8")
except UnicodeDecodeError:
    raise SystemExit(f"{base} has a .PKGINFO that is not UTF-8")
if "\0" in text:
    raise SystemExit(f"{base} has a NUL byte in .PKGINFO")
found = {key: [] for key in patterns}
for line in text.split("\n"):
    stripped = line.strip(" \t")
    if not stripped or stripped.startswith("#"):
        continue
    token = re.match(r"[^ =]*", stripped).group(0)
    if token == "pgpsig":
        raise SystemExit(f"{base} carries embedded pgpsig metadata: the development repository is signature-free")
    canonical = re.fullmatch(r"([a-z][a-z0-9]*) = (.*)", line)
    if not canonical or canonical.group(1) not in allowed:
        raise SystemExit(f"{base} has an unsupported or noncanonical .PKGINFO line: {line!r}")
    key, value = canonical.groups()
    if key in found:
        if not patterns[key].fullmatch(value):
            raise SystemExit(f"{base} has no single canonical {label[key]}: noncanonical line {line!r}")
        found[key].append(value)
for key, values in found.items():
    if len(values) != 1:
        raise SystemExit(f"{base} has no single canonical {label[key]}")
print("\t".join(found[key][0] for key in ("pkgname", "pkgver", "arch")))
PY
}

# The prepared generation's database must describe exactly the staged, already
# validated packages: for every EXPECTED line (filename, name, version, arch,
# tab separated) one entry with the same FILENAME, NAME, VERSION and ARCH, no
# other entry, and no other package file in the directory.
devrepo_verify_database() { # GENERATION_DIR EXPECTED_FILE
  python3 -I - "$1" "$2" <<'PY'
import os
import sys
import tarfile

root, expected_file = sys.argv[1:]
expected = {}
with open(expected_file, encoding="utf-8") as handle:
    for line in handle.read().splitlines():
        filename, name, version, arch = line.split("\t")
        expected[filename] = (name, version, arch)

def entries(archive):
    found = {}
    with tarfile.open(os.path.join(root, archive), "r:gz") as tar:
        for member in tar:
            parts = member.name.rstrip("/").split("/")
            if len(parts) == 1 and member.isdir():
                found.setdefault(parts[0], {})
            elif len(parts) == 2 and parts[1] == "desc":
                if not member.isreg() or member.size > 1 << 20:
                    raise SystemExit(f"{archive}: unusable entry {member.name}")
                found.setdefault(parts[0], {})["desc"] = tar.extractfile(member).read().decode("utf-8")
            elif not member.isdir() and not (len(parts) == 2 and parts[1] == "files"):
                raise SystemExit(f"{archive}: unexpected entry {member.name}")
    return found

def fields(desc):
    result, key = {}, None
    for line in desc.split("\n"):
        if line.startswith("%") and line.endswith("%") and len(line) > 2:
            key = line[1:-1]
            result.setdefault(key, [])
        elif line and key:
            result[key].append(line)
    return result

database = entries("omamobile.db.tar.gz")
if set(entries("omamobile.files.tar.gz")) != set(database):
    raise SystemExit("the files database lists other packages than the database")
seen = {}
for directory, parts in database.items():
    if "desc" not in parts:
        raise SystemExit(f"database entry {directory} has no desc")
    desc = fields(parts["desc"])
    values = {}
    for key in ("FILENAME", "NAME", "VERSION", "ARCH"):
        if len(desc.get(key, [])) != 1:
            raise SystemExit(f"database entry {directory} has no single {key}")
        values[key] = desc[key][0]
    if directory != f"{values['NAME']}-{values['VERSION']}":
        raise SystemExit(f"database entry {directory} does not match its NAME and VERSION")
    if values["FILENAME"] in seen:
        raise SystemExit(f"database lists {values['FILENAME']} twice")
    seen[values["FILENAME"]] = (values["NAME"], values["VERSION"], values["ARCH"])
if seen != expected:
    raise SystemExit("the database identity, version, architecture or filenames differ from the staged packages")
actual = {name for name in os.listdir(root) if name.endswith((".pkg.tar.zst", ".pkg.tar.xz"))}
if actual != set(expected):
    raise SystemExit("the generation's package files differ from the staged packages")
PY
}

# Atomically swap two directories (renameat2 RENAME_EXCHANGE): every reader sees
# the old generation or the new one, never a mixture. Linux only; fails closed
# when the kernel or filesystem cannot exchange. Both must be real directories
# of one filesystem in one parent.
devrepo_exchange_generation() { # NEW_DIR LIVE_DIR
  python3 -I - exchange-generation "$1" "$2" <<'PY'
import ctypes
import os
import stat
import sys

new, live = sys.argv[2:]
metadata = []
for path in (new, live):
    try:
        metadata.append(os.lstat(path))
    except OSError as error:
        raise SystemExit(f"cannot inspect {path}: {error.strerror}")
    if not stat.S_ISDIR(metadata[-1].st_mode):
        raise SystemExit(f"{path} is not a real directory (links are refused)")
if metadata[0].st_dev != metadata[1].st_dev or os.path.dirname(new) != os.path.dirname(live):
    raise SystemExit("the new generation is not beside the live one on the same filesystem")
libc = ctypes.CDLL(None, use_errno=True)
if not hasattr(libc, "renameat2"):
    raise SystemExit("atomic directory exchange (renameat2) is unavailable: refusing a non-atomic publish")
AT_FDCWD, RENAME_EXCHANGE = -100, 2
if libc.renameat2(AT_FDCWD, os.fsencode(new), AT_FDCWD, os.fsencode(live), RENAME_EXCHANGE) != 0:
    error = ctypes.get_errno()
    raise SystemExit(f"atomic directory exchange failed ({os.strerror(error)}): the live repository is unchanged")
PY
}
