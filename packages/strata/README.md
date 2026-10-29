<!-- SPDX-License-Identifier: MIT -->
# strata

Pacman package of [LGSE Strata](https://github.com/lgse/strata) v1.1.1, built
from the official `aarch64-unknown-linux-gnu` release archive. The archive is
downloaded by `makepkg` and pinned by SHA-256; no binary is in this repository.
It needs glibc >= 2.39 and GTK >= 4.12 (the phone has glibc 2.43, GTK 4.24).

Pin (checked 2026-10-29):

| | |
| --- | --- |
| Release | `v1.1.1`, stable, published 2026-10-25 |
| Archive | `strata-1.1.1-aarch64-unknown-linux-gnu.tar.gz`, 19811494 bytes |
| SHA-256 | `d6d8e41e1e00df7702e9a1a2624c3b8ee11b638a3a6db48f5ae2ef4db1188d4a` |
| Source commit | `fb0315529cecbe5019963b7adcbf5d3be1e75a78` (GitHub: verified commit) |
| Provenance | `gh attestation verify <archive> -R LGSE/strata` passed; the same digest is in the release's signed `strata-update-manifest.json` |

Upgrade: verify the new release the same way, then change `pkgver`,
`sha256sums` and `_source_commit` together.

## What it installs

`/usr/bin/strata`, `io.github.lgse.Strata.desktop`, the icon, upstream docs and
licences (Strata embeds the non-free UnRAR code; its licence is in
`/usr/share/licenses/strata/UnRAR.txt`), and the optional portal files
`strata.portal` and the portal D-Bus service. It does **not** claim
`inode/directory` or `org.freedesktop.FileManager1`, and does not change the
portal selection: `omamobile-apps-myron` does that.

## Updates

Strata checks for updates on start, but a binary owned by pacman is treated as
package-managed: it only reads the pacman sync database and never replaces
`/usr/bin/strata`, and it never installs anything without confirmation. The
package changes only when this repository bumps it.
