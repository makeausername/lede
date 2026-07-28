#!/bin/sh

set -eu

script="${1:-custom/hkc-wan-dhcp.sh}"
tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT INT TERM

run_case() {
	proto="$1"
	expect_change="$2"
	log="$tmpdir/$proto.log"

	(
		uci() {
			if [ "$1" = '-q' ] && [ "$2" = 'get' ] && [ "$3" = 'network.wan.proto' ]; then
				[ "$proto" = 'missing' ] && return 1
				printf '%s\n' "$proto"
				return 0
			fi
			printf '%s\n' "$*" >>"$log"
		}
		. "$script"
	)

	if [ "$expect_change" = 'yes' ]; then
		grep -Fqx -- "-q set network.wan=interface" "$log"
		grep -Fqx -- "-q set network.wan.device=eth1" "$log"
		grep -Fqx -- "-q set network.wan.proto=dhcp" "$log"
		grep -Fqx -- "-q commit network" "$log"
	else
		test ! -e "$log"
	fi
}

run_case missing yes
run_case dhcp yes
run_case pppoe no
run_case static no
