#!/bin/bash
# SPDX-License-Identifier: MIT
# Sourced by rootfs/build-inside.  pacman queries by target name also match an
# installed provider, so closure policy must compare the exact package names
# from the complete installed-package listing instead. Virtual providers do
# not violate this exact-name policy.

check_myron_package_closure() { # ROOT
  local root=$1 output name package
  local -a required=(omamobile-apps-myron mesa-myron-zink-turnip omamobile-myron-gpu-profile)
  local -a forbidden=(omamobile-apps omacam neard libcamera libcamera-ipa pipewire-libcamera
                      gst-plugin-libcamera libfprint vulkan-panfrost)
  local -a absent=() present=()
  local -A installed=()

  output=$(pacman -r "$root" -Qq) || die "cannot list installed packages for the Myron closure"
  while IFS= read -r name; do
    [[ -n $name ]] && installed["$name"]=1
  done <<<"$output"

  for package in "${required[@]}"; do
    [[ ${installed[$package]+present} ]] || absent+=("$package")
  done
  ((${#absent[@]} == 0)) || die "Myron stage misses required packages: ${absent[*]}"
  for package in "${forbidden[@]}"; do
    [[ ${installed[$package]+present} ]] && present+=("$package")
  done
  ((${#present[@]} == 0)) || die "Myron stage resolved forbidden packages: ${present[*]}"
}
