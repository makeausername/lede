-- Runs against a private staging directory, never the live UCI directory.
local dir = assert(arg[1], "staging directory required")
assert(dir:match("^/tmp/hkc%-qwrt%.[%w]+/stage$"), "invalid staging directory")
local c = require("uci").cursor(dir, dir .. "/.delta")
local function sections(package, kind)
    local result = {}
    c:foreach(package, kind, function(s) result[#result + 1] = s[".name"] end)
    return result
end
local function one(kind)
    local found = sections("shadowsocksr", kind)
    assert(#found <= 1, "ambiguous SSR section: " .. kind)
    return found[1] or assert(c:add("shadowsocksr", kind))
end
local function missing(section, option, value)
    if c:get("shadowsocksr", section, option) == nil then
        assert(c:set("shadowsocksr", section, option, value))
    end
end
-- Use the same isolated Lua cursor for all six packages. The vendor CLI
-- staging flags are not interchangeable with newer UCI versions.
assert(c:get("network", "lan", "type") == "bridge", "legacy LAN bridge required")
assert(c:get("network", "wan", "ifname") == "eth3", "unexpected WAN port")
local ports = {}
for name in (c:get("network", "lan", "ifname") or ""):gmatch("%S+") do
    assert(not ports[name], "duplicate LAN port"); ports[name] = true
end
assert(ports.eth0 and ports.eth1 and ports.eth2, "missing LAN port")
local count=0; for _ in pairs(ports) do count=count+1 end
assert(count==3, "unexpected LAN port")
assert(c:get("dhcp", "lan", "interface") == "lan", "unexpected LAN DHCP section")
local dns = assert(sections("dhcp", "dnsmasq")[1], "dnsmasq section required")
local rule = c:get("firewall", "hkc_lan_ipv4_only")
assert(rule == nil or rule == "rule", "conflicting IPv4-only rule")
assert(c:set("network", "lan", "ipv6", "0"))
if c:get("network", "lan", "ip6assign") then assert(c:delete("network", "lan", "ip6assign")) end
for k,v in pairs({ra="disabled",dhcpv6="disabled",ndp="disabled",ra_slaac="0"}) do assert(c:set("dhcp","lan",k,v)) end
assert(c:set("dhcp",dns,"filter_aaaa","1"))
if rule == nil then assert(c:set("firewall","hkc_lan_ipv4_only","rule")) end
for k,v in pairs({name="HKC LAN IPv4 only",src="lan",dest="wan",family="ipv6",proto="all",target="REJECT",enabled="1"}) do
    assert(c:set("firewall","hkc_lan_ipv4_only",k,v))
end
local global = one("global")
local interval = c:get("shadowsocksr", global, "switch_time")
if interval == nil or interval == "667" then
    assert(c:set("shadowsocksr", global, "switch_time", "30"))
end
missing(global, "monitor_enable", "1")
missing(global, "component_mirror", "direct")
-- Legacy DNS mode changes need a separate compatibility decision, not a silent rewrite.
local mode = c:get("shadowsocksr", global, "pdnsd_enable")
assert(mode ~= "2" and mode ~= "3", "legacy SSR DNS mode requires explicit migration")
missing(global, "filter_aaaa", c:get("shadowsocksr", global, "mosdns_ipv6") or "1")
local sub = one("server_subscribe")
local old_hour = c:get("shadowsocksr", sub, "auto_update_time")
if old_hour ~= nil then
    assert(old_hour:match("^%d+$") and tonumber(old_hour) <= 23, "invalid legacy update hour")
end
missing(sub, "auto_update_week_time", "*")
missing(sub, "auto_update_day_time", old_hour or "2")
missing(sub, "auto_update_min_time", "0")
missing(sub, "proxy", "0")
missing(sub, "config_auto_update_mode", "0")
missing(sub, "config_update_interval", "60")
missing(sub, "user_agent", "v2rayN/9.99")
local fragment = one("global_xray_fragment")
missing(fragment, "fragment", "0")
missing(fragment, "noise", "0")
-- Keep existing nodes, types, DNS choice, schedules and explicit user settings.
local kind = c:get("firewall", "shadowsocksr")
assert(kind == nil or kind == "include", "conflicting SSR firewall section")
local path = c:get("firewall", "shadowsocksr", "path")
assert(path == nil or path == "/var/etc/shadowsocksr.include", "conflicting SSR firewall path")
if kind == nil then assert(c:set("firewall", "shadowsocksr", "include")) end
for k, v in pairs({type="script", path="/var/etc/shadowsocksr.include", reload="1"}) do
    assert(c:set("firewall", "shadowsocksr", k, v))
end
local track = sections("ucitrack", "shadowsocksr")
assert(#track <= 1, "ambiguous SSR ucitrack section")
local name = track[1] or assert(c:add("ucitrack", "shadowsocksr"))
local init = c:get("ucitrack", name, "init")
assert(init == nil or init == "shadowsocksr", "conflicting SSR ucitrack handler")
assert(c:set("ucitrack", name, "init", "shadowsocksr"))
-- The zzz_hkc-qwrt wrapper sorts after all vendor defaults. Register
-- Argon after vendor themes and apply LAN policy after odhcpd.defaults.
assert(c:get("luci", "main") == "core", "LuCI main section required")
local themes=c:get("luci", "themes")
assert(themes == nil or themes == "internal", "conflicting LuCI themes section")
if themes == nil then assert(c:set("luci", "themes", "internal")) end
assert(c:set("luci", "themes", "Argon", "/luci-static/argon"))
assert(c:set("luci", "main", "mediaurlbase", "/luci-static/argon"))
for _, package in ipairs({"network", "dhcp", "shadowsocksr", "firewall", "ucitrack", "luci"}) do
    assert(c:save(package)); assert(c:commit(package))
end
