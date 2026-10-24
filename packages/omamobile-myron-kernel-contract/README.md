<!-- SPDX-License-Identifier: MIT -->
# omamobile-myron-kernel-contract

This package records and verifies the exact downstream kernel contract that
was qualified on Xiaomi `myron`. It contains no kernel Image, modules,
firmware, vendor files, boot images, systemd units, hooks, or write paths.

The reference binds together the kernel release, raw Image, ELF notes,
configuration, both ABI symbol tables, and the exact seven-module VT asset
archive. A matching release string alone is never accepted. The verifier also
checks the archive member allowlist, its internal checksums, its manifest, and
the qualified module selector.

The metadata also pins the source lock, stamped manifest, and four accepted
patches. It deliberately records source-lock reproduction as unverified and
keeps activation disabled; hash metadata is not a claim that the accepted
kernel has already been reproduced from a clean checkout.

`verify-runtime` accepts the canonical private runtime-assets manifest and a
root directory. It verifies the manifest identity first, then reads and hashes
the selected files without changing them. This supports private stock asset
provisioning without committing or redistributing those bytes.

```text
omamobile-myron-kernel-verify show
omamobile-myron-kernel-verify verify-kernel \
  --image Image \
  --notes kernel-notes.bin \
  --config kernel_aarch64_dot_config \
  --vmlinux-symvers vmlinux.symvers \
  --module-symvers kernel_aarch64_Module.symvers \
  --assets systemd-vt-device-assets.tar.gz
omamobile-myron-kernel-verify verify-runtime \
  --manifest myron-runtime-assets.tsv \
  --root ROOT --features gpu,wifi,touch
```

## Stage contract (0.2.0; verify-abi added in 0.3.0)

`stage-contract.json` is a second metadata file. It binds the SHA-256 of
`reference.json` and describes an immutable, activation-disabled, metadata-only
`external-kernel-module-stage`: the eight target files: the candidate selector at
`/usr/local/sbin/myron-attempt79-module-dir` (mode 0755) and the seven GKI
modules directly under `/usr/local/lib/myron-gki-module-sets/<notes sha256>/`
(mode 0644, no `modules/` subdirectory). The archive's `SHA256SUMS`,
`manifest.json`, `kernel-notes.bin` and previous selector are verification and
rollback metadata: they are validated but never planned into the tree. The
contract also lists the paths that
must stay absent (`/boot`, firmware and vendor trees, systemd, modprobe,
modules-load, udev, pacman hook and Vulkan paths, and any non-empty
`/usr/lib/modules`). The module list and destinations are derived from
`reference.json`; the verifier rejects a contract that differs from that
derivation, or that is bound to another `reference.json`.

```text
omamobile-myron-kernel-verify show-stage
omamobile-myron-kernel-verify plan-stage --assets systemd-vt-device-assets.tar.gz
omamobile-myron-kernel-verify verify-stage \
  --assets systemd-vt-device-assets.tar.gz --root ROOT
```

- `show-stage` prints the validated contract.
- `plan-stage` validates reference, archive and contract, then prints a
  deterministic JSON plan: each destination, mode and SHA-256. The archive
  manifest must carry a `selector_destination` equal to the contract's;
  a missing or different value is refused. It runs no
  external command and writes nothing.
- `verify-stage` treats `ROOT` as a standalone overlay tree, not a complete
  root filesystem, and walks it with descriptor-confined `O_NOFOLLOW`
  traversal and bounded reads and scans. Linux `/proc/self/fdinfo` mount IDs
  make same-filesystem bind mounts fail closed for both directories and files;
  verification also fails if that mount identity is unavailable. It rejects
  relative or non-canonical roots (including `.` or `..` components), root `/`,
  every path outside the exact plan, symlinks anywhere on an
  owned path, special files, wrong modes or bytes, extra hard links, missing or
  extra owned files, any other `.ko`, the forbidden paths above, and a bind
  mount inside the tree. Staged files are hashed, never executed.

## ABI, import and load-order check (0.4.0)

```text
omamobile-myron-kernel-verify verify-abi \
  --assets systemd-vt-device-assets.tar.gz \
  --vmlinux-symvers vmlinux.symvers \
  --module-symvers kernel_aarch64_Module.symvers
```

`verify-abi` is a staged-set-only, offline, pure-Python check. It loads the
exact reference and stage contracts, validates the exact qualified archive
bytes and both symvers files by SHA-256 (before parsing either), then parses
the seven staged modules as AArch64 ELF64 `ET_REL` files with bounded reads
(no mmap, no external command, nothing written). All three inputs must be
canonical absolute paths with no symlink component and must be regular files.
It checks:

- `.modinfo` has exactly one `name` (equal to the file name, `-` and `_`
  equivalent) and one `vermagic` that starts with the kernel release and is
  identical across the set; GPL-only imports require a compatible `license`;
  ELF class, byte order, type and machine;
- undefined global/weak symbols are the imports; basic `__versions` and paired
  extended-modversions sections list exactly those imports plus optional
  `module_layout`, whose CRC is checked against `vmlinux.symvers`. When both
  formats exist, the loader-authoritative extended table must cover every
  import and every basic entry must match it;
- relocation sections have bounded ELF64 REL/RELA records, valid symbol-table
  and target links, supported AArch64 types, complete write extents,
  instruction alignment, and cannot target literal metadata or runtime export
  strings used as evidence. Allocated AArch64 targets require RELA; REL is
  structurally inspected and refused because the Android 16 loader rejects it;
- exports accept one consistent legacy two-PREL32-field 8-byte, standard
  AArch64 PREL32 12-byte, or non-PREL32 ELF64 24-byte layout per module,
  including final-linked merged `__ksymtab*` and
  `__kcrctab*` tables with exact entry coverage and loader-required export-name
  sorting. Runtime names resolve named-symbol or compiler-shaped section-symbol
  relocations with explicit RELA addends; overlapping
  writes are rejected. Per-symbol and merged 12/24-byte runtime namespace
  fields are resolved the same way and must equal `Module.symvers`; CRC evidence may be classic
  absolute or modern section-backed;
  merged CRC entries must match export count and table order because the
  kernel resolves them by export index;
- each import resolves to the kernel (`vmlinux.symvers`) or to exactly one
  staged module (`Module.symvers` provider), with CRC and namespace
  (`import_ns`) checks; unresolved imports, imports from modules outside the
  staged set or from `rmnet_core`, and duplicate providers are refused;
- each module's exports agree with its `Module.symvers` records in both
  directions (symbol, export type, CRC);
- the dependency graph has no cycle and the declared order in
  `reference.json` is a valid topological load order.

The output is deterministic JSON with `scope: staged-set-only`,
`vendor_modules: not-verified`, `activation: disabled`, the three input
hashes, the declared and resolved order and per-module imports, exports,
providers and CRC status. It carries no deployment, boot or flash claim.

**Unqualified on real modules.** Version 0.4.0 synthetically covers standard
Linux AArch64/GKI RELA sections, fail-closed allocated-REL refusal,
final-linked 12-byte PREL32 and 24-byte
ELF64 export tables, legacy 8-byte tables, classic and section-backed CRCs,
allocated basic and extended modversions, and `module_layout`.
It has still never been run on the real qualified archive. Unsupported or
malformed layouts fail deterministically. A pass proves consistency of the
staged set only; it does
not clear the deployment blocker, which stays until the real qualified
archive, the exact symvers files and the full vendor module inventory have
been checked.

**The verifier writes nothing.** It opens files read-only; it never creates,
modifies, chmods, extracts, or removes anything, and it runs no `tar`,
`depmod`, `modprobe`, `systemctl`, or network tool. (The kernel may still
update access times under the mount's own policy.) `verify-kernel` still
ignores the manifest's `selector_destination`.

Evidence limits: the checks prove byte identity with the recorded reference
plus the exact kernel release marker in each module. `verify-abi` adds an
unqualified, synthetic-layout ABI/import/provider/load-order consistency check
for the staged set only (see above); it has not been shown on real modules. No stage writer exists:
nothing extracts the archive, runs `depmod`, installs a module, or touches
boot. The contract authorizes no hardware access and no deployment.

Successful verification only proves byte identity with the recorded reference.
It does not authorize flashing, module loading, service activation, or changes
to a running phone.
