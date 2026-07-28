#!/bin/sh

set -eu

# Netcore N60 Pro has a dedicated 2.5G WAN on eth1. Repair only a missing or
# DHCP WAN definition so upgrades never overwrite PPPoE or static settings.
wan_proto="$(uci -q get network.wan.proto || true)"
case "$wan_proto" in
	''|dhcp)
		uci -q set network.wan='interface'
		uci -q set network.wan.device='eth1'
		uci -q set network.wan.proto='dhcp'
		uci -q set network.wan.peerdns='1'
		uci -q set network.wan.delegate='1'
		uci -q commit network
		;;
esac

exit 0
