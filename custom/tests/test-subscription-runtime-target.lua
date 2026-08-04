-- The extracted firmware root is intentionally offline and has no ubus/rpcd
-- daemon. Use a LuCI-compatible wrapper around the target's native libuci-lua
-- cursor so this still exercises the real ARM64 implementation and on-image
-- configuration without pretending that the native cursor has get_first().
local offline_uci = dofile("/tmp/offline-luci-model-uci.lua")
package.loaded["luci.model.uci"] = offline_uci
local uci = offline_uci.cursor()
local runtime = require "luci.model.shadowsocksr.subscription_runtime"

local config = "shadowsocksr"
local global_sid = assert(uci:get_first(config, "global"), "missing global section")
local test_sid = "hkc_runtime_selection"

uci:delete(config, test_sid)
assert(uci:section(config, "servers", test_sid, {
	type = "v2ray",
	v2ray_protocol = "vless",
	alias = "Runtime selection test"
}))
uci:set(config, global_sid, "global_server", "nil")
uci:commit(config)

local selected, changed, reason = runtime.ensure_main_server(uci)
assert(selected == nil, "disabled main server was unexpectedly selected")
assert(not changed and reason == "disabled")
uci:commit(config)
assert(uci:get(config, global_sid, "global_server") == "nil")

uci:set(config, global_sid, "global_server", test_sid)
selected, changed, reason = runtime.ensure_main_server(uci)
assert(selected == test_sid and not changed and reason == "preserved")

uci:set(config, global_sid, "global_server", "removed_runtime_node")
selected, changed, reason = runtime.ensure_main_server(uci)
assert(selected == nil and changed and reason == "disabled-missing")
assert(uci:get(config, global_sid, "global_server") == "nil")

uci:set(config, global_sid, "global_server", "removed_runtime_node")
uci:delete(config, test_sid)
selected, changed, reason = runtime.ensure_main_server(uci)
assert(selected == nil and changed and reason == "disabled-missing")
uci:commit(config)
assert(uci:get(config, global_sid, "global_server") == "nil")

print("target UCI subscription runtime selection tests passed")
