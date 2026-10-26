# SPDX-License-Identifier: MIT
# Run a real script as a /bin/sh process (not sourced into the test's bash).
# On the device and in this repository /bin/sh is bash in POSIX mode; running
# the script as a separate `sh` process checks what sourcing it cannot: the
# script's own `set -eu`, its top-level flow, subshell and pipeline behaviour,
# and its real command lookups against mocked tools on PATH.
# shellcheck shell=bash disable=SC2154

# sh_patch SRC DST name=value...: copy SRC with the listed top-level
# assignments replaced by absolute test paths or values.
sh_patch() {
  local src=$1 dst=$2 pair name value; shift 2
  cp "$src" "$dst"
  for pair in "$@"; do
    name=${pair%%=*} value=${pair#*=}
    grep -q "^$name=" "$dst" || { printf 'sh_patch: %s is not assigned in %s\n' "$name" "$src" >&2; return 1; }
    sed -i "s|^$name=.*|$name='$value'|" "$dst"
  done
}

# sh_scenario FILE LIB...: freeze the scenario variables the mock libraries
# (and extra names after --) read, so each mocked tool starts fast.
sh_scenario() {
  local file=$1 name names=; shift
  names=$(grep -ohE '[A-Za-z_][A-Za-z0-9_]*' "$@" 2>/dev/null | sort -u)
  : >"$file"
  for name in $names guard_log guard_rc; do
    [[ $name =~ ^(BASH.*|FUNCNAME|IFS|PIPESTATUS|RANDOM|EUID|UID|PPID)$ ]] && continue
    declare -p "$name" 2>/dev/null | grep -Ev '^declare -[a-zA-Z-]*r' >>"$file" || true
  done
}

# sh_mocks BINDIR SCENARIO LIB TOOL...: executables that load the scenario and
# the shared mock functions, then call the function named like the tool.
sh_mocks() {
  local bin=$1 scenario=$2 lib=$3 tool; shift 3
  mkdir -p "$bin"
  for tool in "$@"; do
    printf '#!/bin/bash\nset +eu\nsource %q\nsource %q\n%s "$@"\n' "$scenario" "$lib" "$tool" >"$bin/$tool"
    chmod +x "$bin/$tool"
  done
}
