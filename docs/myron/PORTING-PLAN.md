<!-- SPDX-License-Identifier: MIT -->
# Myron Omarchy Mobile porting plan

Status (2026-10-24): phase 0 audit, phase 1 inert skeleton, and the metadata-only
part of phase 2 are implemented. No Arch image has booted and no live phone
state was changed.

## Goal

Run Arch Linux ARM, Hyprland, and Omarchy Mobile on Xiaomi myron while
preserving every working downstream-kernel hardware path. Initial work reuses
the exact Android 16 GKI family, vendor modules, firmware contracts, and
Attempt105 behavior. Mainline replacement is out of scope.

## Evidence summary

- [V] Native Hyprland works on DSI-1 with touch and Adreno 840 acceleration on
  the existing postmarketOS system.
- [V] Wi-Fi, LTE/5G data, GNSS, charging, display, touch, torch, browser video,
  and the isolated GPU path have working reference evidence.
- [V] The current Omarchy installer is Pixel-shaped: it writes slot B boot
  images and `userdata`.
- [V] Reference documentation places Myron Linux on slot A and Android/recovery
  on slot B; the live kernel does not expose a useful slot suffix.
- [V] Attempt105 libraries are linked to musl and must be rebuilt for Arch.
- [I] A rootfs can reuse the boot-proven Image/module set without changing the
  boot chain, once a reversible temporary-root mechanism is designed.
- [I] Most systemd units can be translated from the reference module manifests,
  but package paths and Alpine dependencies need per-subsystem review.

## Phase 0: baseline audit

Completed in this repository:

- [BASELINE.md](BASELINE.md)
- [HARDWARE-MATRIX.md](HARDWARE-MATRIX.md)
- [KERNEL-INVENTORY.md](KERNEL-INVENTORY.md)
- [FIRMWARE-INVENTORY.md](FIRMWARE-INVENTORY.md)
- [GPU-STACK.md](GPU-STACK.md)

Remaining audit gates:

1. capture non-identifying boot-image headers, DTB/DTBO selection, partition
   names/sizes, and current-slot state through an approved read-only recovery
   session;
2. reconcile Attempt105 r0/r1 hashes and check in the exact source patch;
3. export a license/provenance decision for every vendor-asset class;
4. diagnose the lock-screen PAM hang separately from compositor stability;
5. record safe probes for DP, haptics, sensor presence, and USB audio.

## Phase 1: device skeleton

Implemented:

- `device/myron/device.conf` with verified identity and a fail-closed
  `external-android` boot method;
- `packages/omamobile-device-myron`, which stages metadata only;
- offline tests proving Myron rootfs/image/flash/push/install commands stop
  before container or phone access;
- package tests proving no service, boot file, firmware, module, binary, or
  hardware activation path is staged;
- device listing and descriptor documentation.

The package itself can be built and inspected. `tools/build-rootfs` refuses the
target until a compatible external-kernel/module input is implemented, so it
cannot silently assemble a Myron image with Pixel/Panfrost inputs.

## Phase 2: kernel and module reuse

Build an `omamobile-myron-kernel-contract` package containing metadata and
verification tools, not an Image or automatic hook. It must verify exact
kernel release, notes hash, GKI ABI, matched module manifest, and required
firmware before any service starts.

Translate reference modules in dependency order:

1. boot contract and device nodes;
2. access/USB rescue and time;
3. network and desktop/input;
4. graphics;
5. cellular/GNSS, audio, power, Bluetooth, and applications.

Each translated module gets an Arch package or device-package subcomponent,
an offline rootfs test, a read-only live probe, and a rollback record. No
module is selected by `uname -r` alone.

Implemented in the metadata-only contract package:

- exact qualified VT Image, notes, configuration, and both symbol-table hashes;
- exact seven-module asset archive, member allowlist, internal manifest, release
  marker, selector, and `rmnet_core` conflict checks;
- exact private runtime-asset manifest identity and per-feature read-only hash
  verification;
- explicit `activation.mode=disabled` while source-lock reproduction remains
  unverified;
- no Image, module, firmware, vendor binary, service, hook, or writer payload.

- (0.2.0) a separate, metadata-only stage contract plus read-only `show-stage`,
  `plan-stage` and `verify-stage`: exact destinations, modes and hashes for the
  eight target files of an external module stage (selector at
  `/usr/local/sbin/myron-attempt79-module-dir`, seven modules directly in the
  notes-keyed directory; archive metadata is validated, not staged), forbidden boot, firmware, vendor, `/usr/lib/modules`
  and activation paths, and no writes or external commands. This is not full
  ABI, import, provider or load-order proof, and there is still no stage
  writer, extraction, `depmod`, module install, boot work, or hardware or
  deployment authorization.

- (0.3.0, Phase 2.6) read-only `verify-abi`: a staged-set-only, offline,
  pure-Python ABI/import/provider/CRC/load-order verifier that validates the
  qualified archive and both symvers files by SHA-256 before parsing, with
  `scope: staged-set-only`, `vendor_modules: not-verified` and
  `activation: disabled` in its JSON. Its ELF reader supports a synthetic
  layout only and is unqualified on real modules. The blocker remains until
  the real qualified archive, exact symvers and the full vendor module
  inventory are checked.

- (0.4.0, Phase 2.11) the verifier accepts structurally validated ELF64
  RELA sections and refuses allocated REL targets, plus legacy 8-byte,
  AArch64 PREL32 12-byte, and non-PREL32
  ELF64 24-byte export layouts, classic and section-backed CRCs, basic and
  extended modversions, runtime export namespaces, and `module_layout`.
  Coverage remains synthetic and explicitly unqualified on real modules; no
  blocker or authority state changes.

Phase 2.5 (laptop-only, done): `device/myron/deployment-contract.json` and
`tools/myron-deployment` stage the module overlay writer-side and assemble a
deterministic deployment-candidate kit bound to the rootfs stage, kernel
contract, GPU profile and runtime-manifest identity. Its gate always refuses
deployment with seven permanent blockers; the kit is not bootable, flashable,
image-ready, an atomic-snapshot proof, hardware-qualified or an authorization
([DEPLOYMENT-GATE.md](DEPLOYMENT-GATE.md)). It runs no `depmod` and no external
command, and nothing has been built from the real archive.

Phase 2.7 (laptop-only, mechanism done): `tools/myron-deployment` 0.2.0 records
`runtime_assets` evidence in the kit, either explicitly `not-bound` or a
hash-only `verified` closure of the required stock-extracted `gpu`, `wifi` and
`touch` files, derived from one hardened tree walk against the pinned manifest.
It is not provisioning, extraction, redistribution, ABI or hardware
qualification, copies no private bytes or manifest, and no real runtime tree has
been bound. `private-runtime-asset-bytes-not-bound-to-kit` and the other six
blockers are unchanged until a real, separately reviewed bound kit and contract
revision ([DEPLOYMENT-GATE.md](DEPLOYMENT-GATE.md)).

Phase 2.8 (laptop-only, mechanism done): `tools/myron-deployment` 0.3.0 binds
the existing staged-set ABI verifier into `kit.json`, either explicitly
`not-bound` or recomputed from the same exact archive bytes plus both exact
symvers files. Only a fixed summary and report/evidence hashes enter the kit;
symvers bytes and full symbol tables stay external. This does not qualify the
synthetic-only parser, cover vendor modules, verify live load semantics or
clear `module-abi-import-and-load-order-not-verified`. Activation, the
unverified overlay order, all seven blockers and gate refusal remain unchanged
([DEPLOYMENT-GATE.md](DEPLOYMENT-GATE.md)).

Phase 2.9 (laptop-only, mechanism done): `device/myron/snapshot-contract.json`
and `tools/myron-snapshot` 0.2.0 bind a fully re-verified deployment kit to its
pre-deployment rootfs digest in a deterministic, metadata-only snapshot
candidate. A read-only rollback rehearsal accepts only the same version-1 tree
digest while still reporting `atomicity_proven: false` and
`rollback_proven: false`. Version 0.2.0 permits only `not-captured`,
`not-proven` quiescence and `not-proven` rollback states; it performs no
capture or restore, clears no blocker and authorizes nothing
([SNAPSHOT-GATE.md](SNAPSHOT-GATE.md)).

Phase 2.10 (laptop-only, mechanism done):
`device/myron/preflight-contract.json` and `tools/myron-preflight` 0.2.1 bind a
re-verified kit and snapshot into a refusal-only hardware-read approval
request. The request maps all seven open blockers to their real evidence
producer and declares seven bounded, redacted future read operations, but its
execution and collected-evidence lists are empty and every authority flag is
false. It contacts no phone and is not approval
([PREFLIGHT-GATE.md](PREFLIGHT-GATE.md)).

Phase 2.12 (laptop-only, mechanism done): `device/myron/capture-contract.json`
and `tools/myron-collect` 0.1.0 validate a bounded **pre-captured fixture**
tree against one preflight request and record structure-only evidence. This is
fixture evidence, not live evidence and not approval; it has no live transport,
clears no blocker and sets no authority flag
([CAPTURE-GATE.md](CAPTURE-GATE.md)).

Phase 2.13 (laptop-only, rehearsal done): `device/myron/session-contract.json`
and `tools/myron-session` 0.1.0 adapt a fixed set of **synthetic** input
projections into the exact R1-R7 capture fixture and prove the unchanged
collector accepts it. This is not acquisition, a live transport, hardware
evidence, authorization, blocker closure or device-format qualification; no GPT,
Android boot-image or device-tree parser exists
([SESSION-GATE.md](SESSION-GATE.md)).

Phase 2.14 (laptop-only, synthetic parser done): `device/myron/bootchain-contract.json`
and `tools/myron-bootchain` 0.1.0 parse one **synthetic** GPT (revision 1.0,
92-byte headers, 128 entries of 128 bytes, primary and backup copies) byte for
byte into the R2 operation fragment the unchanged collector accepts. This is
synthetic binary parser qualification only: no captured provenance, live
transport, hardware evidence, authorization or blocker closure. R3 (boot image
headers) and R4 (selection) are **not** implemented and stay required successor
gates: the R3 schema migration (format-specific Android boot v0-v4, vendor boot
v3/v4 and DTBO; nullable or not-applicable OS-version semantics; component
roles, hash coverage and profile limits) and the R4 selection-source
qualification (a concrete selected-index source, an actual Myron witness and
contract cross-checks; parsing a DTBO or FDT does not prove selection)
([BOOTCHAIN-GATE.md](BOOTCHAIN-GATE.md)).

Phase 2.11 (laptop-only, mechanism done): kernel-contract and deployment tool
0.4.0 add synthetic coverage for standard AArch64/GKI module layouts so real
owner bytes are no longer guaranteed to fail on RELA, PREL32 exports,
section-backed CRCs, `module_layout`, or allocated extended modversions. Snapshot and
preflight tools 0.2.0 pin the new evidence format. Real-module qualification,
full vendor inventory and every live/deployment gate remain open.

Remaining Phase 2 gates are a clean reproducible source build, qualification
against the exact owner archive and symvers pair, a bounded evidence collector,
a trusted SSH host-key revalidation before another live read, and translation
of the vendor module boot order. The generic rootfs builder remains blocked because its
`/usr/lib/modules` model is incompatible with Myron's notes-keyed module sets.

## Phase 3: Arch Linux ARM rootfs

Use `tools/build-packages` and `tools/build-rootfs`; do not run the phone
installer. Required changes:

- Myron-specific package dependencies without Pixel GPU/audio/modem packages;
- NetworkManager, ModemManager/libqmi, GeoClue, PipeWire/WirePlumber, Chrony,
  BlueZ, Hyprland, Omarchy Mobile, and recovery SSH;
- a UID-neutral first-boot/session contract;
- private local provisioning for vendor firmware/calibration;
- a manifest proving no proprietary file entered the repository or public
  artifact;
- an offline image inspection that rejects boot hooks and partition writers.

Rootfs success means package resolution, staged files, unit dependencies,
licenses, and static tests pass. It does not mean the phone boots.

First safe step (done): `ROOTFS_INTEGRATION=external-contract` in the Myron
descriptor and `tools/build-rootfs --stage-only`. It resolves and installs the
Myron packages into a tree, `out/omamobile-rootfs-stage-<version>-aarch64/`,
with a MANIFEST. The stage is not bootable, not image-ready, and not
hardware-qualified. It has no kernel, modules, boot payload, ext4 image,
`.img.zst`, checksum, or smoke test, and no proprietary or vendor payload
(firmware, calibration, runtime assets). It activates no custom GPU or session
service. Without `--stage-only`, Myron still refuses the rootfs build. A stage
generation never overwrites the same version: choose a new version or remove
the previous output deliberately.
`tests/rootfs-stage` inspects a stage tree read-only.

`ROOTFS_PACKAGE_PROFILE=myron` replaces the shared Pixel-oriented package
lists for this stage. It explicitly includes NetworkManager, ModemManager,
libqmi, GeoClue, PipeWire/WirePlumber, Chrony, BlueZ, Hyprland, and the isolated
Myron Mesa/profile packages. Panfrost and unqualified camera, fingerprint, and
NFC packages remain excluded. `omamobile-apps-myron` satisfies the shell's app
profile with Maps and GeoClue only, and the stage builder rejects a resolved
dependency closure containing the generic app profile, camera/libcamera, NFC,
fingerprint, or Panfrost packages. This is package-selection evidence only;
none of those hardware paths is claimed working in Arch yet.

## Phase 4: graphics and shell

Rebuild Mesa for glibc as described in [GPU-STACK.md](GPU-STACK.md). Keep the
result isolated until it matches Attempt105. Add Myron output/input defaults to
the device profile, not to shared Pixel files.

Run the graphics ladder through nested Hyprland offline/on the existing
session. A direct DSI test requires separate approval and must reuse the proven
90-second independently supervised rollback design.

The existing Plasma system remains the recovery session until an Arch boot has
passed repeated qualification. A working Hyprland panel with missing modem,
Wi-Fi, GNSS, or charging is not a completed port.

## Phase 5: hardware services

Order by user value and risk:

1. Wi-Fi/DNS and USB rescue;
2. charging/battery/thermal guards;
3. one-shot cellular and GNSS;
4. audio input/output with speaker protection;
5. Bluetooth, sensors, cameras, NFC, fingerprint, and suspend.

Real carrier actions, speaker output, thermal stress, flashlight, suspend, and
module replacement remain attended approval gates. Cellular reconnect stays
disabled until the IPA panic is fixed or isolated.

## Phase 6: safe boot testing

No boot strategy is chosen yet. Candidate designs must preserve the current
bootable reference and avoid the generic Pixel installer. Before any boot:

1. verify exact device identity and current slot from two sources;
2. verify recovery entry without repeated fastboot dependency;
3. verify complete boot-image and rootfs backups plus hashes;
4. use a temporary or inactive target with a finite boot/recovery deadline;
5. keep WLAN or USB SSH independent of the graphical session;
6. show exact writes, stop conditions, and rollback commands;
7. obtain explicit approval for that one operation.

No upstream `install-phone`, slot change, repartition, filesystem format, or
boot-image write is authorized by this plan.

Legacy `tools/phone-provision`, `tools/phone-install-package`, and subsystem
`*-stage` helpers are not descriptor-gated. Do not use them on Myron. They need
a verified live-compatible identity check before any Myron workflow may call
them.

The `bin/omamobile` refusal also depends on selecting `DEVICE=myron`; the
project default remains `cheetah`. Do not run a device-transition command with
the default target while Myron is connected. A live-compatible identity check
must precede any future Myron write path.

## Test architecture

Repository gates:

- descriptor uses `external-android` and names no writable partition;
- all generic persistent/disruptive commands fail before invoking SSH,
  fastboot, or a container;
- device package stages metadata only;
- descriptor copies remain identical;
- the package test rejects Pixel SoC/DTB/DTBO assignments in the descriptor;
- `tools/pr-check` rejects committed binary/vendor extensions;
- every subsystem probe is independent and reports `UNKNOWN` rather than
  falsely passing an untested feature.

Future build gates:

- package build and rootfs generation;
- service/unit dependency validation;
- exact kernel/module compatibility;
- firmware provision manifest without redistribution;
- GPU equivalence with explicit llvmpipe rejection.

## Risks and stop conditions

| Risk | Stop condition |
| --- | --- |
| Pixel installer writes the wrong slot | any Myron path reaches `fastboot`, SSH, or image preparation under `external-android` |
| Kernel/module ABI mismatch | notes hash, symbol CRC, import set, or vendor-module validation differs |
| GPU regression | llvmpipe, system Gallium, multiple unexpected Vulkan devices, or KGSL fault increment |
| Modem panic | any reconnect attempt or IPA interface reopen without a dedicated approved runbook |
| Speaker damage | missing calibration/protection/watchdog or unapproved audible test |
| Loss of recovery | slot/partition uncertainty, missing exact backups, or rollback dependent only on the active UI/SSH terminal |
| Silent hardware regression | any reference-working matrix row lacks an independent Arch probe |

## Next implementation task

Offline refusal tooling is now complete through the preflight request, and the
fixture collector (Phase 2.12) can check the shape of pre-captured evidence; the
synthetic adapter rehearsal (Phase 2.13) shows synthetic projections adapt into that
fixture, and the synthetic GPT parser (Phase 2.14) parses one synthetic GPT into R2
only (the R3 schema migration and the R4 selection-source qualification are the
required successor gates). Next,
assemble a **real** kit and snapshot candidate from the owner-supplied qualified
archive, runtime tree and symvers pair, then generate and independently review
its preflight request SHA-256. That work stays offline. The following boundary
is explicit human approval for one bounded read-only recovery/SSH evidence
session implementing `R1`–`R7`; it is not deployment approval. Source-lock
reproduction, complete vendor-module ordering, real capture/restore, boot-chain
design, hardware qualification and independent deployment authorization still
follow. Do not deploy, activate services, import Attempt105's Alpine binaries,
or use Pixel `/usr/lib/modules` or installer assumptions.
