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

Successful verification only proves byte identity with the recorded reference.
It does not authorize flashing, module loading, service activation, or changes
to a running phone.
