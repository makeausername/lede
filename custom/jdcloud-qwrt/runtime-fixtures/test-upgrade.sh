#!/bin/sh
export PATH=/bin:/sbin:/usr/bin:/usr/sbin
fail() { /semi "FAIL: $*\n$(cat /tmp/result)"; poweroff -f; exit 1; }
/semi 'QWRT_ORIGINAL_KERNEL_INIT_STARTED\n'
exec >/tmp/result 2>&1
uname -a
mount -t proc proc /proc || fail proc
mount -t sysfs sysfs /sys || fail sysfs
losetup /dev/loop0 /candidate.squashfs || fail loop
mount -t squashfs -o ro /dev/loop0 /mnt || fail squashfs
cd /mnt
sha256sum -c /expected.sha256 >/tmp/hashes.log 2>&1 || fail full_hashes
echo FULL_ROOTFS_HASHES_PASS "$(wc -l </tmp/hashes.log)"
cd /
umount /mnt || fail unmount
losetup -d /dev/loop0 || fail detach
/semi 'FULL_ROOTFS_HASHES_PASS\n'
mkdir -p /tmp/sysinfo
echo 'jdcloud,ax1800-pro' >/tmp/sysinfo/board_name
. /lib/upgrade/fwtool.sh
. /lib/upgrade/platform.sh
. /lib/upgrade/mmc.sh
fwtool_check_image /candidate.bin || fail original_metadata
platform_check_image /candidate.bin || fail original_platform
echo ORIGINAL_METADATA_AND_PLATFORM_PASS
echo 'wrong,board' >/tmp/sysinfo/board_name
if fwtool_check_image /candidate.bin; then fail wrong_board_accepted; fi
echo WRONG_BOARD_REJECTED
echo 'jdcloud,ax1800-pro' >/tmp/sysinfo/board_name
# All block devices below refer ONLY to sparse files on the guest RAM rootfs.
# No physical disk, network adapter, host share, or router exists in this VM.
dd if=/dev/zero of=/tmp/kernel-disk bs=1M count=0 seek=6 || fail kernel_disk
dd if=/dev/zero of=/tmp/root-disk bs=1M count=0 seek=300 || fail root_disk
/usr/sbin/losetup /dev/loop6 /tmp/kernel-disk || fail kernel_loop
/usr/sbin/losetup /dev/loop7 /tmp/root-disk || fail root_loop
board_name() { echo 'jdcloud,ax1800-pro'; }
find_mmc_part() {
 case "$1" in '0:HLOS') echo /dev/loop6;; rootfs) echo /dev/loop7;; *) fail unexpected_partition;; esac
}
losetup() {
 # Vendor detach-all targets mounted physical disks on the real router.
 # Here the simulated target partitions themselves use loop devices.
 if [ "$1" = '--detach-all' ]; then echo SIMULATION_RETAIN_TARGET_LOOPS; return 0; fi
 /usr/sbin/losetup "$@"
}
umount() {
 if [ "$1" = '-a' ]; then echo SIMULATION_SKIP_GLOBAL_UNMOUNT; return 0; fi
 /bin/busybox umount "$@"
}
reboot() { echo SIMULATION_REBOOT_INTERCEPTED; }
export UPGRADE_BACKUP=/tmp/sysupgrade.tgz BACKUP_FILE=sysupgrade.tgz
for mode in reset preserve; do
 if [ "$mode" = preserve ]; then echo SYNTHETIC_BACKUP_ONLY >$UPGRADE_BACKUP; else rm -f "$UPGRADE_BACKUP"; fi
 platform_do_upgrade /candidate.bin || fail "platform_$mode"
 echo "$KERNEL_SHA  /dev/loop6" | sha256sum -c - || fail kernel_output
 dd if=/dev/loop7 bs=65536 count=$ROOT_BLOCKS 2>/dev/null | sha256sum >/tmp/root-hash
 [ "$(cut -d ' ' -f1 /tmp/root-hash)" = "$ROOT_SHA" ] || fail root_output
 /usr/sbin/losetup -o "$ROOT_BYTES" /dev/loop0 /dev/loop7 || fail overlay_loop
 mount -t ext4 /dev/loop0 /mnt || fail overlay_mount
 if [ "$mode" = preserve ]; then cmp /mnt/sysupgrade.tgz "$UPGRADE_BACKUP" || fail backup_copy
 else [ ! -e /mnt/sysupgrade.tgz ] || fail unexpected_backup; fi
 echo "$mode" >/mnt/test-write && sync && [ "$(cat /mnt/test-write)" = "$mode" ] || fail overlay_write
 umount /mnt || fail overlay_unmount
 /usr/sbin/losetup -d /dev/loop0 || fail overlay_detach
 rmdir /tmp/new_root
 echo UPGRADE_RAM_SIMULATION_PASS "$mode"
 /semi "UPGRADE_RAM_SIMULATION_PASS $mode\n"
done
/semi "$(cat /tmp/result)"
/semi '\nQWRT_ORIGINAL_KERNEL_TEST_END\n'
poweroff -f
