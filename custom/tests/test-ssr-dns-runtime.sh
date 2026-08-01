#!/bin/sh
set -eu

root="${1:?usage: test-ssr-dns-runtime.sh <luci-app-ssr-plus-root>}"
init="$root/root/etc/init.d/shadowsocksr"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
mkdir -p "$work/dnsmasq"

# Execute the production start_dns function with deterministic UCI and process
# stubs. This checks the real argument builder without exposing a subscription
# or depending on public DNS availability in CI.
dns2tcp_source="$(awk '
	/^wait_for_udp_listener\(\) \{/ { copy=1 }
	/^supports_builtin_dns\(\) \{/ { copy=0 }
	copy { print }
' "$init")"
start_dns_source="$(awk '
	/^start_dns\(\) \{/ { copy=1 }
	/^generate_xray_config\(\) \{/ { copy=0 }
	copy { print }
' "$init")"
test -n "$dns2tcp_source"
test -n "$start_dns_source"
eval "$dns2tcp_source"
eval "$start_dns_source"

capture="$work/argv"
uci_get_by_type() {
	case "$2" in
		pdnsd_enable) echo "${dns_mode:-6}" ;;
		chinadns_ng_tunnel_forward) echo '8.8.8.8:53' ;;
		chinadns_ng_proto) echo tcp ;;
		chinadns_forward) echo '223.5.5.5:53' ;;
		apple_optimization) echo 0 ;;
		*) echo "${3:-}" ;;
	esac
}
uci_get_by_name() {
	case "$2" in
		type) echo v2ray ;;
		*) echo "${3:-}" ;;
	esac
}
normalize_run_mode() { echo router; }
get_filter_aaaa() { echo 0; }
add_dns_into_ipset() { :; }
first_type() { echo "/usr/bin/$1"; }
ifstatus() { echo '{}'; }
jsonfilter() { echo '119.29.29.29'; }
echolog() { :; }
ln_start_bin() {
	printf 'CALL' >>"$capture"
	for arg in "$@"; do
		printf '\t%s' "$arg" >>"$capture"
	done
	printf '\n' >>"$capture"
}
wait_for_udp_listener() { return 0; }

HAS_IPSET=0
GLOBAL_SERVER='test-node'
TMP_DNSMASQ_PATH="$work/dnsmasq"
tmp_dns_port=300
dns_port=5335
china_dns_port=5333
pdnsd_enable_flag=0
dns_mode=6

start_dns
test "$(grep -c '^CALL' "$capture")" -eq 2
tab="$(printf '\t')"
grep -F "${tab}-t${tab}tcp://8.8.8.8#53" "$capture" >/dev/null
if grep -F "${tab} -t tcp://8.8.8.8#53" "$capture" >/dev/null; then
	echo 'ChinaDNS-NG trust DNS was collapsed into one invalid argv entry' >&2
	exit 1
fi

# A missing proxy DNS listener must make startup fail instead of reporting a
# false-positive running state.
wait_for_udp_listener() {
	[ "$1" != "$dns_port" ]
}
if start_dns; then
	echo 'start_dns accepted a missing 5335 proxy DNS listener' >&2
	exit 1
fi

# The production default is DNS2TCP. Its listener failure must propagate out
# of start_dns so the service cannot install redirect rules around a dead DNS
# path and then falsely report itself as running.
dns_mode=1
if start_dns; then
	echo 'start_dns accepted a failed DNS2TCP default path' >&2
	exit 1
fi

echo 'SSR DNS argument and listener tests passed'
