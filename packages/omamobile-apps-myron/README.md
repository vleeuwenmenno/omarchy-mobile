<!-- SPDX-License-Identifier: MIT -->
# omamobile-apps-myron

Dependency-only provider for `omamobile-apps` on Xiaomi Myron. It keeps Maps
and GeoClue, whose reference path works, while camera, NFC, and libcamera stay
absent until their independent hardware gates pass.

It also depends on `strata` and makes it the default file manager and file
chooser. `/etc/xdg/mimeapps.list` sets `inode/directory=io.github.lgse.Strata.desktop`;
a D-Bus service in `/usr/local/share/dbus-1/services` (ahead of `/usr/share` in
`XDG_DATA_DIRS`) gives `org.freedesktop.FileManager1` ("show in folder") to
Strata; and `/etc/xdg/xdg-desktop-portal/hyprland-portals.conf` picks
`FileChooser=strata;gtk` (and repeats Access=omamobile;gtk). xdg-desktop-portal
reads `/etc/xdg/...` before `omamobile-shell`'s `/etc/xdg-desktop-portal/...`,
so the shell's generic file never conflicts. Nautilus, nautilus-python and
xdg-desktop-portal-gnome are not dependencies; the Myron rootfs skips them
(`rootfs/packages.omarchy-skip.myron`) and its closure check refuses them. A
user's own `~/.config/mimeapps.list`, `~/.local/share/dbus-1/services` entry or
`~/.config/xdg-desktop-portal/` file overrides all three.

Apart from that the package installs only its version and documentation. It
has no service, hook, device rule, hardware probe, or runtime activation. The Myron rootfs
builder checks the resolved package closure and refuses a stage containing the
generic `omamobile-apps`, camera/libcamera, NFC, fingerprint, or Panfrost
packages.
