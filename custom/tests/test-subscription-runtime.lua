local runtime = require "luci.model.shadowsocksr.subscription_runtime"

local Cursor = {}
Cursor.__index = Cursor

function Cursor.new(sections)
	return setmetatable({ sections = sections or {} }, Cursor)
end

function Cursor:find(sid)
	for _, section in ipairs(self.sections) do
		if section[".name"] == sid then
			return section
		end
	end
end

function Cursor:get(config, sid, option)
	assert(config == "shadowsocksr")
	local section = self:find(sid)
	if not section then
		return nil
	end
	if option == nil then
		return section[".type"]
	end
	return section[option]
end

function Cursor:get_first(config, section_type, option, default)
	assert(config == "shadowsocksr")
	for _, section in ipairs(self.sections) do
		if section[".type"] == section_type then
			if option == nil then
				return section[".name"]
			end
			return section[option] or default
		end
	end
	return default
end

function Cursor:set(config, sid, option, value)
	assert(config == "shadowsocksr")
	local section = assert(self:find(sid), "missing section " .. sid)
	section[option] = value
end

local function global_with(value)
	return {
		[".name"] = "global",
		[".type"] = "global",
		global_server = value
	}
end

local function server(name)
	return {
		[".name"] = name,
		[".type"] = "servers",
		type = "v2ray",
		v2ray_protocol = "vless"
	}
end

local first = Cursor.new({ global_with("nil"), server("node_a") })
local selected, changed, reason = runtime.ensure_main_server(first)
assert(selected == nil and not changed and reason == "disabled")
assert(first:get("shadowsocksr", "global", "global_server") == "nil")

selected, changed, reason = runtime.ensure_main_server(first)
assert(selected == nil and not changed and reason == "disabled")

local preserved = Cursor.new({ global_with("node_b"), server("node_a"), server("node_b") })
selected, changed, reason = runtime.ensure_main_server(preserved)
assert(selected == "node_b" and not changed and reason == "preserved")

local stale = Cursor.new({ global_with("removed_node"), server("replacement") })
selected, changed, reason = runtime.ensure_main_server(stale)
assert(selected == nil and changed and reason == "disabled-missing")
assert(stale:get("shadowsocksr", "global", "global_server") == "nil")

local empty = Cursor.new({ global_with("removed_node") })
selected, changed, reason = runtime.ensure_main_server(empty)
assert(selected == nil and changed and reason == "disabled-missing")
assert(empty:get("shadowsocksr", "global", "global_server") == "nil")

local no_global = Cursor.new({ server("node_a") })
selected, changed, reason = runtime.ensure_main_server(no_global)
assert(selected == nil and not changed and reason == "missing-global")

print("subscription runtime selection tests passed")
