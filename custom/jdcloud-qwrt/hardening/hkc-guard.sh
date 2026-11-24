#!/bin/sh
# Only for the preserved QWRT 5.4 kernel and JDCloud mmc layout.
hkc_kernel_sha=0ca88f17c3ee8194ad0591425a927ab5e90f363b64f86f879271b058ee8247f8
hkc_error() { echo "HKC upgrade stopped: $*" >&2; return 1; }
hkc_parts() {
 [ "$(board_name)" = jdcloud,ax1800-pro ] || return 1
 [ "$(readlink -f "$(find_mmc_part '0:HLOS')")" = /dev/mmcblk0p16 ] || return 1
 [ "$(readlink -f "$(find_mmc_part rootfs)")" = /dev/mmcblk0p17 ] || return 1
 [ -b /dev/mmcblk0p16 ] && [ -b /dev/mmcblk0p17 ] || return 1
 [ "$(cat /sys/class/block/mmcblk0p16/size)" = 12288 ] || return 1
 [ "$(cat /sys/class/block/mmcblk0p17/size)" = 614400 ] || return 1
 hkc_kernel=/dev/mmcblk0p16
 hkc_root=/dev/mmcblk0p17
 echo "$hkc_kernel_sha  $hkc_kernel" | sha256sum -c - >/dev/null || return 1
}
hkc_prepare() {
 local image="$1" work="$2" schema kernel_sha
 [ -f "$image" ] && [ ! -L "$image" ] || return 1
 [ "$(board_name)" = jdcloud,ax1800-pro ] || return 1
 fwtool_check_image "$image" || return 1
 fwtool -q -i "$work/meta" "$image" || return 1
 . /usr/share/libubox/jshn.sh
 json_load "$(cat "$work/meta")" && json_select hkc_qwrt || return 1
 json_get_var schema schema
 json_get_var kernel_sha kernel_sha256
 json_get_var hkc_size rootfs_bytes
 json_get_var hkc_sha rootfs_sha256
 [ "$schema" = 1 ] && [ "$kernel_sha" = "$hkc_kernel_sha" ] || return 1
 case "$hkc_size" in ''|*[!0-9]*) return 1;; esac
 [ "${#hkc_size}" -le 9 ] || return 1
 [ "${#hkc_sha}" = 64 ] || return 1
 case "$hkc_sha" in *[!0-9a-f]*) return 1;; esac
 lua /lib/upgrade/hkc-image.lua "$image" "$hkc_size" || return 1
 tar -xOf "$image" sysupgrade-jdcloud-ax1800-pro/kernel >"$work/kernel" || return 1
 echo "$hkc_kernel_sha  $work/kernel" | sha256sum -c - >/dev/null || return 1
 tar -xOf "$image" sysupgrade-jdcloud-ax1800-pro/root >"$work/root" || return 1
 [ "$(wc -c <"$work/root")" = "$hkc_size" ] || return 1
 echo "$hkc_sha  $work/root" | sha256sum -c - >/dev/null || return 1
}
hkc_check_image() (
 umask 077
 work=$(mktemp -d /tmp/hkc-upgrade.XXXXXX) || exit 1
 trap 'rm -rf "$work"' EXIT
 hkc_parts && hkc_prepare "$1" "$work"
)
hkc_write_root() {
 # Kernel remains byte-identical and is NEVER written by this maintenance path.
 dd if="$1" of="$hkc_root" bs=65536 conv=fsync || return 1
 (set -o pipefail; dd if="$hkc_root" bs=65536 count=$((hkc_size / 65536)) 2>/dev/null | sha256sum >"$work/readback") || return 1
 [ "$(cut -d ' ' -f1 "$work/readback")" = "$hkc_sha" ]
}
hkc_upgrade() (
 umask 077
 exec 9>/tmp/hkc-upgrade.lock
 flock -n 9 || exit 1
 work=$(mktemp -d /tmp/hkc-upgrade.XXXXXX) || exit 1
 loop=''; mounted=0
 cleanup() {
  [ "$mounted" = 0 ] || umount "$work/overlay"
  [ -z "$loop" ] || losetup -d "$loop"
  rm -rf "$work"
 }
 trap cleanup EXIT
 trap 'exit 1' HUP INT TERM
 hkc_parts && hkc_prepare "$1" "$work" || { hkc_error 'image/board/partition validation'; exit 1; }
 if [ -n "${UPGRADE_BACKUP:-}" ]; then
  [ "$UPGRADE_BACKUP" = /tmp/sysupgrade.tgz ] && [ -s "$UPGRADE_BACKUP" ] && [ ! -L "$UPGRADE_BACKUP" ] || exit 1
  [ "$(wc -c <"$UPGRADE_BACKUP")" -le 16777216 ] || exit 1
  tar -tvzf "$UPGRADE_BACKUP" >"$work/backup-types" || exit 1
  [ -s "$work/backup-types" ] && ! grep -qv '^[-d]' "$work/backup-types" || exit 1
  tar -tzf "$UPGRADE_BACKUP" >"$work/backup-list" || exit 1
  # Retention is deliberately limited to the normal config backup, not overlays/scripts.
  while IFS= read -r path; do
   printf '%s\n' "$path" | LC_ALL=C grep -Eq '^[A-Za-z0-9_./-]+$' || exit 1
   case "$path" in /*|*../*|*/..|../*|*\\*) exit 1;; etc/|etc/config/|etc/dropbear/|etc/crontabs/|etc/config/*|etc/dropbear/*|etc/passwd|etc/shadow|etc/group|etc/hosts|etc/ethers|etc/sysctl.conf|etc/crontabs/*|etc/rc.local|etc/sysupgrade.conf|etc/uhttpd.*) :;; *) exit 1;; esac
  done <"$work/backup-list"
  cp "$UPGRADE_BACKUP" "$work/backup.tgz" && cmp -s "$UPGRADE_BACKUP" "$work/backup.tgz" || exit 1
 fi
 losetup --detach-all || { hkc_error 'detach overlay'; exit 1; }
 hkc_write_root "$work/root" || { hkc_error 'root write/readback'; exit 1; }
 loop=$(losetup -f) || exit 1
 losetup -o "$hkc_size" "$loop" "$hkc_root" || exit 1
 mkfs.ext4 -F -L rootfs_data "$loop" || { hkc_error 'format overlay'; exit 1; }
 mkdir "$work/overlay" && mount -t ext4 "$loop" "$work/overlay" || exit 1
 mounted=1
 if [ -n "${UPGRADE_BACKUP:-}" ]; then
  cp "$work/backup.tgz" "$work/overlay/sysupgrade.tgz" && cmp -s "$work/backup.tgz" "$work/overlay/sysupgrade.tgz" || { hkc_error 'backup copy'; exit 1; }
 fi
 sync || exit 1
 umount "$work/overlay" || exit 1
 mounted=0
 losetup -d "$loop" || exit 1
 loop=''
 # Caller may reboot only after this function returns success.
)
