#!/bin/ash
# RAM-only QEMU fixture. All config, remote headers and service transport are synthetic.
set -eu
mkdir -p /var/lock /tmp/sysinfo /tmp/baseline /tmp/shim
printf '%s\n' jdcloud,ax1800-pro >/tmp/sysinfo/board_name
cat >/etc/config/network <<'EOF'
config interface 'loopback'
 option ifname 'lo'
 option proto 'static'
 option ipaddr '127.0.0.1'
 option ipv6 '1'
config interface 'lan'
 option type 'bridge'
 option ifname 'eth0 eth1 eth2'
 option ipaddr '192.168.2.1'
 option ip6assign '60'
config interface 'wan'
 option ifname 'eth3'
 option proto 'dhcp'
config interface 'wan6'
 option proto 'dhcpv6'
EOF
cat >/etc/config/dhcp <<'EOF'
config dnsmasq
 option domainneeded '1'
config dhcp 'lan'
 option interface 'lan'
 option ra 'server'
config dnsmasq
 option filter_aaaa '0'
EOF
printf "config defaults\n option input 'ACCEPT'\n" >/etc/config/firewall
printf "config network\n option init 'network'\n" >/etc/config/ucitrack
printf "config wifi-device 'radio0'\n option channel 'auto'\n" >/etc/config/wireless
uci set 'shadowsocksr.@global[0].switch_time=667'
uci set 'shadowsocksr.@server_subscribe[0].auto_update_time=7'
uci commit shadowsocksr
# Simulate later vendor theme selection before luci-ssr-plus runs.
uci set luci.main.mediaurlbase=/luci-static/design
uci set luci.main.lang=en
uci commit luci
for p in network dhcp firewall shadowsocksr ucitrack wireless luci; do cp -p /etc/config/$p /tmp/baseline/$p; done
restore() {
 for p in network dhcp firewall shadowsocksr ucitrack wireless luci; do cp -p /tmp/baseline/$p /etc/config/$p; done
 rm -f /etc/hkc-qwrt-defaults-v1
}
fingerprint() { sha256sum /etc/config/*; }
check_common() {
 [ "$(uci get network.lan.ifname)" = 'eth0 eth1 eth2' ]
 [ "$(uci get network.wan.ifname)" = eth3 ]
 [ "$(uci get network.lan.ipaddr)" = 192.168.2.1 ]
 [ "$(uci get network.wan.proto)" = dhcp ]
 [ "$(uci get network.wan6.proto)" = dhcpv6 ]
 [ "$(uci get network.loopback.ipv6)" = 1 ]
 [ "$(uci get network.lan.ipv6)" = 0 ]
 ! uci -q get network.lan.ip6assign
 [ "$(uci get dhcp.lan.ra)" = disabled ]
 [ "$(uci get 'dhcp.@dnsmasq[0].filter_aaaa')" = 1 ]
 [ "$(uci get 'dhcp.@dnsmasq[1].filter_aaaa')" = 0 ]
 [ "$(uci get firewall.hkc_lan_ipv4_only.target)" = REJECT ]
 [ "$(uci get firewall.shadowsocksr.path)" = /var/etc/shadowsocksr.include ]
 [ "$(uci get luci.main.mediaurlbase)" = /luci-static/argon ]
 [ "$(uci get luci.main.lang)" = en ]
 cmp -s /etc/config/wireless /tmp/baseline/wireless
}
lua -e 'local c=require("uci").cursor(); local j=require("luci.jsonc"); print(j.stringify(c:get_all("shadowsocksr","fixture")))' >/tmp/node-before
fingerprint >/tmp/deferred-before
(. /etc/uci-defaults/luci-ssr-plus)
fingerprint >/tmp/deferred-after
cmp -s /tmp/deferred-before /tmp/deferred-after
[ ! -e /etc/hkc-qwrt-defaults-v1 ]
(. /etc/uci-defaults/zzz_hkc-qwrt)
check_common
[ "$(uci get 'shadowsocksr.@global[0].switch_time')" = 30 ]
[ "$(uci get 'shadowsocksr.@server_subscribe[0].proxy')" = 0 ]
[ "$(uci get 'shadowsocksr.@server_subscribe[0].auto_update_day_time')" = 7 ]
lua -e 'local c=require("uci").cursor(); local j=require("luci.jsonc"); print(j.stringify(c:get_all("shadowsocksr","fixture")))' >/tmp/node-after
cmp -s /tmp/node-before /tmp/node-after
echo INTEGRATION_DEFAULTS PASS
fingerprint >/tmp/before
/usr/libexec/hkc-qwrt-defaults
fingerprint >/tmp/after
cmp -s /tmp/before /tmp/after
echo INTEGRATION_IDEMPOTENT PASS
restore
uci set 'shadowsocksr.@global[0].switch_time=77'
uci set 'shadowsocksr.@global[0].monitor_enable=0'
uci set 'shadowsocksr.@server_subscribe[0].proxy=1'
uci set 'shadowsocksr.@server_subscribe[0].auto_update_day_time=19'
uci commit shadowsocksr
/usr/libexec/hkc-qwrt-defaults
[ "$(uci get 'shadowsocksr.@global[0].switch_time')" = 77 ]
[ "$(uci get 'shadowsocksr.@global[0].monitor_enable')" = 0 ]
[ "$(uci get 'shadowsocksr.@server_subscribe[0].proxy')" = 1 ]
[ "$(uci get 'shadowsocksr.@server_subscribe[0].auto_update_day_time')" = 19 ]
echo INTEGRATION_CUSTOM_PRESERVED PASS
restore
: >/etc/config/shadowsocksr
/usr/libexec/hkc-qwrt-defaults
[ "$(uci get 'shadowsocksr.@global[0].global_server')" = nil ]
[ "$(uci get 'shadowsocksr.@global[0].monitor_enable')" = 1 ]
[ "$(uci get 'shadowsocksr.@server_subscribe[0].proxy')" = 0 ]
echo INTEGRATION_EMPTY_DEFAULTS PASS
for scenario in board ports dns conflict uncommitted; do
 restore
 case "$scenario" in
  board) echo wrong,board >/tmp/sysinfo/board_name ;;
  ports) uci set network.wan.ifname=eth0; uci commit network ;;
  dns) uci set 'shadowsocksr.@global[0].pdnsd_enable=3'; uci commit shadowsocksr ;;
  conflict) uci set firewall.shadowsocksr=zone; uci commit firewall ;;
  uncommitted) uci set network.wan.proto=static ;;
 esac
 fingerprint >/tmp/before
 if /usr/libexec/hkc-qwrt-defaults >/tmp/rejection.log 2>&1; then echo "unexpected acceptance: $scenario";exit 1;fi
 fingerprint >/tmp/after
 cmp -s /tmp/before /tmp/after
 [ ! -e /etc/hkc-qwrt-defaults-v1 ]
 echo jdcloud,ax1800-pro >/tmp/sysinfo/board_name
 uci revert network
 echo "INTEGRATION_REJECT_$scenario PASS"
done
restore
cat >/tmp/shim/mv <<'EOF'
#!/bin/ash
if [ "$3" = /etc/config/firewall ] && [ ! -e /tmp/failure-injected ]; then touch /tmp/failure-injected;exit 1;fi
exec /bin/busybox mv "$@"
EOF
chmod 755 /tmp/shim/mv
fingerprint >/tmp/before
if PATH=/tmp/shim:$PATH /usr/libexec/hkc-qwrt-defaults >/tmp/rollback.log 2>&1; then exit 1;fi
[ -e /tmp/failure-injected ]
[ ! -e /etc/hkc-qwrt-defaults-v1 ]
fingerprint >/tmp/after
cmp -s /tmp/before /tmp/after
echo INTEGRATION_ROLLBACK PASS
rm /tmp/shim/mv
timeout 2 sh -c 'exit 0'
set +e
timeout 1 sleep 4
result=$?
set -e
[ "$result" = 124 ]
echo INTEGRATION_TIMEOUT PASS
(
 # rc.common does not run with errexit/nounset; assert the captured JSON below.
 set +eu
 service_triggers() { :; }
 service_data() { :; }
 . /lib/functions.sh
 initscript=/etc/init.d/hkc-stability
 . /lib/functions/procd.sh
 _procd_ubus_call() { json_dump >/tmp/procd-service.json; }
 . /etc/init.d/hkc-stability
 procd_open_service hkc-stability /etc/init.d/hkc-stability
 start_service
 procd_close_service
)
cat /tmp/procd-service.json
lua -e 'local j=require("luci.jsonc");local f=assert(io.open("/tmp/procd-service.json"));local x=assert(j.parse(f:read("*a"))); assert(x.name=="hkc-stability");local n=0;for _,v in pairs(x.instances) do n=n+1;assert(v.command[1]=="/usr/libexec/hkc-ssr-health" and v.command[2]=="daemon");assert(v.respawn[1]=="3600" and v.respawn[2]=="5" and v.respawn[3]=="0" and #v.respawn==3) end;assert(n==1)'
echo INTEGRATION_PROCD PASS
# Fake HTTPS response transport only: use the real QWRT date/flock/parser/retry code.
cat >/tmp/shim/curl <<'EOF'
#!/bin/ash
echo request >>/tmp/clock-requests
[ ! -e /tmp/clock-fail ] || exit 7
out=''
while [ "$#" -gt 0 ]; do
 if [ "$1" = -D ]; then shift;out="$1";fi
 shift
done
printf 'HTTP/1.1 200 OK\r\nDate: %s\r\nAge: 0\r\n\r\n' "$(date -u '+%a, %d %b %Y %H:%M:%S GMT')" >"$out"
printf 200
EOF
chmod 755 /tmp/shim/curl
PATH=/tmp/shim:$PATH /usr/libexec/hkc-time-sync sync
[ -s /var/run/hkc-time-valid ] && [ -s /var/run/hkc-clock-synced ]
[ "$(wc -l </tmp/clock-requests)" = 2 ]
PATH=/tmp/shim:$PATH /usr/libexec/hkc-time-sync sync
[ "$(wc -l </tmp/clock-requests)" = 2 ]
rm /var/run/hkc-clock-attempt-uptime /var/run/hkc-clock-verified-uptime
touch /tmp/clock-fail
if PATH=/tmp/shim:$PATH /usr/libexec/hkc-time-sync sync; then exit 1;fi
[ -e /var/run/hkc-clock-retry ] && [ ! -e /var/run/hkc-time-valid ]
echo INTEGRATION_CLOCK_FIXTURES PASS
# Check daemon wiring with no SSR intent/node. Mock only WAN and HTTPS transport.
rm -f /tmp/clock-fail /tmp/clock-requests /var/run/hkc-clock-attempt-uptime /var/run/hkc-clock-verified-uptime /var/run/hkc-ssr-intent
cat >/tmp/shim/ifstatus <<'EOF'
#!/bin/ash
if [ -e /tmp/wan-ready ]; then echo '{"up":true}';else echo '{"up":false}';fi
EOF
cat >/tmp/shim/ip <<'EOF'
#!/bin/ash
echo 'default via 192.0.2.254 dev eth3'
EOF
cat >/tmp/shim/sleep <<'EOF'
#!/bin/ash
exec /bin/busybox sleep 1
EOF
chmod 755 /tmp/shim/ifstatus /tmp/shim/ip /tmp/shim/sleep
set +e
PATH=/tmp/shim:$PATH timeout 2 /usr/libexec/hkc-ssr-health daemon
result=$?
set -e
[ "$result" = 124 ] && [ ! -e /tmp/clock-requests ]
touch /tmp/wan-ready
set +e
PATH=/tmp/shim:$PATH timeout 2 /usr/libexec/hkc-ssr-health daemon
result=$?
set -e
[ "$result" = 124 ] && [ -s /var/run/hkc-time-valid ]
[ "$(wc -l </tmp/clock-requests)" = 2 ]
[ ! -e /var/run/hkc-ssr-repair.last ]
echo INTEGRATION_DAEMON_NO_NODE PASS
echo INTEGRATION_ALL PASS
