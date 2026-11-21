#!/bin/sh
[ "${ACTION:-}" = add ] || exit 0
if [ "$(cat /tmp/sysinfo/board_name 2>/dev/null)" = 'jdcloud,re-ss-01' ]; then
	# kmodloader can emit an event before board_detect installs the encrypted
	# defaults. Defer that event; the bounded worker detects both radios later.
	[ "$(jsonfilter -i /etc/board.json -e '@.wlan.defaults.ssids["2g"].encryption' 2>/dev/null)" = sae-mixed ] || exit 0
	[ "$(jsonfilter -i /etc/board.json -e '@.wlan.defaults.ssids["5g"].encryption' 2>/dev/null)" = sae-mixed ] || exit 0
fi
/sbin/wifi config
