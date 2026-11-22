#!/bin/sh
# Research defaults for the recovered QWRT legacy bridge schema only.
# Not installed until the complete userspace-port gates have passed.
set -eu
. /lib/functions.sh
. /lib/functions/system.sh
[ "$(board_name)" = 'jdcloud,ax1800-pro' ]
[ "$(uci -q get network.lan.type)" = bridge ]
[ "$(uci -q get network.wan.ifname)" = eth3 ]
ports="$(uci -q get network.lan.ifname)"
[ "$(printf '%s\n' "$ports" | tr ' ' '\n' | sed '/^$/d' | sort | tr '\n' ' ')" = 'eth0 eth1 eth2 ' ]
[ "$(uci -q get dhcp.lan.interface)" = lan ]
[ "$(uci -q get 'dhcp.@dnsmasq[0]')" = dnsmasq ]
# A conflicting named section must never be overwritten.
kind="$(uci -q get firewall.hkc_lan_ipv4_only || true)"
[ -z "$kind" ] || [ "$kind" = rule ]
uci -q set network.lan.ipv6=0
uci -q delete network.lan.ip6assign || true
uci -q set dhcp.lan.ra=disabled
uci -q set dhcp.lan.dhcpv6=disabled
uci -q set dhcp.lan.ndp=disabled
uci -q set dhcp.lan.ra_slaac=0
uci -q set 'dhcp.@dnsmasq[0].filter_aaaa=1'
uci -q set firewall.hkc_lan_ipv4_only=rule
uci -q set 'firewall.hkc_lan_ipv4_only.name=HKC LAN IPv4 only'
uci -q set firewall.hkc_lan_ipv4_only.src=lan
uci -q set firewall.hkc_lan_ipv4_only.dest=wan
uci -q set firewall.hkc_lan_ipv4_only.family=ipv6
uci -q set firewall.hkc_lan_ipv4_only.proto=all
uci -q set firewall.hkc_lan_ipv4_only.target=REJECT
uci -q set firewall.hkc_lan_ipv4_only.enabled=1
uci -q commit network
uci -q commit dhcp
uci -q commit firewall
# No global IPv6 switch, WAN changes, service restart or network reload.
