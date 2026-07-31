local storage = require "luci.model.shadowsocksr.subscription_storage"

local Cursor = {}
Cursor.__index = Cursor

function Cursor.new(sections)
	return setmetatable({ sections = sections or {}, next_id = 1 }, Cursor)
end

function Cursor:foreach(config, section_type, callback)
	assert(config == "shadowsocksr")
	for _, item in ipairs(self.sections) do
		if item[".type"] == section_type then
			callback(item)
		end
	end
end

function Cursor:add(config, section_type)
	assert(config == "shadowsocksr")
	local sid = "generated_" .. self.next_id
	self.next_id = self.next_id + 1
	self.sections[#self.sections + 1] = {
		[".name"] = sid,
		[".type"] = section_type
	}
	return sid
end

function Cursor:find(sid)
	for _, item in ipairs(self.sections) do
		if item[".name"] == sid then
			return item
		end
	end
end

function Cursor:set(config, sid, option, value)
	assert(config == "shadowsocksr")
	local item = assert(self:find(sid), "missing section " .. sid)
	item[option] = value
end

function Cursor:get(config, sid, option)
	assert(config == "shadowsocksr")
	local item = self:find(sid)
	return item and item[option]
end

function Cursor:delete(config, sid)
	assert(config == "shadowsocksr")
	for index, item in ipairs(self.sections) do
		if item[".name"] == sid then
			table.remove(self.sections, index)
			return true
		end
	end
	return false
end

local cursor = Cursor.new({
	{
		[".name"] = "disabled",
		[".type"] = "server_subscribe_item",
		enabled = "0",
		url = "https://disabled.invalid/subscription"
	},
	{
		[".name"] = "active",
		[".type"] = "server_subscribe_item",
		enabled = "1",
		alias = "Primary",
		url = "https://old.invalid/subscription"
	}
})

assert(storage.get(cursor) == "https://old.invalid/subscription")
local sid = storage.replace(cursor, "  https://subscription.invalid/token  ")
assert(sid == "disabled")
assert(#storage.collect_ids(cursor) == 1)
assert(storage.get(cursor) == "https://subscription.invalid/token")
assert(cursor:get("shadowsocksr", sid, "enabled") == "1")
assert(cursor:get("shadowsocksr", sid, "alias") == "Subscribe 1")

storage.replace(cursor, "https://subscription.invalid/token")
assert(#storage.collect_ids(cursor) == 1)

storage.clear(cursor)
assert(#storage.collect_ids(cursor) == 0)
assert(storage.get(cursor) == "")

local created = storage.replace(cursor, "https://new.invalid/subscription")
assert(created == "generated_1")
assert(storage.get(cursor) == "https://new.invalid/subscription")

storage.replace(cursor, "   ")
assert(#storage.collect_ids(cursor) == 0)

print("subscription storage tests passed")
