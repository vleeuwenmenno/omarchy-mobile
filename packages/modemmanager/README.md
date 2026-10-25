# Myron ModemManager snapshot

This package is the Arch Linux ARM translation of the ModemManager build that
already provides modem data and GNSS on Myron's postmarketOS installation.
It pins the same upstream revision and carries the Myron-specific patches for:

- driverless downstream `rmnet_ipa` detection and endpoint discovery;
- QMAP mux setup through the downstream RMNET ioctl ABI;
- serialized carrier-configuration requests;
- AFW LOC registration, position-report conversion, and operation-mode races.

Build `packages/libqmi` first.  The AFW patch calls generated APIs absent from
the 1.38.0 release package:

```sh
tools/build-packages --dev-unsigned packages/libqmi packages/modemmanager
```

Installing these packages does not enable ModemManager in the hardware-test
image.  Discovery, GNSS, bearer creation, SMS, and calls remain separate
attended gates.
