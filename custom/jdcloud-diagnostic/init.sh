#!/bin/sh /etc/rc.common
START=19
USE_PROCD=1
start_service() {
	[ "$(cat /tmp/sysinfo/board_name)" = 'jdcloud,re-ss-01' ] || return 0
	procd_open_instance
	procd_set_param command /bin/sh /usr/libexec/hkc-jdcloud-boot
	# Deliberately no respawn: the worker has a bounded retry budget.
	procd_set_param stdout 0
	procd_set_param stderr 1
	procd_close_instance
}
