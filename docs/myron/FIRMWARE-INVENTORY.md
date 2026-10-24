<!-- SPDX-License-Identifier: MIT -->
# Myron firmware and vendor-asset inventory

Status: metadata-only audit on 2026-10-24. No proprietary file is included in
this repository. Hashes remain in the private reference manifest and are not
duplicated here unless they identify a source-built public artifact.

## Policy

Most working hardware depends on files extracted from the owner's stock
installation. Their reference manifest marks them `stock-extracted` and
`extract-only`. They must not be committed, packaged in a public repository,
attached to a release, or copied from the running phone into this repository.

An eventual Myron provisioner must:

1. accept a user-supplied, exact Xiaomi factory/recovery source;
2. verify product, version, source hashes, and destination allowlist;
3. extract only the files required by a named subsystem;
4. produce a local manifest with hashes and provenance;
5. inject files only into the user's private rootfs copy;
6. provide a removal/rollback manifest.

## Inventory by subsystem

| Subsystem | Required asset classes | Provenance / state |
| --- | --- | --- |
| GPU | four gen80200 firmware files; KGSL/governor/stat modules | stock-extracted; all four firmware files present live; Attempt105 hashes them |
| Wi-Fi | cfg80211/CNSS/QCA CLD modules, firmware service, board config | stock-extracted; working in reference system |
| Bluetooth | power module, controller firmware, board-specific NVM | stock-extracted; controller starts, discovery broken |
| Cellular | IPA/IPANETM/RMNET-control modules and Qualcomm modem firmware/config | stock-extracted plus source-built ModemManager/libqmi components; data working, reconnect unsafe |
| GNSS | Qualcomm LOC service through the modem stack | same radio firmware path; patched source-built ModemManager converts position reports for GeoClue |
| Audio | AudioReach/FastRPC/DSP modules, ACDB, backend/card XML, amplifier firmware/calibration | mostly stock-extracted; input/output partial and safety gates incomplete |
| Charging | `batterysecret`, Android linker/runtime subset, health libraries | stock-extracted local runtime plus one source-built property shim; working but not redistributable |
| Touch | focaltech and Xiaomi touch modules | stock-extracted; working |
| Camera | downstream modules plus matched Android AIDL/CamX runtime and tuning | kernel interfaces partial; userspace bridge unfinished |

Canonical reference metadata is
`../myron-postmarketos/config/myron-runtime-assets.tsv`. The current file has
83 pinned asset records spanning stock extraction, source-built outputs, and a
repository-generated manifest.

## GPU firmware observed live

The following required names existed under `/usr/lib/firmware`:

```text
gen80200_aqe.fw
gen80200_gmu.bin
gen80200_sqe.fw
gen80200_zap.mbn
```

Their bytes are not part of this port. A future local extractor must reproduce
the reference hashes before GPU activation.

## Source-built components

Source-built outputs are not automatically redistributable binaries. Their
source, patches, license, and reproducible build must be brought into the Arch
package flow first. Current examples include:

- patched ModemManager and its Qualcomm SoC plugin;
- libqmi compatibility work;
- the GKI Qualcomm PD mapper candidate;
- the charging property shim;
- combined Mesa Zink/Turnip/KGSL.

The Arch port should package these from source. It must not import Alpine APKs
or live ELF files as release payloads.

## Unresolved provenance gates

- clean-checkout extraction is not yet demonstrated;
- some reference inputs live in ignored private directories;
- the source lock does not reproduce the accepted kernel output yet;
- audio calibration and charging runtime redistribution terms need review;
- modem NV and per-device calibration must remain device-local and must never
  be treated as generic firmware;
- camera runtime/tuning provenance is incomplete;
- the Attempt105 r1 APK and timestamp patch are untracked in the reference
  checkout and must be reconciled before an Arch graphics build is accepted.
