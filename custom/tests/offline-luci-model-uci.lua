-- The extracted firmware root used by CI has no ubus/rpcd daemon, so LuCI's
-- normal UCI cursor cannot connect. Wrap the target's native libuci-lua cursor
-- with the small get_first() compatibility method used by LuCI. All remaining
-- methods are delegated to the real ARM64 cursor unchanged.
local native_uci = require "uci"

local M = {}

local function wrap(raw)
	local proxy = {}

	function proxy:get_first(config, section_type, option, default)
		local first
		raw:foreach(config, section_type, function(section)
			if not first then
				first = section[".name"]
			end
			return false
		end)

		if not first then
			return default
		end
		if option == nil then
			return first
		end

		local value = raw:get(config, first, option)
		if value == nil then
			return default
		end
		return value
	end

	function proxy:section(config, section_type, name, values)
		local sid = name
		if sid then
			raw:set(config, sid, section_type)
		else
			sid = raw:add(config, section_type)
		end
		if not sid then
			return nil
		end
		for option, value in pairs(values or {}) do
			raw:set(config, sid, option, value)
		end
		return sid
	end

	return setmetatable(proxy, {
		__index = function(_, key)
			local value = raw[key]
			if type(value) ~= "function" then
				return value
			end
			return function(_, ...)
				return value(raw, ...)
			end
		end
	})
end

function M.cursor(...)
	return wrap(native_uci.cursor(...))
end

return M
