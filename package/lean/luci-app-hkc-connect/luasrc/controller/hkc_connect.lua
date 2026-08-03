module("luci.controller.hkc_connect", package.seeall)

local http = require "luci.http"
local json = require "luci.jsonc"
local template = require "luci.template"
local model = require "luci.model.hkc_connect"

local SESSION_COOKIE = "hkc_session"
local CSRF_COOKIE = "hkc_csrf"

local function cookie(name)
	local raw = http.getenv("HTTP_COOKIE") or ""
	for part in raw:gmatch("[^;]+") do
		local key, value = part:match("^%s*([^=]+)=([^;]*)$")
		if key == name then return value end
	end
	return ""
end

local function set_cookie(name, value, http_only, max_age)
	local attributes = {
		name .. "=" .. tostring(value or ""),
		"Path=/cgi-bin/luci/hkc-connect",
		"SameSite=Strict",
		"Max-Age=" .. tostring(max_age or 0)
	}
	if http_only then attributes[#attributes + 1] = "HttpOnly" end
	http.header("Set-Cookie", table.concat(attributes, "; "))
end

local function response(payload, status)
	status = status or 200
	local reasons = { [200] = "OK", [400] = "Bad Request", [401] = "Unauthorized", [403] = "Forbidden", [405] = "Method Not Allowed", [409] = "Conflict", [429] = "Too Many Requests", [500] = "Internal Server Error", [502] = "Bad Gateway", [503] = "Service Unavailable" }
	http.status(status, reasons[status] or "Error")
	http.header("Cache-Control", "no-store, max-age=0")
	http.header("Pragma", "no-cache")
	http.prepare_content("application/json")
	http.write_json(payload)
end

local function fail(code, status)
	response({ ok = false, error = code or "request_failed" }, status or 400)
end

local function parse_body()
	local raw = http.content() or ""
	if #raw > 8192 then return nil end
	local ok, value = pcall(json.parse, raw)
	if not ok or type(value) ~= "table" then return nil end
	return value
end

local function csrf_valid()
	local from_cookie = cookie(CSRF_COOKIE)
	local from_header = http.getenv("HTTP_X_HKC_CSRF") or ""
	return from_cookie ~= "" and #from_cookie == #from_header and from_cookie == from_header
end

local function session_valid()
	return model.web_session_valid(cookie(SESSION_COOKIE))
end

local function require_post_auth()
	if http.getenv("REQUEST_METHOD") ~= "POST" then
		fail("method_not_allowed", 405)
		return false
	end
	if not session_valid() then
		fail("authentication_required", 401)
		return false
	end
	if not csrf_valid() then
		fail("csrf_failed", 403)
		return false
	end
	return true
end

function action_index()
	local token = model.new_csrf_token()
	if not token then
		http.status(503, "Service Unavailable")
		return
	end
	set_cookie(CSRF_COOKIE, token, false, 86400)
	http.header("Cache-Control", "no-store, max-age=0")
	http.header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
	http.header("X-Content-Type-Options", "nosniff")
	http.header("Referrer-Policy", "no-referrer")
	template.render("hkc_connect/index")
end

function api_bootstrap()
	if not session_valid() then
		response({ ok = true, data = { authenticated = false, bound = model.is_bound() } })
		return
	end
	response({ ok = true, data = { authenticated = true, data = model.status() } })
end

function api_login()
	if http.getenv("REQUEST_METHOD") ~= "POST" then return fail("method_not_allowed", 405) end
	if not csrf_valid() then return fail("csrf_failed", 403) end
	local body = parse_body()
	if not body then return fail("invalid_request", 400) end
	local account, err, status = model.login(body.email, body.password, body.mfaCode)
	if not account then return fail(err, status) end
	local session = model.create_web_session()
	if not session then return fail("session_store_failed", 500) end
	set_cookie(SESSION_COOKIE, session, true, 315360000)
	response({ ok = true, data = { account = account, sync = model.sync_status() } })
end

function api_status()
	if not session_valid() then return fail("authentication_required", 401) end
	response({ ok = true, data = model.status() })
end

function api_lines()
	if not session_valid() then return fail("authentication_required", 401) end
	response({ ok = true, data = model.list_nodes() })
end

function api_connect()
	if not require_post_auth() then return end
	local body = parse_body()
	if not body then return fail("invalid_request", 400) end
	local ok, err = model.connect(body.nodeId)
	if not ok then return fail(err, 409) end
	response({ ok = true, data = model.status() })
end

function api_disconnect()
	if not require_post_auth() then return end
	model.disconnect(true)
	response({ ok = true, data = model.status() })
end

function api_settings()
	if not session_valid() then return fail("authentication_required", 401) end
	response({ ok = true, data = model.settings() })
end

function api_update_settings()
	if not require_post_auth() then return end
	local body = parse_body()
	if not body then return fail("invalid_request", 400) end
	local settings, err = model.update_settings({
		auto_connect = body.autoConnect,
		domestic_protection = body.domesticProtection,
		auto_update = body.autoUpdate,
		update_hour = body.updateHour,
		update_minute = body.updateMinute
	})
	if not settings then return fail(err, 409) end
	response({ ok = true, data = settings })
end

function api_sync()
	if not require_post_auth() then return end
	local ok, err = model.start_sync()
	if not ok then return fail(err, 409) end
	response({ ok = true, data = model.sync_status() })
end

function api_sync_status()
	if not session_valid() then return fail("authentication_required", 401) end
	response({ ok = true, data = model.sync_status() })
end

function api_refresh_account()
	if not require_post_auth() then return end
	local account, err, status = model.refresh_account()
	if not account then return fail(err, status) end
	response({ ok = true, data = account })
end

function api_logout()
	if not require_post_auth() then return end
	model.logout()
	set_cookie(SESSION_COOKIE, "", true, 0)
	response({ ok = true })
end

function index()
	local root = entry({ "hkc-connect" }, call("action_index"), "HKC Connect", 1)
	root.sysauth = false
	root.leaf = false

	local api = entry({ "hkc-connect", "api" }, firstchild(), nil)
	api.sysauth = false
	api.leaf = false

	for path, handler in pairs({
		bootstrap = "api_bootstrap", login = "api_login", status = "api_status",
		lines = "api_lines", connect = "api_connect", disconnect = "api_disconnect",
		settings = "api_settings", ["settings/update"] = "api_update_settings",
		sync = "api_sync", ["sync/status"] = "api_sync_status",
		["account/refresh"] = "api_refresh_account", logout = "api_logout"
	}) do
		local segments = { "hkc-connect", "api" }
		for segment in path:gmatch("[^/]+") do segments[#segments + 1] = segment end
		local route = entry(segments, call(handler), nil)
		route.sysauth = false
		route.leaf = true
	end
end
