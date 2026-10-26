#!/bin/sh
# SPDX-License-Identifier: MIT
set -eu

die() {
	printf 'ERROR: %s\n' "$*" >&2
	exit 1
}

[ -r /sys/kernel/notes ] || die '/sys/kernel/notes is unreadable'
actual=$(sha256sum /sys/kernel/notes | awk '{print $1}')
case "$actual" in
	33ea3a20a11012793d178913699e3ab1728450ae8834c8171bd7a524204566d1)
	directory="/usr/local/lib/myron-gki-modules/$(uname -r)" ;;
	7ba981b730e49e1866ebf4967e9cadb0c3a0aa90c5c0bb4b0f9804b628e6f248|\
	a695a96006f5faa845676799ef5bc1cd348b65d1ca30c69931e50c38bd51b00d|\
	82e8f063b306d6f8136fbf5d05f39fd10755a3f3a22a36bf2661234e866e2b41|\
	816d7b757498dc0858c3798bf27171a0efa99e821044538653a12734dbbca119|\
	9ea04dd9f04704b2da7c0525930d53b51e3e5a99bccf78219bc202ec3dc869f8|\
	8ba2b05e346c638d699e16d4b782378e394bba374a12b16abacc1b905cb8d608|\
	dadfc0372f028cd5c9810415167af6c182e79fbf2954e7c555a8a1108cf33e1e|\
	0ecd0f4eb2f6ab7c073ef2f2afd94e4185ac404b2b01a04a666188d63f029db8)
		directory="/usr/local/lib/myron-gki-module-sets/$actual"
		;;
	*) die "unknown kernel notes hash: $actual" ;;
esac
[ -d "$directory" ] || die "selected GKI module directory is missing: $directory"
printf '%s\n' "$directory"
