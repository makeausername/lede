#!/bin/sh
# Apply the phone-tested LAN policy without disabling system IPv6 or ::1.
set -eu

# Validate the HKC LAN layout before writing any configuration. Device order
# can differ after an upgrade, so locate br-lan by name, not @device[0].
test "$(uci -q get network.lan.device)" = br-lan
test "$(uci -q get dhcp.lan.interface)" = lan
test "$(uci -q get 'dhcp.@dnsmasq[0]')" = dnsmasq
lan_section=''
for section in $(uci -q show network | sed -n 's/^network\.\([^.=]*\)=device$/\1/p'); do
    if [ "$(uci -q get "network.$section.name")" = br-lan ]; then
        test -z "$lan_section"
        lan_section=$section
    fi
done
test -n "$lan_section"
rule_type="$(uci -q get firewall.hkc_lan_ipv4_only || true)"
test -z "$rule_type" || test "$rule_type" = rule

# Disabling IPv6 on this bridge also covers clients with cached IPv6 addresses.
# Leave WAN/WAN6, the loopback device and global IPv6 sysctls unchanged.
uci -q set "network.$lan_section.ipv6=0"
uci -q delete network.lan.ip6assign || true
uci -q set dhcp.lan.ra=disabled
uci -q set dhcp.lan.dhcpv6=disabled
uci -q set dhcp.lan.ndp=disabled
uci -q set dhcp.lan.ra_slaac=0
uci -q set 'dhcp.@dnsmasq[0].filter_aaaa=1'

# Keep IPv4 forwarding intact; this named rule is safe to apply again.
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
# uci-defaults runs before network/DNS/firewall startup; no service reload here.
exit 0
