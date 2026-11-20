#!/bin/sh
# Only the audited 6 MiB HLOS / 300 MiB rootfs layout is supported.
# Checks are read-only; writes are confined to the two verified image targets.

hkc_jdcloud_error() {
	echo "HKC JDCloud: $*" >&2
	return 1
}

hkc_jdcloud_part_geometry() {
	local name="${1##*/}"
	[ "$(cat /sys/class/block/$name/start 2>/dev/null)" = "$2" ] &&
		[ "$(cat /sys/class/block/$name/size 2>/dev/null)" = "$3" ]
}

hkc_jdcloud_layout() {
	[ "$(board_name)" = 'jdcloud,re-ss-01' ] || return 1
	HKC_KERNEL="$(find_mmc_part '0:HLOS')"
	HKC_ROOT="$(find_mmc_part 'rootfs')"
	[ "$HKC_KERNEL" = /dev/mmcblk0p16 ] && [ "$HKC_ROOT" = /dev/mmcblk0p17 ] || return 1
	[ -b "$HKC_KERNEL" ] && [ -b "$HKC_ROOT" ] || return 1
	hkc_jdcloud_part_geometry "$HKC_KERNEL" 16418 12288 &&
		hkc_jdcloud_part_geometry "$HKC_ROOT" 28706 614400
}

hkc_jdcloud_sizes() {
	case "$1:$2" in *[!0-9:]*|:*|*:) return 1 ;; esac
	[ "$1" -gt 0 ] && [ "$1" -le 6291456 ] &&
		[ "$2" -ge 65536 ] && [ "$2" -le 297795584 ] &&
		[ $(( $2 % 65536 )) -eq 0 ]
}

hkc_jdcloud_archive() {
	local image="$1" expected actual
	[ -f "$image" ] || return 1
	expected="$(printf '%s\n' sysupgrade-jdcloud_re-ss-01/ sysupgrade-jdcloud_re-ss-01/CONTROL sysupgrade-jdcloud_re-ss-01/kernel sysupgrade-jdcloud_re-ss-01/root | sort)"
	actual="$(tar tf "$image" 2>/dev/null | sort)"
	[ "$actual" = "$expected" ] || return 1
	[ "$(tar xOf "$image" sysupgrade-jdcloud_re-ss-01/CONTROL 2>/dev/null)" = 'BOARD=jdcloud_re-ss-01' ] || return 1
	HKC_KERNEL_BYTES="$(tar xOf "$image" sysupgrade-jdcloud_re-ss-01/kernel 2>/dev/null | wc -c)"
	HKC_ROOT_BYTES="$(tar xOf "$image" sysupgrade-jdcloud_re-ss-01/root 2>/dev/null | wc -c)"
	hkc_jdcloud_sizes "$HKC_KERNEL_BYTES" "$HKC_ROOT_BYTES" || return 1
	[ "$(tar xOf "$image" sysupgrade-jdcloud_re-ss-01/kernel 2>/dev/null | head -c 4 | hexdump -v -e '1/1 "%02x"')" = d00dfeed ] &&
		[ "$(tar xOf "$image" sysupgrade-jdcloud_re-ss-01/root 2>/dev/null | head -c 4 | hexdump -v -e '1/1 "%02x"')" = 68737173 ]
}

hkc_jdcloud_check_image() {
	hkc_jdcloud_layout || { hkc_jdcloud_error 'board or partition layout differs'; return 1; }
	hkc_jdcloud_archive "$1" || { hkc_jdcloud_error 'invalid archive, image type or capacity'; return 1; }
}

hkc_jdcloud_do_upgrade() {
	local image="$1" work loopdev digest actual part target kernel_sha root_sha rc=1
	# Recheck immediately before the stage2 writer. Never fall back to default flashing.
	hkc_jdcloud_check_image "$image" || return 1
	if [ -n "${UPGRADE_BACKUP:-}" ] && [ ! -f "$UPGRADE_BACKUP" ]; then
		hkc_jdcloud_error 'requested configuration backup is missing'
		return 1
	fi
	work="$(mktemp -d /tmp/hkc-jdcloud.XXXXXX)" || return 1
	tar xOf "$image" sysupgrade-jdcloud_re-ss-01/kernel >"$work/kernel" &&
		tar xOf "$image" sysupgrade-jdcloud_re-ss-01/root >"$work/root" || {
		rm -rf "$work"; return 1;
	}
	# Extraction must succeed completely before touching either block device.
	[ "$(wc -c <"$work/kernel")" -eq "$HKC_KERNEL_BYTES" ] &&
		[ "$(wc -c <"$work/root")" -eq "$HKC_ROOT_BYTES" ] || {
		rm -rf "$work"; return 1;
	}
	# Hash both source payloads before any block-device write.
	kernel_sha="$(sha256sum "$work/kernel")" && root_sha="$(sha256sum "$work/root")" || {
		hkc_jdcloud_error 'cannot hash source payloads'; rm -rf "$work"; return 1;
	}
	kernel_sha="${kernel_sha%% *}"; root_sha="${root_sha%% *}"
	[ "${#kernel_sha}" -eq 64 ] && [ "${#root_sha}" -eq 64 ] || {
		hkc_jdcloud_error 'invalid source digest'; rm -rf "$work"; return 1;
	}
	losetup --detach-all || { rm -rf "$work"; return 1; }
	for part in kernel root; do
		case "$part" in kernel) target="$HKC_KERNEL"; digest="$kernel_sha" ;; root) target="$HKC_ROOT"; digest="$root_sha" ;; esac
		dd if="$work/$part" of="$target" bs=65536 conv=fsync || {
			hkc_jdcloud_error "write failed: $part"; rm -rf "$work"; return 1;
		}
		actual="$(head -c "$(wc -c <"$work/$part")" "$target" | sha256sum)" || {
			hkc_jdcloud_error "cannot hash readback: $part"; rm -rf "$work"; return 1;
		}
		actual="${actual%% *}"
		[ "$digest" = "$actual" ] || {
			hkc_jdcloud_error "readback failed: $part"; rm -rf "$work"; return 1;
		}
	done
	loopdev="$(losetup -f)" || { rm -rf "$work"; return 1; }
	losetup -o "$HKC_ROOT_BYTES" "$loopdev" "$HKC_ROOT" || { rm -rf "$work"; return 1; }
	if mkfs.ext4 -F -L rootfs_data "$loopdev" && mkdir "$work/overlay" && mount -t ext4 "$loopdev" "$work/overlay"; then
		rc=0
		if [ -n "${UPGRADE_BACKUP:-}" ]; then
			cp "$UPGRADE_BACKUP" "$work/overlay/$BACKUP_FILE" || rc=1
		fi
		umount "$work/overlay" || rc=1
	fi
	losetup -d "$loopdev" || rc=1
	rm -rf "$work"
	[ "$rc" -eq 0 ] || { hkc_jdcloud_error 'overlay setup failed'; return 1; }
	sync
	# Common sysupgrade stage2 owns reboot. No boot environment, GPT, or data-partition writes.
	return 0
}
