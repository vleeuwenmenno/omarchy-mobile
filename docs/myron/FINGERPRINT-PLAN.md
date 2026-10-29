# Myron fingerprint bring-up

Status: read-only inventory completed on installed Omarchy, 2026-10-29.
Kernel: `6.12.23-android16-5-g5a0e85dd9db0-dirty-4k`.
Enrollment, verification, fprintd and PAM integration are not qualified.

## Confirmed hardware and userspace

The `xiaomi_fingerprint` DT node is enabled and bound to `xiaomi-fp`, backed
by the loaded `mi_fp` module. The current boot exposes `/dev/xiaomi-fp`
(491:0), `/dev/mifp_id` (491:1), `/dev/qbt_ipc` (491:2) and `/dev/smcinvoke`.
The Qualcomm qbt-handler platform node is unbound. No additional module load
is needed to establish that the Xiaomi IPC driver is present.

Current slot-B files differ from the September stock capture. Do not use
the old `mfp-daemon` filename as the extraction contract. The current files are:

| File | SHA-256 |
| --- | --- |
| `vendor/bin/hw/android.hardware.biometrics.fingerprint-service.xiaomi` | `4cbf4f901fe2fc0ece4845fded3024224cba5ab028a833bcaa25f9a65da0d80b` |
| `odm/lib64/hw/fingerprint.goodix_us2.default.so` | `759af5689467d4469040a139e5335f9322627f5122079e7c70a6d8aac11649a1` |
| `odm/lib64/libgf_hal.so` | `a9fba8c54aba1c6ca8026b1defc5e0c2cb5c891fc3eeeab869f9f941e0b74d48` |
| `vendor/lib64/libQSEEComAPI.so` | `691e541d6857ec7e327a6faeaf3d7d589ca4deb091fd0fe258441aba878ed66b` |

The VINTF manifest declares fingerprint AIDL V4, `IFingerprint/default`.
The init service is `vendor.fingerprint-default`, class `late_start`, user
`system`, groups `system input uhid`, capability `SYS_NICE`. Its comment
explains that startup waits for files under `/data`.

The wrapper links the V4 fingerprint and common interfaces plus common
config/thread/util libraries. It selects a legacy fingerprint HAL and contains
the `goodix_us2` selection string. The Goodix module links `libgf_hal`, which
imports `QSEECom_start_app`, QSEE command/shutdown functions, Binder/HIDL,
DMA heap, ION and Xiaomi fx.tunnel libraries. This is not the Pixel
Trusty/G7 backend implemented by the existing fingerprint package.

Strings establish paths, not executed behavior: `libgf_hal` contains
`/dev/xiaomi-fp`, `/vendor/firmware_mnt/image`, and an ION-open failure message.
`/dev/ion` is absent on this boot; DMA-heap fallback remains unproven.
The wrapper contains `/data/vendor_de/{}/fpdata/`. The exact trusted-app
selection and storage side effects are still unproven. Firmware files named
`fingerpr.*` alone do not establish which TA this HAL loads.

## Reproducible inspection and cleanup

`tools/myron-fingerprint-stock-inspect` is a developer-only inspection tool,
not a shipping service. It requires Omarchy/root, validates the super block
identity and exact single extents, then uses read-only loop mappings. ext4
mounts additionally use `noload`; all mounts use `nosuid,nodev,noexec`.
It copies only fixed HAL/config files and metadata to a private archive.
It does not execute vendor code, open fingerprint devices, or read calibration.
It refuses an existing evidence directory rather than overwriting it.

The first EROFS-only mount failed because vendor is ext4. Cleanup was verified.
The corrected inventory found renamed files; the final capture contains all
seven selected files. No temporary mount or super-backed loop remained after
completion. Private captures are under
`out/private/myron-fingerprint-stock-20261029/r4` and on the phone under
`/var/tmp/myron-fingerprint-stock-20261029-r4`. Earlier failed/candidate
captures remain separate. These proprietary files must not be committed.
No production configuration changed; no image-composer or runtime deployment
change is required for this inspection tool.

## Next gates

1. Build an owner-stock-only dependency manifest for this exact wrapper and
   Goodix HAL. Determine the configured HAL properties, TA selection and
   DMA-heap versus ION path offline. Do not execute a HAL to discover its writes.
2. Define an isolated runtime with explicit device access, private writable
   data, and a verified secure-storage/calibration policy. Review its first
   startup separately because opening the HAL can initialize secure state.
3. Implement a Myron backend for the existing fprintd protocol only after
   validating the actual V4/legacy HAL semantics. Pixel coordinates, Trusty
   services and LHBM behavior are not defaults for Myron.
4. Perform owner-approved enrollment and real verification. Only then add
   per-service sudo PAM with a backup and independent SSH recovery. Keep
   `system-auth` unchanged and prove password fallback on cancel, timeout,
   missing hardware and stopped fprintd.

No enrollment, HAL startup, RPMB/storage service, module load, reboot, or PAM
edit was performed during this inspection. Mobile data remained On afterward.
