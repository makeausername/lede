# HKC Redmi AX6000 stock-layout candidate

Status: source adaptation only. No firmware build, image upload, sysupgrade test,
flash or reboot has been performed for this target. This is not a release.

## Isolation and feature parity

Base: `6cb7723430091ab26c3b734b95c743e10eccafa4`.
Branch: `codex/redmi-ax6000-stock` in a separate worktree.
The N60 profile, DTS, workflow, application patches, defaults, translations and
12-file stability/time-sync runtime manifest remain unchanged. The AX6000 config
only changes the selected device. Shared board/upgrade scripts add cases for the
new stock-layout ID; existing N60 and merged AX6000 routes are preserved.

`custom/hkc-ax6000-baseline.json` pins the existing stable sources. The candidate
workflow copies the pinned N60 application/defaults pipeline, and the regression
check enforces parity. Future N60 changes require deliberate revalidation here.

Candidate workflow: `.github/workflows/hkc-redmi-ax6000-stock.yml`. Ordinary branch
pushes do not build. Builds require a deliberately pushed `hkc-ax6000-test-*` tag
or manual dispatch on this branch. The explicit tag route works without adding
this workflow to stable master (GitHub may not expose branch-only manual workflows).
Do not create/push build tags or dispatch yet. No remote push was performed.
It retains N60 patch/runtime checks and adds FIT/embedded DTB/partition/metadata,
wireless package and UBI-capacity checks. The UI and product defaults match N60;
physical port count, board identity and radio capabilities reflect AX6000 hardware.

## Inspected device and boot evidence

Xiaomi Redmi Router AX6000, MT7986A, 512 MiB RAM, 128 MiB SPI NAND with NMBM.
Old firmware: ImmortalWrt 18.06-5.4-SNAPSHOT r11886-64b0e82a2, kernel 5.4.224,
vendor mt_wifi driver. The new source uses the current Filogic mt76 driver stack.

| Region | Offset | Size |
| --- | --- | --- |
| ubi_kernel | 0x00600000 | 0x01e00000 (30 MiB) |
| ubi | 0x02400000 | 0x05000000 (80 MiB) |

All preceding boot/calibration partitions and the trailing NMBM area retain their
original locations. The stock DTS includes existing AX6000 wiring and replaces
only board identity and the merged UBI definition. No Bootloader replacement or
partition conversion is implemented. Boot/calibration partitions remain read-only.

The inspected router exposes a whole-chip mtd0, so its Nvram is mtd2, not mtd1.
Old fw_env.config incorrectly points at BL2. Offline Nvram parsing found a valid
64 KiB CRC-protected environment, `bootcmd=bootxq`, active firmware 0, boot_wait on,
flag_boot_rootfs=0, flag_last_success=1, flag_boot_success=1 and both failure
counters >= 6. These flags match the documented forced-system-0 arrangement.
They were NOT changed, and the new target does not reset or rewrite them.
The new environment configuration resolves Nvram/Bdata by label, not MTD number.

The kernel volume contains an ARM64 LZMA FIT with config-1. Its old Linux 5.4
load/entry is 0x48080000. The new generic Filogic kernel uses 0x48000000; the image
check requires the modern ARM64 Image text_offset to be zero. Do not copy the old
load address blindly. Actual new-image boot remains a required acceptance step.

## Upgrade boundaries

The old LuCI calls `sysupgrade -T`; its metadata needs legacy board ID
`xiaomi,redmi-router-ax6000`. Candidate metadata includes that ID and the new
stock ID. This does NOT make the candidate compatible with merged-layout units
sharing the legacy ID. Verify the actual partition map before every migration.

The inspected old upgrade code already writes kernel to ubi_kernel/kernel and
root to ubi/rootfs. New platform handling preserves that split for later upgrades
and propagates validation failures. No force-flash path is added.

Do not preserve the old vendor wireless/network configuration across this driver
and major-version transition. Back up and separately migrate necessary WAN and
subscription settings. This is a future upgrade requirement, not an action taken
on the current router. No generic old-device updater is deployed.

## Backups and recovery boundary

Local private backup made on 2026-10-28 in the original checkout under
`artifacts/new-router-audit-20261028/backup/`: nine logical MTD partition images,
configuration/private keys and running DTB. All nine MTD hashes matched a second
read from the device. The SHA256 manifest is local only. Never commit or upload
these private files. Online rootfs backup is not an atomic offline NAND image.

UART boot interruption and RAM-based recovery are the recovery route to prepare
before flashing (boot_wait is on). Have a serial adapter/access and a known-good,
matching-layout recovery image available. Recovery has NOT been exercised, and
the partition dumps are not a recipe for blind raw NAND writes: NMBM and device
calibration must be preserved. Do not modify BL2/FIP/Nvram/Factory to test a build.

## Validation and next gate

Run `python3 scripts/test-hkc-ax6000.py --shell /bin/sh` on Linux, or use Git Bash
with `--shell` on Windows. Checks cover stable-source hashes, settings parity,
explicit-build-only scope, upgrade routes, error propagation, LAN/WAN mapping,
label-based environment mapping and negative DTB fixtures.

Local YAML/shell syntax and real backed-up FIT/DTB parser checks passed. Windows
has no local dtc/toolchain; the new DTS has not yet been compiled. During the next
explicitly authorized build, the normal kernel build compiles the DTS and the
image gate reads that actual embedded DTB. No build success is claimed here.

Before flash: complete the candidate build and artifact checks; compare actual
SHA256; confirm recovery readiness; upload only the verified stock-layout image
to RAM and run `sysupgrade -T` without `-F`; obtain explicit flash authorization.
A passing test is not proof of successful boot. Afterwards test Ethernet, both
Wi-Fi bands, proxy/DNS, time synchronization, reboot and sustained use.

References:
- https://raw.githubusercontent.com/openwrt/openwrt/openwrt-24.10/target/linux/mediatek/dts/mt7986a-xiaomi-redmi-router-ax6000-stock.dts
- https://raw.githubusercontent.com/openwrt/openwrt/openwrt-24.10/target/linux/mediatek/filogic/base-files/lib/upgrade/platform.sh
- https://openwrt.org/toh/xiaomi/redmi_ax6000
