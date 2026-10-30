#!/bin/sh
# Read-only stock-firmware inventory. No upload, test-flash, env writes, or keys.
set -u
value() { printf '%s=%s\n' "$1" "$2"; }
value schema 1
value board "$(cat /tmp/sysinfo/board_name 2>/dev/null)"
value model "$(uci -q get customer.info.up_model)"
value vendor_version "$(cat /etc/VERSION 2>/dev/null)"
for key in dual_boot boot_image_slot upgrade_image_slot boot_kernel_part boot_rootfs_part upgrade_kernel_part upgrade_rootfs_part reserve_rootfs_data rootfs_data_part; do
    value "$key" "$(cat /sys/module/boot_param/parameters/$key 2>/dev/null)"
done
for name in BL2 u-boot-env Factory FIP ubi; do
    found=0
    for dir in /sys/class/mtd/mtd[0-9]*; do
        [ -f "$dir/name" ] || continue
        [ "$(cat "$dir/name")" = "$name" ] || continue
        found=$((found+1))
        value "mtd.$name.offset" "$(cat "$dir/offset")"
        value "mtd.$name.size" "$(cat "$dir/size")"
    done
    value "mtd.$name.count" "$found"
done
for key in bad_peb_count reserved_for_bad avail_eraseblocks eraseblock_size ro_mode; do
    value "ubi.$key" "$(cat /sys/class/ubi/ubi0/$key 2>/dev/null)"
done
for dir in /sys/class/ubi/ubi0_*; do
    [ -f "$dir/name" ] || continue
    value "volume.$(cat "$dir/name")" "$(cat "$dir/reserved_ebs")"
done
if [ -s /etc/fw.key ]; then value encryption_key present; else value encryption_key absent; fi
if [ -e /tmp/image_ignore_signature ]; then value ignore_signature present; else value ignore_signature absent; fi
# Only one public slot variable is read; stderr is reduced to a state, not dumped.
env_result="$(fw_printenv -n dual_boot.current_slot 2>&1)"
case "$env_result" in
    *'Bad CRC'*) value env_state default_bad_crc ;;
    0|1) value env_state valid; value env_current_slot "$env_result" ;;
    *) value env_state unknown ;;
esac
value web_auto_flashes "$(grep -Fc 'sysupgrade -c $UPGRADE_IMG' /www/cgi-bin/upgrade 2>/dev/null)"
exit 0
