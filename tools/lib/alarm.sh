# SPDX-License-Identifier: MIT
# Shared by tools/build-packages and tools/build-rootfs (sourced, not run):
# an Arch Linux ARM aarch64 container on this x86 laptop, through Docker and
# the laptop's aarch64 binfmt handler. Debian and Arch register it as
# qemu-aarch64 (qemu-user-static-binfmt). NixOS registers it as aarch64-linux.
# That node has to be enabled and carry the F (fix-binary) flag: without F
# its interpreter is a /run/binfmt wrapper that does not exist in the
# container. boot.binfmt.preferStaticEmulators turns the flag on. Package
# containers may use a handler without F when its static interpreter can be
# bind-mounted (alarm_require_binfmt below); the root file system build may not.
#
# The container starts from Arch Linux ARM's official root tarball, checked
# against its MD5 file and its detached signature from the Arch Linux ARM
# build key (fingerprint pinned below). Everything is cached under
# $ALARM_CACHE (default ~/.cache/omamobile-rootfs):
#   ArchLinuxARM-aarch64-latest.tar.gz{,.md5,.sig}   the tarball, verified
#   alarm-builder.asc                                the build key, as fetched
#   pkg/                                             pacman's package cache
#   src/                                             makepkg's source cache
# Docker images: omamobile-alarm-base:<tarball sha256> (the plain tarball)
# and omamobile-alarm-build:<hash> (keyrings, repositories, base-devel).

ALARM_URL=${ALARM_URL:-http://os.archlinuxarm.org/os/ArchLinuxARM-aarch64-latest.tar.gz}
# Arch Linux ARM Build System <builder@archlinuxarm.org>
ALARM_KEY=68B3537F39A313B3E574D06777193F152BDBE6A6
ALARM_KEYSERVER=${ALARM_KEYSERVER:-hkps://keyserver.ubuntu.com}
ALARM_CACHE=${ALARM_CACHE:-$HOME/.cache/omamobile-rootfs}
ALARM_TARBALL=$ALARM_CACHE/ArchLinuxARM-aarch64-latest.tar.gz
# Omarchy's aarch64 packages (omarchy, omarchy-settings, quickshell, its
# hyprland). Stable, the release the phone's Omarchy patches follow; edge
# carries release candidates (4.5.0rc1 on 2026-10-20) they may not apply to.
OMARCHY_CHANNEL=${OMARCHY_CHANNEL:-stable}
# The keyring that signs [omarchy], taken from this (Omarchy) laptop, which
# already trusts it: the container can't bootstrap that trust on its own.
OMARCHY_KEYRING_DIR=${OMARCHY_KEYRING_DIR:-/usr/share/pacman/keyrings}

alarm_say() { printf '\e[1m==> %s\e[0m\n' "$*"; }
alarm_die() { printf '\e[31merror:\e[0m %s\n' "$*" >&2; exit 1; }

# The aarch64 binfmt_misc handler, read from $ALARM_BINFMT_DIR (injectable so
# tests can use a fixture; default /proc/sys/fs/binfmt_misc). Nothing here
# writes binfmt_misc, creates a directory or uses sudo.
#   package (default)  an enabled handler with the F (fix-binary) flag works as
#                      is (Debian/Arch qemu-aarch64, NixOS aarch64-linux with
#                      preferStaticEmulators). Without F a package container
#                      may still run if the handler's exact absolute interpreter
#                      is a static, executable regular file: it is bind-mounted
#                      read-only at the same path (ALARM_DOCKER_QEMU_ARGS).
#   rootfs             F is required. pacstrap, package scriptlets and
#                      arch-chroot start processes inside the target tree,
#                      where no bind-mounted interpreter exists.
# Disabled, globally disabled and competing (several enabled) handlers fail.
ALARM_DOCKER_QEMU_ARGS=()
alarm_binfmt_matches_aarch64() { # MAGIC MASK OFFSET
  python3 -I - "$1" "$2" "$3" <<'PY'
import re
import sys

magic_text, mask_text, offset = sys.argv[1:]
if not re.fullmatch(r"(?:0|[1-9][0-9]*)", offset) or not re.fullmatch(r"[0-9A-Fa-f]+", magic_text or "") or len(magic_text) % 2:
    raise SystemExit(2)
if mask_text:
    if not re.fullmatch(r"[0-9A-Fa-f]+", mask_text) or len(mask_text) != len(magic_text):
        raise SystemExit(2)
else:
    mask_text = "ff" * (len(magic_text) // 2)
magic = bytes.fromhex(magic_text)
mask = bytes.fromhex(mask_text)
start = int(offset)
# Decide whether the handler's predicate intersects any valid ELF64
# little-endian AArch64 ET_EXEC or ET_DYN header. Bytes not fixed by the ELF
# ABI are variables, including OSABI and ABI version; a handler may constrain
# those (or later file bytes) and still compete with the normal qemu handler.
# Treating variable bytes as satisfiable is deliberately conservative: a
# possibly competing non-F handler must not escape the preflight.
common = {
    0: 0x7f, 1: ord("E"), 2: ord("L"), 3: ord("F"),
    4: 2,       # ELFCLASS64
    5: 1,       # ELFDATA2LSB
    6: 1,       # EV_CURRENT in e_ident
    **{position: 0 for position in range(9, 16)},  # EI_PAD
    18: 0xb7, 19: 0,                              # EM_AARCH64
    20: 1, 21: 0, 22: 0, 23: 0,                  # EV_CURRENT
    52: 64, 53: 0,                                # sizeof(Elf64_Ehdr)
}
for elf_type in (2, 3):
    fixed = dict(common)
    fixed[16], fixed[17] = elf_type, 0
    compatible = True
    for index, (wanted, selected) in enumerate(zip(magic, mask)):
        actual = fixed.get(start + index)
        if actual is not None and (actual & selected) != (wanted & selected):
            compatible = False
            break
    if compatible:
        print("match")
        raise SystemExit(0)
print("nonmatch")
PY
}
alarm_require_binfmt() { # [package|rootfs]
  local mode=${1:-package} dir=${ALARM_BINFMT_DIR:-/proc/sys/fs/binfmt_misc}
  local file name line first state interp flags magic mask offset extension match match_status
  local dotglob_on=0 nullglob_on=0 failglob_on=0 noglob_on=0 globignore_set=0 globignore_value=""
  local enabled=() disabled=() interps=() flagsof=()
  local files=()
  ALARM_DOCKER_QEMU_ARGS=()
  [[ $mode == package || $mode == rootfs ]] || alarm_die "bad binfmt mode $mode"
  [[ -d $dir ]] || alarm_die "no usable aarch64 binfmt handler: $dir is not mounted"
  if [[ -f $dir/status && $(<"$dir/status") != enabled ]]; then
    alarm_die "binfmt_misc is globally disabled ($dir/status): run it as enabled before building aarch64 containers"
  fi
  # binfmt_misc accepts handler names that begin with a dot. Snapshot exactly
  # one expansion with deterministic settings, then restore every caller
  # setting before inspecting it. Otherwise inherited dotglob can duplicate
  # hidden nodes, while failglob, noglob or GLOBIGNORE can omit nodes.
  shopt -q dotglob && dotglob_on=1
  shopt -q nullglob && nullglob_on=1
  shopt -q failglob && failglob_on=1
  [[ $- == *f* ]] && noglob_on=1
  if [[ ${GLOBIGNORE+x} ]]; then globignore_set=1; globignore_value=$GLOBIGNORE; fi
  set +f
  GLOBIGNORE=
  shopt -s dotglob nullglob
  shopt -u failglob
  files=("$dir"/*)
  if ((globignore_set)); then GLOBIGNORE=$globignore_value; else unset GLOBIGNORE; fi
  if ((dotglob_on)); then shopt -s dotglob; else shopt -u dotglob; fi
  if ((nullglob_on)); then shopt -s nullglob; else shopt -u nullglob; fi
  if ((failglob_on)); then shopt -s failglob; else shopt -u failglob; fi
  if ((noglob_on)); then set -f; else set +f; fi
  for file in "${files[@]}"; do
    name=${file##*/}
    [[ $name != status && $name != register && -f $file && ! -L $file ]] || continue
    first=1 state="" interp="" flags="" magic="" mask="" offset="" extension=""
    while IFS= read -r line || [[ -n $line ]]; do
      if ((first)); then state=$line first=0; continue; fi
      case $line in
        interpreter\ *) interp=${line#interpreter } ;;
        flags:*) flags=${line#flags:} flags=${flags// /} ;;
        magic\ *) magic=${line#magic } ;;
        mask\ *) mask=${line#mask } ;;
        offset\ *) offset=${line#offset } ;;
        extension\ *) extension=${line#extension } ;;
      esac
    done <"$file"
    # Extension registrations are selected by filename suffix, not ELF header,
    # so they cannot compete with an AArch64 magic registration. Ignore valid
    # extension nodes. A mixed extension/magic predicate is not a valid kernel
    # registration shape and must fail closed when it is enabled.
    if [[ -n $extension ]]; then
      if [[ -n $magic || -n $mask || -n $offset ]]; then
        if [[ $state == disabled ]]; then disabled+=("$name"); continue; fi
        alarm_die "binfmt handler $name mixes extension and magic predicates"
      fi
      continue
    fi
    # A disabled registration cannot intercept container execution. Skip it
    # before magic parsing.
    if [[ $state == disabled ]]; then
      disabled+=("$name")
      continue
    fi
    match_status=0
    match=$(alarm_binfmt_matches_aarch64 "$magic" "$mask" "$offset") || match_status=$?
    if ((match_status != 0)); then
      alarm_die "cannot evaluate whether binfmt handler $name matches aarch64 (matcher status $match_status)"
    fi
    case $match in
      match) ;;
      nonmatch) continue ;;
      *) alarm_die "cannot evaluate whether binfmt handler $name matches aarch64 (invalid matcher response)" ;;
    esac
    if [[ $state == enabled ]]; then
      enabled+=("$name"); interps+=("$interp"); flagsof+=("$flags")
    else
      disabled+=("$name")
    fi
  done
  if ((${#enabled[@]} == 0)); then
    if ((${#disabled[@]})); then
      alarm_die "the aarch64 binfmt handler is disabled (${disabled[*]}): enable it, or install qemu-user-static-binfmt, or enable boot.binfmt.emulatedSystems with boot.binfmt.preferStaticEmulators"
    fi
    alarm_die "no usable aarch64 binfmt handler: install qemu-user-static-binfmt, or enable boot.binfmt.emulatedSystems with boot.binfmt.preferStaticEmulators so aarch64-linux is enabled and its flags: line contains F"
  fi
  if ((${#enabled[@]} > 1)); then
    alarm_die "competing aarch64 binfmt handlers are enabled (${enabled[*]}): disable all but one"
  fi
  [[ ${flagsof[0]} == *F* ]] && return 0
  if [[ $mode == rootfs ]]; then
    alarm_die "the root file system build needs the aarch64 binfmt handler ${enabled[0]} with the F (fix-binary) flag: pacstrap, package scriptlets and arch-chroot run inside the target tree, where no interpreter can be mounted"
  fi
  interp=${interps[0]}
  [[ $interp =~ ^/[A-Za-z0-9._+/-]+$ && $interp != *..* && $interp != */ ]] ||
    alarm_die "the aarch64 binfmt handler ${enabled[0]} has no F flag and an interpreter path that cannot be mounted: '$interp'"
  [[ -f $interp && ! -L $interp && -x $interp ]] ||
    alarm_die "the aarch64 binfmt handler ${enabled[0]} has no F flag and its interpreter $interp is not an executable regular file"
  python3 -I - "$interp" <<'PY' ||
import struct
import sys

with open(sys.argv[1], "rb") as stream:
    header = stream.read(64)
    if len(header) < 64 or header[:4] != b"\x7fELF" or header[4] != 2 or header[5] != 1:
        raise SystemExit(1)
    if struct.unpack_from("<H", header, 18)[0] != 62:  # EM_X86_64 host executable
        raise SystemExit(1)
    phoff = struct.unpack_from("<Q", header, 32)[0]
    phentsize, phnum = struct.unpack_from("<HH", header, 54)
    if phentsize < 56 or not 0 < phnum <= 256:
        raise SystemExit(1)
    stream.seek(phoff)
    table = stream.read(phentsize * phnum)
    if len(table) != phentsize * phnum:
        raise SystemExit(1)
    types = [struct.unpack_from("<I", table, number * phentsize)[0] for number in range(phnum)]
if 3 in types or 1 not in types:  # PT_INTERP: dynamic; no PT_LOAD: not a program
    raise SystemExit(1)
PY
    alarm_die "the aarch64 binfmt handler ${enabled[0]} has no F flag and its interpreter $interp is not a static executable"
  ALARM_DOCKER_QEMU_ARGS=(--mount "type=bind,src=$interp,dst=$interp,readonly")
}

# Download (once) and verify the tarball. ALARM_REFRESH=1 fetches the newest.
alarm_fetch() { # [package|rootfs]: what the binfmt handler must support
  local gnupg status
  mkdir -p "$ALARM_CACHE/pkg" "$ALARM_CACHE/src"
  command -v docker >/dev/null || alarm_die "docker is needed"
  alarm_require_binfmt "${1:-package}"
  if [[ ! -f $ALARM_TARBALL || ${ALARM_REFRESH:-} == 1 ]]; then
    alarm_say "Downloading the Arch Linux ARM aarch64 root tarball"
    curl -fsSL -o "$ALARM_TARBALL.part" "$ALARM_URL"
    curl -fsSL -o "$ALARM_TARBALL.md5" "$ALARM_URL.md5"
    curl -fsSL -o "$ALARM_TARBALL.sig" "$ALARM_URL.sig"
    mv "$ALARM_TARBALL.part" "$ALARM_TARBALL"
  fi
  (cd "$ALARM_CACHE" && md5sum -c --quiet "${ALARM_TARBALL##*/}.md5") || alarm_die "MD5 mismatch for $ALARM_TARBALL"
  gnupg=$(mktemp -d)
  if [[ ! -s $ALARM_CACHE/alarm-builder.asc ]]; then
    GNUPGHOME=$gnupg gpg -q --batch --keyserver "$ALARM_KEYSERVER" --recv-keys "$ALARM_KEY" ||
      { rm -rf "$gnupg"; alarm_die "could not fetch the Arch Linux ARM build key $ALARM_KEY"; }
    GNUPGHOME=$gnupg gpg -q --batch --armor --export "$ALARM_KEY" >"$ALARM_CACHE/alarm-builder.asc"
  else
    GNUPGHOME=$gnupg gpg -q --batch --import "$ALARM_CACHE/alarm-builder.asc"
  fi
  # VALIDSIG carries the primary key's fingerprint last: it must be the pinned one
  status=$(GNUPGHOME=$gnupg gpg --batch --status-fd 1 --verify "$ALARM_TARBALL.sig" "$ALARM_TARBALL" 2>/dev/null || true)
  rm -rf "$gnupg"
  grep -Eq "^\[GNUPG:\] VALIDSIG .* $ALARM_KEY\$" <<<"$status" ||
    alarm_die "bad or missing signature on $ALARM_TARBALL (expected key $ALARM_KEY)"
}

# The plain tarball as a Docker image; prints its tag.
alarm_base_image() {
  local sum tag
  sum=$(sha256sum "$ALARM_TARBALL" | cut -c1-16)
  tag=omamobile-alarm-base:$sum
  if ! docker image inspect "$tag" >/dev/null 2>&1; then
    alarm_say "Importing the tarball as $tag" >&2
    docker import --platform linux/arm64 "$ALARM_TARBALL" "$tag" >/dev/null
  fi
  echo "$tag"
}

# The build image: the base plus initialised keyrings (Arch Linux ARM's,
# Omarchy's from this laptop, Omarchy Mobile's from packages/), the build
# pacman.conf, base-devel, arch-install-scripts and a "builder" user with
# this laptop's uid. Prints its tag. $1: the repository root.
alarm_build_image() {
  local root=$1 base tag hash ctx name
  base=$(alarm_base_image)
  for f in omarchy.gpg omarchy-trusted omarchy-revoked; do
    [[ -f $OMARCHY_KEYRING_DIR/$f ]] || alarm_die "no $OMARCHY_KEYRING_DIR/$f: this needs Omarchy's keyring (omarchy-keyring) on the build machine"
  done
  ctx=$(mktemp -d)
  cp "$OMARCHY_KEYRING_DIR"/omarchy{.gpg,-trusted,-revoked} "$ctx/"
  cp "$root"/packages/omamobile-keyring/omamobile{.gpg,-trusted,-revoked} "$ctx/"
  cp "$root/tools/lib/alarm-setup" "$ctx/setup"
  hash=$( (echo "$base $OMARCHY_CHANNEL $(id -u)"; cat "$ctx"/*) | sha256sum | cut -c1-16)
  tag=omamobile-alarm-build:$hash
  if ! docker image inspect "$tag" >/dev/null 2>&1; then
    alarm_say "Preparing the build image $tag (keyrings, base-devel)" >&2
    name=omamobile-alarm-setup-$$
    docker run --platform linux/arm64 "${ALARM_DOCKER_QEMU_ARGS[@]}" --name "$name" -v "$ctx:/setup:ro" -v "$ALARM_CACHE/pkg:/var/cache/pacman/pkg" \
      -e OMARCHY_CHANNEL="$OMARCHY_CHANNEL" -e BUILDER_UID="$(id -u)" -e BUILDER_GID="$(id -g)" \
      "$base" bash /setup/setup >&2 || { docker rm -f "$name" >/dev/null 2>&1; rm -rf "$ctx"; alarm_die "build image setup failed"; }
    docker commit "$name" "$tag" >/dev/null
    docker rm "$name" >/dev/null
  fi
  rm -rf "$ctx"
  echo "$tag"
}
