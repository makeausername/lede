PART_NAME=firmware
REQUIRE_IMAGE_METADATA=1
RAMFS_COPY_BIN='fw_printenv fw_setenv fwtool jshn lua sha256sum flock cmp readlink mktemp'
RAMFS_COPY_DATA='/etc/fw_env.config /var/lock/fw_printenv.lock /lib/upgrade/hkc-image.lua'
. /lib/upgrade/hkc-guard.sh
platform_check_image() { hkc_check_image "$1"; }
platform_do_upgrade() {
 hkc_upgrade "$1" || {
  echo 'HKC upgrade failed; automatic reboot suppressed. Recovery may be required.' >&2
  exit 1
 }
}
