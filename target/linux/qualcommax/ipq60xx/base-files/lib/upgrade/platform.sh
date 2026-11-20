PART_NAME=firmware
REQUIRE_IMAGE_METADATA=1

RAMFS_COPY_BIN='fw_printenv fw_setenv head sha256sum mkfs.ext4 losetup mktemp'
RAMFS_COPY_DATA='/etc/fw_env.config /var/lock/fw_printenv.lock'

platform_check_image() {
	if [ "$(board_name)" = 'jdcloud,re-ss-01' ]; then
		. /lib/upgrade/hkc-jdcloud.sh
		hkc_jdcloud_check_image "$1"
		return $?
	fi
	return 0;
}

platform_do_upgrade() {
	case "$(board_name)" in
	jdcloud,re-ss-01)
		. /lib/upgrade/hkc-jdcloud.sh
		# Common do_stage2 ignores a returned failure and reboots anyway.
		# Exit this stage2 shell on failure; never announce a failed write as complete.
		hkc_jdcloud_do_upgrade "$1" || exit 1
		return 0
		;;
	anysafe,e1|\
	cmiot,ax18|\
	glinet,gl-ax1800|\
	glinet,gl-axt1800|\
	qihoo,360v6|\
	xiaomi,rm1800)
		nand_do_upgrade "$1"
		;;
	jdcloud,re-cs-02|\
	jdcloud,re-cs-07|\
	link,nn6000-v1|\
	link,nn6000-v2|\
	philips,ly1800|\
	redmi,ax5-jdcloud)
		kernelname="0:HLOS"
		rootfsname="rootfs"
		mmc_do_upgrade "$1"
		;;
	linksys,mr7350)
		boot_part="$(fw_printenv -n boot_part)"
		if [ "$boot_part" -eq "1" ]; then
			fw_setenv boot_part 2
			CI_KERNPART="alt_kernel"
			CI_UBIPART="alt_rootfs"
		else
			fw_setenv boot_part 1
			CI_UBIPART="rootfs"
		fi
		fw_setenv boot_part_ready 3
		fw_setenv auto_recovery yes
		nand_do_upgrade "$1"
		;;
	*)
		default_do_upgrade "$1"
		;;
	esac
}
