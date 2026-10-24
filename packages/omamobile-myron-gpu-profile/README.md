<!-- SPDX-License-Identifier: MIT -->
# omamobile-myron-gpu-profile

Activation-disabled contract for using `mesa-myron-zink-turnip` in one future
Myron graphical session. Installing this package cannot select the custom Mesa
stack. It installs no systemd unit or drop-in, environment generator, Vulkan
loader registration, shell profile, package hook, udev rule, or `/etc` file.

`profile.env` and `session-drop-in.conf.disabled` are inert data under the
package's private `/usr/share/omamobile/myron-gpu-profile` directory. The
drop-in has no target unit because the Arch session owner and unit name remain
unqualified. It also explicitly removes `WAYLAND_DISPLAY`, `AQ_BACKEND`, and
`EGL_PLATFORM`; a future native compositor session must select DRM itself.

The command has four operations:

```text
omamobile-myron-gpu-profile show
omamobile-myron-gpu-profile environment
omamobile-myron-gpu-profile verify-static --root ROOT
omamobile-myron-gpu-profile verify-live
```

`environment` prints JSON. It does not export, persist, or apply anything.
`verify-static` checks the exact inert assets and internally verifies the Mesa
manifest, checksums, AArch64 ELF headers, symlinks, tree, and ICD path. It also
scans a bounded list of standard loader, systemd, shell, package-hook, Vulkan,
and udev activation locations for the private prefix or profile file. It opens
no DRM, KGSL, input, or sysfs device. This is a static packaging guard, not a
proof that no custom activation path exists outside the enumerated locations.

`verify-live` always refuses because no qualified live-probe reference ships.
Adding a live probe is a later, separately reviewed phase with bounded logging,
GPU-fault stop conditions, and session rollback. Hardware qualification and
phone deployment remain pending.
