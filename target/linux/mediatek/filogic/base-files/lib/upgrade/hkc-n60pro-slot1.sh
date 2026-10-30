# HKC N60 PRO stock-layout slot-1 helpers. Functions only: safe to source.
# Never write bootloader environment, stock volumes, Factory or raw MTD.
hkc_slot1_error() { echo "HKC stock-slot1: $*" >&2; return 1; }
hkc_slot1_board() { tr '\000' '\n' </proc/device-tree/compatible | head -n 1; }
hkc_slot1_read() { cat "$1" 2>/dev/null; }
hkc_slot1_volume() { nand_find_volume "$HKC_UBI" "$1"; }

hkc_slot1_context() {
    [ "$(hkc_slot1_board)" = netcore,n60-pro-stock-slot1 ] || return 1
    local spec name offset size dir count matched mtd
    for spec in BL2:0:1048576 u-boot-env:1048576:524288 Factory:1572864:2097152 FIP:3670016:2097152 ubi:5767168:120061952; do
        name=${spec%%:*}; spec=${spec#*:}; offset=${spec%%:*}; size=${spec#*:}
        count=0; matched=
        for dir in /sys/class/mtd/mtd[0-9]*; do
            [ "$(hkc_slot1_read "$dir/name")" = "$name" ] || continue
            count=$((count+1)); matched=${dir##*/}
            [ "$(hkc_slot1_read "$dir/offset")" = "$offset" ] &&
                [ "$(hkc_slot1_read "$dir/size")" = "$size" ] || return 1
        done
        [ "$count" = 1 ] || return 1
        [ "$name" != ubi ] || mtd=${matched#mtd}
    done
    HKC_UBI=$(nand_find_ubi ubi)
    case "$HKC_UBI" in ubi[0-9]) ;; *) return 1 ;; esac
    [ "$(hkc_slot1_read /sys/class/ubi/$HKC_UBI/mtd_num)" = "$mtd" ] || return 1
    [ "$(hkc_slot1_read /sys/class/ubi/$HKC_UBI/ro_mode)" = 0 ] || return 1
    HKC_LEB=$(hkc_slot1_read /sys/class/ubi/$HKC_UBI/eraseblock_size)
    HKC_FREE=$(hkc_slot1_read /sys/class/ubi/$HKC_UBI/avail_eraseblocks)
    [ "$HKC_LEB" = 126976 ] || return 1
    case "$HKC_FREE" in ''|*[!0-9]*) return 1 ;; esac
    local reserve=$(hkc_slot1_read /sys/class/ubi/$HKC_UBI/reserved_for_bad)
    case "$reserve" in ''|*[!0-9]*) return 1 ;; esac
    [ "$reserve" -ge 19 ] || return 1
    # Original slot and its configuration must still exist and are never modified.
    for name in u-boot-env kernel rootfs rootfs_ext rootfs_data kernel2 rootfs2; do
        [ -n "$(hkc_slot1_volume "$name")" ] || return 1
    done
}

hkc_slot1_active_root() {
    local vol=$(hkc_slot1_volume rootfs2) expected actual
    [ -n "$vol" ] || return 1
    expected=$(hkc_slot1_read /sys/class/block/ubiblock${vol#ubi}/dev)
    actual=$(awk '($5=="/" || $5=="/rom") { for(i=6;i<=NF;i++) if($i=="-" && $(i+1)=="squashfs") {print $3;exit} }' /proc/self/mountinfo)
    [ -n "$expected" ] && [ "$actual" = "$expected" ]
}

hkc_slot1_overlay() {
    hkc_slot1_context && hkc_slot1_active_root || { hkc_slot1_error 'root/layout validation failed; no volume changed'; return 1; }
    local vol=$(hkc_slot1_volume hkc_data) blocks
    if [ -n "$vol" ]; then
        blocks=$(hkc_slot1_read /sys/class/ubi/$vol/reserved_ebs)
        case "$blocks" in ''|*[!0-9]*) return 1 ;; esac
        [ "$blocks" -ge 67 ] || { hkc_slot1_error 'existing HKC overlay too small; not resized'; return 1; }
        return 0
    fi
    # 8 MiB rounds up to 67 LEBs; retain another 16 available LEBs.
    [ "$HKC_FREE" -ge 83 ] || { hkc_slot1_error 'insufficient space for isolated overlay'; return 1; }
    ubimkvol /dev/$HKC_UBI -N hkc_data -s 8388608 || return 1
    sync
    vol=$(hkc_slot1_volume hkc_data)
    [ -n "$vol" ] && [ "$(hkc_slot1_read /sys/class/ubi/$vol/reserved_ebs)" -ge 67 ]
}

hkc_slot1_image() {
    local image="$1" listing control
    HKC_DIR=sysupgrade-netcore_n60-pro-stock-slot1
    listing=$(tar tf "$image" 2>/dev/null) || return 1
    # Only our exact four tar entries; no duplicates, extra paths, legacy profile.
    [ "$(printf '%s\n' "$listing" | sort)" = "$(printf '%s\n' "$HKC_DIR/" "$HKC_DIR/CONTROL" "$HKC_DIR/kernel" "$HKC_DIR/root" | sort)" ] || return 1
    tar xOf "$image" >/dev/null 2>&1 || return 1
    control=$(tar xOf "$image" "$HKC_DIR/CONTROL") || return 1
    [ "$control" = BOARD=netcore_n60-pro-stock-slot1 ] || return 1
    [ "$(identify_tar "$image" "$HKC_DIR/kernel")" = fit ] || return 1
    [ "$(identify_tar "$image" "$HKC_DIR/root")" = squashfs ] || return 1
    HKC_KERNEL_SIZE=$(tar xOf "$image" "$HKC_DIR/kernel" | wc -c)
    HKC_ROOT_SIZE=$(tar xOf "$image" "$HKC_DIR/root" | wc -c)
    [ "$HKC_KERNEL_SIZE" -gt 0 ] && [ "$HKC_KERNEL_SIZE" -le 16777216 ] || return 1
    [ "$HKC_ROOT_SIZE" -gt 0 ] && [ "$HKC_ROOT_SIZE" -le 67108864 ] || return 1
    HKC_KERNEL_SHA=$(tar xOf "$image" "$HKC_DIR/kernel" | sha256sum | cut -d' ' -f1)
    HKC_ROOT_SHA=$(tar xOf "$image" "$HKC_DIR/root" | sha256sum | cut -d' ' -f1)
}

hkc_slot1_capacity() {
    local available=$HKC_FREE vol blocks name needed
    for name in kernel2 rootfs2 hkc_data; do
        vol=$(hkc_slot1_volume "$name")
        [ -n "$vol" ] || return 1
        blocks=$(hkc_slot1_read /sys/class/ubi/$vol/reserved_ebs)
        case "$blocks" in ''|*[!0-9]*) return 1 ;; esac
        available=$((available+blocks))
    done
    needed=$(((HKC_KERNEL_SIZE+HKC_LEB-1)/HKC_LEB+(HKC_ROOT_SIZE+HKC_LEB-1)/HKC_LEB+67+16))
    [ "$available" -ge "$needed" ]
}

hkc_slot1_check() {
    hkc_slot1_context && hkc_slot1_active_root && hkc_slot1_image "$1" && hkc_slot1_capacity
}

hkc_slot1_write() {
    local image="$1" name vol got
    # Recheck independent of the UI/check stage; ramfs has no /rom mount anymore.
    hkc_slot1_context && hkc_slot1_image "$image" && hkc_slot1_capacity || return 1
    for name in rootfs2 kernel2 hkc_data; do
        vol=$(hkc_slot1_volume "$name")
        [ -n "$vol" ] || return 1
        nand_remove_ubiblock "$vol" || return 1
    done
    for name in rootfs2 kernel2 hkc_data; do
        ubirmvol /dev/$HKC_UBI -N "$name" || return 1
    done
    ubimkvol /dev/$HKC_UBI -N rootfs2 -s "$HKC_ROOT_SIZE" || return 1
    ubimkvol /dev/$HKC_UBI -N kernel2 -s "$HKC_KERNEL_SIZE" || return 1
    ubimkvol /dev/$HKC_UBI -N hkc_data -s 8388608 || return 1
    # Root first; kernel last. Propagate every volume-update and readback failure.
    vol=$(hkc_slot1_volume rootfs2)
    [ -n "$vol" ] || return 1
    tar xOf "$image" "$HKC_DIR/root" | ubiupdatevol /dev/$vol -s "$HKC_ROOT_SIZE" - || return 1
    got=$(head -c "$HKC_ROOT_SIZE" /dev/$vol | sha256sum | cut -d' ' -f1)
    [ "$got" = "$HKC_ROOT_SHA" ] || return 1
    vol=$(hkc_slot1_volume kernel2)
    [ -n "$vol" ] || return 1
    tar xOf "$image" "$HKC_DIR/kernel" | ubiupdatevol /dev/$vol -s "$HKC_KERNEL_SIZE" - || return 1
    got=$(head -c "$HKC_KERNEL_SIZE" /dev/$vol | sha256sum | cut -d' ' -f1)
    [ "$got" = "$HKC_KERNEL_SHA" ] || return 1
    # SAVE_CONFIG=0 means no archive. Never reuse the vendor data volume.
    if [ -f /tmp/sysupgrade.tgz ]; then
        hkc_slot1_restore /tmp/sysupgrade.tgz || return 1
    fi
    sync
}

hkc_slot1_restore() {
    local vol=$(hkc_slot1_volume hkc_data)
    [ -n "$vol" ] || return 1
    mkdir -p /tmp/hkc-new-root || return 1
    mount -t ubifs /dev/$vol /tmp/hkc-new-root || return 1
    if ! cp "$1" /tmp/hkc-new-root/sysupgrade.tgz; then
        umount /tmp/hkc-new-root
        return 1
    fi
    sync
    umount /tmp/hkc-new-root || return 1
    rmdir /tmp/hkc-new-root
}
