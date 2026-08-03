local fs = require("nixio.fs")
local config_dir = "/etc/config"

package.loaded["luci.sys"] = {
	hostname = function() return "HKC" end,
	exec = function() return "" end,
	call = function(command)
		if command:match("^cp %-f /etc/config/shadowsocksr ") then
			fs.mkdirr("/tmp/hkc-connect")
			return fs.writefile("/tmp/hkc-connect/shadowsocksr.before-connect", fs.readfile(config_dir .. "/shadowsocksr")) and 0 or 1
		end
		if command:match("^cp %-f /tmp/hkc%-connect/shadowsocksr%.before%-connect /etc/config/shadowsocksr") then
			return fs.writefile(config_dir .. "/shadowsocksr", fs.readfile("/tmp/hkc-connect/shadowsocksr.before-connect")) and 0 or 1
		end
		if command:match("shadowsocksr running") then return _G.hkc_running and 0 or 1 end
		if command:match("shadowsocksr restart") or command:match("hkc%-connect%-schedule") or command:match("shadowsocksr failopen") then return 0 end
		return 0
	end
}

local uci = require("uci")
package.loaded["luci.model.uci"] = { cursor = function() return uci.cursor(config_dir) end }
local model = require("luci.model.hkc_connect")
local cursor = uci.cursor(config_dir)

cursor:set("shadowsocksr", "hkc_test_node", "servers")
cursor:set("shadowsocksr", "hkc_test_node", "alias", "Synthetic line")
cursor:set("shadowsocksr", "hkc_test_node", "type", "v2ray")
cursor:set("shadowsocksr", "hkc_test_node", "v2ray_protocol", "vless")
cursor:set("shadowsocksr", "hkc_test_node", "server", "192.0.2.1")
cursor:set("shadowsocksr", "hkc_test_node", "server_port", "443")
cursor:commit("shadowsocksr")

local nodes = model.list_nodes()
local found
for _, node in ipairs(nodes) do
	if node.id == "hkc_test_node" then found = node end
	assert(node.server == nil and node.server_port == nil and node.password == nil, "node secret leaked")
end
assert(found and found.name == "Synthetic line" and found.protocol == "VLESS")

_G.hkc_running = true
local ok, err = model.connect("hkc_test_node")
assert(ok, err)
cursor = uci.cursor(config_dir)
assert(cursor:get_first("shadowsocksr", "global", "global_server") == "hkc_test_node")
assert(cursor:get("hkc_connect", "main", "last_server") == "hkc_test_node")

cursor:set("shadowsocksr", "hkc_bad_node", "servers")
cursor:set("shadowsocksr", "hkc_bad_node", "alias", "Rollback line")
cursor:set("shadowsocksr", "hkc_bad_node", "type", "v2ray")
cursor:commit("shadowsocksr")
_G.hkc_running = false
local failed, failure = model.connect("hkc_bad_node")
assert(not failed and failure == "runtime_validation_failed")
cursor = uci.cursor(config_dir)
assert(cursor:get_first("shadowsocksr", "global", "global_server") == "hkc_test_node", "failed connect did not roll back")

local old_monitor = cursor:get_first("shadowsocksr", "global", "monitor_enable", "1")
local failed_settings, settings_failure = model.update_settings({
	auto_connect = true,
	domestic_protection = old_monitor ~= "1",
	auto_update = true,
	update_hour = 5,
	update_minute = 0
})
assert(not failed_settings and settings_failure == "runtime_validation_failed")
cursor = uci.cursor(config_dir)
assert(cursor:get_first("shadowsocksr", "global", "monitor_enable", "1") == old_monitor,
	"failed settings restart did not restore SSR monitor policy")
assert(cursor:get("hkc_connect", "main", "domestic_protection") == old_monitor,
	"failed settings restart did not restore HKC Connect policy")

fs.writefile("/var/run/ssrplus.fail-open", "1\n")
local protected_status = model.status()
assert(protected_status.running == false and protected_status.connectionState == "protected",
	"fail-open state is not reported truthfully")
fs.remove("/var/run/ssrplus.fail-open")

local public = model.public_account({ user = { email = "person@example.com", name = "Person" }, usage = {} })
assert(public.email == "p***@example.com")
assert(public.access_token == nil and public.subscription == nil)

local settings = model.settings()
assert(settings.gameUdp == true and settings.gameUdpManaged == true)
assert(settings.subscription == nil and settings.accessToken == nil)

print("HKC Connect ARM64 model checks passed")
