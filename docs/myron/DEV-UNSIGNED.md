<!-- SPDX-License-Identifier: MIT -->
# Myron development-only unsigned package repository

**Not a release. No deployment authority.** This path exists so the Myron
package set can be resolved into a stage tree on a development machine that
has no Omarchy Mobile signing key. Everything it produces says so, and every
signed, release and phone-facing tool refuses it.

## What it is

| | Signed (default) | Development (`--dev-unsigned`) |
| --- | --- | --- |
| Repository | `out/repo/aarch64` | `out/dev-unsigned/repo/aarch64` (never `out/repo`) |
| Packages | signed, `*.sig` beside them | unsigned; any `*.sig` is refused, never deleted |
| Database | `repo-add --sign` | `repo-add` in a private signature-free workspace, validated, then published |
| Marker | none (refused if present) | `.omamobile-dev-unsigned` inside `aarch64`, exact bytes |
| Container trust of `[omamobile]` | `Required DatabaseOptional` | per-run stanza `SigLevel = Optional TrustedOnly` |
| Staged `etc/pacman.conf` | `Required DatabaseOptional` | the same committed file, `Required DatabaseOptional` |
| Stage name | `omamobile-rootfs-stage-<version>-aarch64` | `omamobile-rootfs-stage-dev-unsigned-<version>-aarch64` |
| MANIFEST line | `repository signatures: signed release` | `repository signatures: none (unsigned development build; not a release)` |

The marker holds exactly these three lines, each ending in a newline:

```
development-only: unsigned package repository
release-authority: false
deployment-authorized: false
```

It is created once, atomically, in an empty `aarch64`, and kept after a failed
build. Only a regular, non-symlink file with exactly these bytes counts: a
dangling or valid link, a directory, a FIFO or any other bytes are refused.
Package and database files must also be independent regular files: symlinks and
hardlinks are refused, preventing unsigned writes from aliasing signed bytes.

Only the flag `--dev-unsigned` selects the mode. `DEV_UNSIGNED`,
`ROOTFS_DEV_UNSIGNED` and similar variables in the environment do nothing.

## The command

One machine without `keys/fingerprint` and `keys/gnupg` (the tools refuse if
either exists, or is a link, even a dangling one). Build the twenty-four
packages the Myron stage needs, in this order, then stage:

```sh
tools/build-packages --dev-unsigned \
  packages/omamobile-keyring packages/qrtr packages/libqmi packages/modemmanager \
  packages/rmtfs packages/tqftpserv \
  packages/audioreach-kernel-headers packages/tinyalsa packages/audioreach-graphservices \
  packages/audioreach-conf packages/audioreach-graphmgr packages/fastrpc \
  packages/omamobile-firstboot packages/omamobile-omarchy \
  packages/strata packages/omamobile-apps-myron packages/omamobile-owl-widgets packages/omamobile-shell \
  packages/omamobile-mirror packages/omamobile-myron-kernel-contract packages/omamobile-device-myron \
  packages/mesa-myron-zink-turnip packages/omamobile-myron-gpu-profile packages/hyprland
env DEVICE=myron tools/build-rootfs --dev-unsigned --stage-only --version <version>
```

- `packages/hyprland` emits both `hyprland` and `hyprpm`.
- Standard `mesa` stays a dependency from the Arch Linux ARM and Omarchy
  repositories; it is not built here. `mesa-myron-zink-turnip` is the isolated
  Myron stack.
- Hyprland and the Myron Mesa are large builds (hours under emulation).
- Arch Linux ARM's tarball and keys, `[omarchy]`, upstream sources and the
  cached base image keep their normal verification. Only the `[omamobile]`
  stanza of the per-run container `pacman.conf` is relaxed.
- `--dev-unsigned` for the rootfs is `env DEVICE=myron ... --stage-only` only.

## Locks and the host

Every repository writer takes an exclusive `flock` on `.repo.lock` in the
directory above `aarch64` (outside it, so it is never in the repository). The
rootfs build holds the shared lock for the whole container run. A busy lock
fails at once instead of waiting.

The package containers need an enabled aarch64 binfmt handler. With the `F`
flag nothing else is needed. A handler without `F` works for package builds
only, by mounting its exact static interpreter read-only
(`--mount type=bind,src=…,dst=…,readonly`); the root file system build refuses
it, because pacstrap, package scriptlets and `arch-chroot` start processes
inside the target tree. Disabled, globally disabled and competing handlers are
refused. Nothing writes `binfmt_misc` or uses `sudo`.

## What stays refused

- `tools/build-packages`, `tools/build-rootfs` (default), `tools/repo-build`
  and `tools/repo-push` refuse a marker, of any type, in `out/repo/aarch64`,
  or an `out/repo` that resolves into `out/dev-unsigned`, before changing
  anything or contacting a phone.
- `tools/myron-deployment` refuses a stage whose MANIFEST has the unsigned
  line or whose tree holds the marker: a development stage never enters a
  deployment kit.
- `tests/rootfs-stage` checks that marker, manifest line, stage name and the
  final `pacman.conf` agree, that no `Optional`/`TrustAll` trust leaks into the
  stage, and that no qemu emulator, image, kernel, module or proprietary
  payload is present.

## What is tested, and what is not

`tests/dev-unsigned-repo`, `tests/dev-unsigned-rootfs`, `tests/alarm-binfmt`
and `tests/rootfs-stage` run offline with fake `docker`, `gpg` and `ssh`. They
prove the host-side contract above. They do **not** run pacman, makepkg,
pacstrap or a chroot, so they do not prove that the real containers accept the
unsigned `[omamobile]` repository or that the Myron stage resolves from it. That
needs one real run of the command above.
