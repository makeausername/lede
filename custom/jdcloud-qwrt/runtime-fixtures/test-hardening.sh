#!/bin/sh
export PATH=/bin:/sbin:/usr/bin:/usr/sbin
fail() { /semi "FAIL: $*\n$(cat /tmp/result)"; poweroff -f; exit 1; }
/semi 'HKC_HARDENING_BEGIN\n'
exec >/tmp/result 2>&1
uname -a
for source in /init /lib/upgrade/platform.sh /lib/upgrade/hkc-guard.sh /etc/board.d/99_hkc_lan; do
 /bin/busybox sh -n "$source" || fail native_shell_syntax
done
mount -t proc proc /proc && mount -t sysfs sysfs /sys || fail mount
mkdir -p /etc/config /tmp/sysinfo /var/lock
echo jdcloud,ax1800-pro >/tmp/sysinfo/board_name
losetup /dev/loop0 /candidate.squashfs && mount -t squashfs -o ro /dev/loop0 /mnt || fail squashfs
cd /mnt
sha256sum -c /expected.sha256 >/tmp/hashes.log 2>&1 || fail full_hashes
echo FULL_ROOTFS_HASHES_PASS "$(wc -l </tmp/hashes.log)"
cd /
umount /mnt && losetup -d /dev/loop0 || fail detach
rm /candidate.squashfs
/semi 'FULL_ROOTFS_HASHES_PASS\n'
# Run the original config generator, changing only generated board defaults.
cat >/etc/board.json <<'EOF'
{"model":{"id":"jdcloud,ax1800-pro"},"network":{"lan":{"ifname":"eth0 eth1 eth2","protocol":"static"},"wan":{"ifname":"eth3","protocol":"dhcp"}}}
EOF
export CFG=/etc/board.json
/bin/sh /etc/board.d/99_hkc_lan || fail board_hook
/bin/sh /bin/config_generate || fail config_generate
[ "$(uci get network.lan.ipaddr)" = 192.168.2.1 ] || fail default_ip
[ "$(uci get network.lan.ifname)" = 'eth0 eth1 eth2' ] || fail lan_ports
[ "$(uci get network.wan.ifname)" = eth3 ] || fail wan_port
[ "$(uci get network.wan.proto)" = dhcp ] || fail wan_proto
echo FACTORY_LAN_PASS
uci set network.lan.ipaddr=10.23.45.1 && uci commit network || fail set_retained
/bin/sh /etc/board.d/99_hkc_lan && /bin/sh /bin/config_generate || fail retained_generate
[ "$(uci get network.lan.ipaddr)" = 10.23.45.1 ] || fail retained_ip
echo RETAINED_LAN_PASS
rm /etc/config/network
/bin/sh /bin/config_generate || fail reset_generate
[ "$(uci get network.lan.ipaddr)" = 192.168.2.1 ] || fail reset_ip
echo RESET_LAN_PASS
cp /etc/board.json /tmp/board-before
echo wrong,board >/tmp/sysinfo/board_name
/bin/sh /etc/board.d/99_hkc_lan || fail other_board
cmp -s /etc/board.json /tmp/board-before || fail other_board_modified
echo jdcloud,ax1800-pro >/tmp/sysinfo/board_name
echo WRONG_BOARD_DEFAULTS_PASS
. /lib/functions.sh
. /lib/functions/system.sh
. /lib/upgrade/fwtool.sh
. /lib/upgrade/platform.sh
mkdir /tmp/prepared
hkc_prepare /candidate.bin /tmp/prepared || fail real_prepare
echo STRICT_PREPARE_PASS
root_size=$hkc_size;root_hash=$hkc_sha
# Truncation must fail before any target writing.
head -c 2048 /candidate.bin >/tmp/truncated.bin
if hkc_prepare /tmp/truncated.bin /tmp/prepared; then fail truncated_accepted; fi
echo TRUNCATED_IMAGE_REJECTED
# Restore the validated staged bytes and use them for isolated writer/fault tests.
hkc_size=$root_size;hkc_sha=$root_hash
dd if=/dev/zero of=/tmp/root-disk bs=1M count=0 seek=300 || fail disk
losetup /dev/loop7 /tmp/root-disk || fail target
board_name() { cat /tmp/sysinfo/board_name; }
hkc_parts() { hkc_kernel=/not-a-writable-kernel;hkc_root=/dev/loop7; }
hkc_prepare() {
 hkc_size=$root_size;hkc_sha=$root_hash
 cp /tmp/prepared/root "$2/root"
}
losetup() {
 if [ "$1" = --detach-all ]; then return 0; fi
 /usr/sbin/losetup "$@"
}
for mode in reset preserve; do
 unset UPGRADE_BACKUP
 if [ "$mode" = preserve ]; then
  tar -czf /tmp/sysupgrade.tgz -C / etc/config/network || fail backup_create
  export UPGRADE_BACKUP=/tmp/sysupgrade.tgz
 fi
 (platform_do_upgrade /candidate.bin; echo REBOOT_ALLOWED) >"/tmp/upgrade-$mode.log" 2>&1 || fail "upgrade_$mode"
 grep -q REBOOT_ALLOWED "/tmp/upgrade-$mode.log" || fail missing_success
 /usr/sbin/losetup -o "$root_size" /dev/loop0 /dev/loop7 && mount -t ext4 /dev/loop0 /mnt || fail overlay
 if [ "$mode" = preserve ]; then cmp -s /mnt/sysupgrade.tgz /tmp/sysupgrade.tgz || fail backup; else [ ! -e /mnt/sysupgrade.tgz ] || fail unexpected_backup; fi
 echo test >/mnt/write-test && sync && [ "$(cat /mnt/write-test)" = test ] || fail overlay_write
 umount /mnt && /usr/sbin/losetup -d /dev/loop0 || fail detach_overlay
 echo HARDENED_UPGRADE_PASS "$mode"
 /semi "HARDENED_UPGRADE_PASS $mode\n"
done
unset UPGRADE_BACKUP
rm /candidate.bin
mkdir -p /tmp/fault-bin
cat >/tmp/fault-bin/mkfs.ext4 <<'EOF'
#!/bin/sh
case "$HKC_FAULT" in format) exit 1;; mount|copy|sync) exit 0;; esac
exec /usr/sbin/mke2fs "$@"
EOF
chmod 755 /tmp/fault-bin/mkfs.ext4
# Each injected failure must exit platform_do_upgrade, suppressing the caller's reboot.
for fault in validation partition detach write readback format mount copy sync; do
 /semi "FAULT_BEGIN $fault\n"
 (
  export HKC_FAULT="$fault" PATH="/tmp/fault-bin:$PATH"
  case "$fault" in
   validation) hkc_prepare() { return 1; };;
   partition) hkc_parts() { return 1; };;
   detach) losetup() { return 1; };;
   write) dd() { return 1; };;
   readback) dd() { case "$1" in if=/dev/loop7) return 1;; *) /bin/busybox dd "$@";; esac; };;
   format) hkc_write_root() { return 0; };;
   mount) hkc_write_root() { return 0; }; mount() { return 1; };;
   copy) hkc_write_root() { return 0; }; export UPGRADE_BACKUP=/tmp/sysupgrade.tgz; cp() { case "$2" in */overlay/sysupgrade.tgz) return 1;; *) /bin/busybox cp "$@";; esac; };;
   sync) hkc_write_root() { return 0; }; sync() { return 1; };;
  esac
  platform_do_upgrade /candidate.bin
  echo REBOOT_UNEXPECTED
 ) >"/tmp/fault-$fault.log" 2>&1
 status=$?
 /semi "FAULT_EXIT $fault $status\n"
 [ "$status" != 0 ] && ! grep -q REBOOT_UNEXPECTED "/tmp/fault-$fault.log" || fail "fault_$fault"
 echo FAILURE_STOPS_REBOOT "$fault"
done
/semi "$(cat /tmp/result)"
/semi '\nHKC_HARDENING_END\n'
poweroff -f
