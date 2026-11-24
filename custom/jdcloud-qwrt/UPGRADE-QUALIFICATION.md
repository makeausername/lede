# Original-kernel and upgrade-container qualification

The scripts in this phase produce **private offline research artifacts**. Do not
upload them to a router, distribute them, or interpret a passing check as hardware
boot qualification. They contain the original root filesystem and are not sanitized
for release. The U-Boot recovery format is separate from the sysupgrade tar format.

`package-hkc-jdcloud-qwrt-upgrade.py` accepts only the pinned original 6 MiB FIT
partition and the previously qualified root filesystem. It verifies both FIT CRC32
and SHA1, the original kernel IKCONFIG, exact board DTB, XZ SquashFS v4, 64 KiB root
padding, partition bounds, and remaining overlay space. The USTAR container has
exactly one board directory, CONTROL, kernel and root. fwtool metadata supports only
`jdcloud,ax1800-pro`. No GPT, bootloader, ART or other partition payload is included.

`verify-hkc-jdcloud-qwrt-kernel.py` boots the **unmodified original 5.4.250 Image**
using a synthetic QEMU virt board and an initramfs, without NICs, host disks or
shared directories. All inputs are hash-pinned. Original QWRT binaries and scripts
run in guest RAM. A small static ELF uses semihosting SYS_WRITE0 only to report
results because this kernel has no virtual UART driver. QEMU userspace semihosting
must be used only with these trusted pinned inputs; it is not a guest security
boundary. See https://www.qemu.org/docs/master/system/invocation.html#hxtool-8 .

The test mounts the actual candidate SquashFS and verifies every regular file.
It then runs the original metadata checker (including a wrong-board negative test)
and original platform/mmc upgrade functions against loop devices backed by guest
RAM files. Kernel and root output hashes, ext4 creation at the exact appended-root
offset, ext4 mount/read/write, and synthetic backup preservation are checked.
Only board/partition lookup, detach-all (to retain the simulated target partitions),
global unmount and reboot are intercepted. No real device operation occurs.

The original platform_check_image returns success unconditionally, and the original
mmc script does not fail closed on all write/format/copy errors. The host checks are
stricter, but do not change that future on-device upgrade behavior. A complete
device-side upgrade guard remains required before release. Backup-copy success in
the RAM test does not prove that an arbitrary customer's retained configuration is
compatible with the migrated userspace.

Remaining release gates:

- Original config_generate still defaults LAN to 192.168.1.1; requested 192.168.2.1
  fresh-reset behavior and preserving customized user settings require qualification.
- Private credential/config cleanup and a clear preserve/reset policy.
- Physical IPQ/NSS, Ethernet and wireless boot, actual upgrade, and recovery testing.
- Post-install maintenance upgrades must fail closed on malformed images/I/O errors.

The kernel test validates filesystem compatibility on virtual hardware. It does not
run the physical IPQ device tree or vendor hardware initialization and cannot prove
the earlier blue-LED/no-LAN failure is impossible.
