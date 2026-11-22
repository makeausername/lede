#!/bin/ash
ifconfig lo up
for proto in tcp udp tcp,udp; do
  ssr-local -c "/tmp/config-$proto.json" -v >/tmp/ssr-run.log 2>&1 &
  pid=$!
  sleep 1
  if kill -0 "$pid" 2>/dev/null; then echo SSR_CONFIG_LISTENER "$proto" PASS;kill "$pid";wait "$pid" 2>/dev/null;else wait "$pid";echo SSR_CONFIG_LISTENER "$proto" FAIL "$?";fi
  head -12 /tmp/ssr-run.log
done
uci set shadowsocksr.reality=servers
uci set shadowsocksr.reality.type=v2ray
uci set shadowsocksr.reality.v2ray_protocol=vless
uci set shadowsocksr.reality.server=192.0.2.1
uci set shadowsocksr.reality.server_port=443
uci set shadowsocksr.reality.vmess_id=00000000-0000-4000-8000-000000000001
uci set shadowsocksr.reality.transport=tcp
uci set shadowsocksr.reality.reality=1
uci set shadowsocksr.reality.reality_publickey=hSDwCYkwp1R0i33ctD73Wg2_Og0mOBr066SpjqqbTmo
uci set shadowsocksr.reality.reality_shortid=0123456789abcdef
uci set shadowsocksr.reality.tls_host=example.invalid
uci set shadowsocksr.reality.fingerprint=chrome
uci set shadowsocksr.reality.tls_flow=xtls-rprx-vision
uci commit shadowsocksr
lua /usr/share/shadowsocksr/gen_config.lua reality tcp 1234 0 0 >/tmp/reality.json
echo REALITY_GENERATED $?
xray run -test -config /tmp/reality.json >/tmp/xray-test.log 2>&1
echo REALITY_CORE_TEST $?
head -15 /tmp/xray-test.log
