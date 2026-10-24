<!-- SPDX-License-Identifier: MIT -->
# omamobile-apps-myron

Dependency-only provider for `omamobile-apps` on Xiaomi Myron. It keeps Maps
and GeoClue, whose reference path works, while camera, NFC, and libcamera stay
absent until their independent hardware gates pass.

The package installs only its version and documentation. It has no service,
hook, device rule, hardware probe, or runtime activation. The Myron rootfs
builder checks the resolved package closure and refuses a stage containing the
generic `omamobile-apps`, camera/libcamera, NFC, fingerprint, or Panfrost
packages.
