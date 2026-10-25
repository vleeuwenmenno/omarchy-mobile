# Myron libqmi snapshot

This package replaces Arch Linux ARM's release build with the exact upstream
libqmi revision already qualified by the Myron postmarketOS modem/GNSS stack.
It adds generated LOC Register Events setters for the `MHAL` client string,
the AFW client type, and positioning-request notification.

It changes no modem state by itself.  Build it before `packages/modemmanager`:

```sh
tools/build-packages --dev-unsigned packages/libqmi
```

The package keeps Arch's name and shared-library ABI so the local repository
selects it as a normal upgrade.  The snapshot version sorts above `1.38.0-2`.
Reference documentation is disabled because it adds minutes of qemu work and
is not installed in the hardware-test rootfs.
