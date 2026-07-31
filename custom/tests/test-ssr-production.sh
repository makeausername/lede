#!/bin/sh
set -eu

root="${1:?usage: test-ssr-production.sh <luci-app-ssr-plus-root>}"
servers="$root/luasrc/model/cbi/shadowsocksr/servers.lua"
status="$root/luasrc/model/cbi/shadowsocksr/status.lua"
controller="$root/luasrc/controller/shadowsocksr.lua"
storage="$root/luasrc/model/shadowsocksr/subscription_storage.lua"
init="$root/root/etc/init.d/shadowsocksr"
monitor="$root/root/usr/bin/ssr-monitor"
generator="$root/root/usr/share/shadowsocksr/gen_config.lua"
subscribe="$root/root/usr/share/shadowsocksr/subscribe.lua"

require_text() {
	needle="$1"
	file="$2"
	grep -Fq "$needle" "$file" || {
		echo "missing required production guard in $file: $needle" >&2
		exit 1
	}
}

reject_text() {
	needle="$1"
	file="$2"
	if grep -Fq "$needle" "$file"; then
		echo "forbidden regression remains in $file: $needle" >&2
		exit 1
	fi
}

test -s "$storage"
require_text 'local subscription_storage = require "luci.model.shadowsocksr.subscription_storage"' "$servers"
require_text 'Value, "_classic_subscribe_url"' "$servers"
require_text 'subscription_storage.get(self.map.uci)' "$servers"
require_text 'subscription_storage.replace(self.map.uci, value)' "$servers"
require_text 'subscription_storage.clear(self.map.uci)' "$servers"
reject_text 'DynamicList, "_classic_subscribe_urls"' "$servers"
reject_text 'classic_subscribe_commit' "$servers"
reject_text 'TypedSection, "server_subscribe_item"' "$servers"
require_text 'function M.replace(cursor, value)' "$storage"
require_text 'function M.clear(cursor)' "$storage"
require_text 'cursor:set(CONFIG, sid, "url", url)' "$storage"

require_text 'local code="$3"' "$init"
reject_text 'local mode="$3"' "$init"
require_text 'gen_config.lua "$server" "$mode"' "$init"
require_text 'Xray TCP uses REDIRECT while UDP uses TPROXY' "$init"
require_text 'run -test -c "$udp_config_file"' "$init"
require_text 'start_udp || return 1' "$init"
require_text 'main_proxy_runtime_healthy' "$init"
require_text 'busybox netstat -lnt' "$init"

test "$(grep -Fc 'tproxy = (proto == "udp") and "tproxy" or "redirect"' "$generator")" -ge 2
require_text 'tcp_listener_running' "$monitor"
require_text 'proxy_path_healthy' "$monitor"
require_text 'PROXY_HEALTH_CHECK_EVERY=4' "$monitor"
require_text 'transparent proxy data path is unavailable' "$monitor"
require_text 'global_tcp_listener_running' "$status"
require_text 'default_tcp_listener_running' "$controller"

require_text 'local function write_new_md5(groupHash, content_md5, url)' "$subscribe"
require_text 'md5 = content_md5' "$subscribe"
require_text 'url_hash = md5(url)' "$subscribe"
reject_text 'local function write_new_md5(groupHash, md5, url)' "$subscribe"
require_text 'nixio.fs.chmod(path, 600)' "$subscribe"
reject_text 'nixio.fs.chmod(path, 384)' "$subscribe"
require_text 'local config_snapshot = nixio.fs.readfile(config_path)' "$subscribe"
require_text 'local service_was_running = luci.sys.call(' "$subscribe"
require_text 'ucic:revert(name)' "$subscribe"
require_text 'nixio.fs.writefile(config_path, config_snapshot)' "$subscribe"
require_text 'if service_was_running then' "$subscribe"
require_text 'Restored the proxy service that was running before the update' "$subscribe"
require_text 'local subscription_label = "subscription["' "$subscribe"
reject_text 'log("处理订阅: " .. url)' "$subscribe"
reject_text 'log("使用订阅转换模板: " .. template_url)' "$subscribe"
reject_text 'log("转换服务: " .. convert_address)' "$subscribe"

if grep -Eq 'chatgpt\.com|claude\.ai' "$init" "$monitor"; then
	echo "external AI sites must not be hard service-health dependencies" >&2
	exit 1
fi

sh -n "$init"
sh -n "$monitor"
