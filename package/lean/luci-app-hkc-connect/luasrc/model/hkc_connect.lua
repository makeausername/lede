local M = {}

local fs = require "nixio.fs"
local nixio = require "nixio"
local json = require "luci.jsonc"
local sys = require "luci.sys"
local util = require "luci.util"
local uci_model = require "luci.model.uci"

local CONFIG = "hkc_connect"
local SECTION = "main"
local SSR_CONFIG = "shadowsocksr"
local STATE_DIR = "/etc/hkc-connect"
local SESSION_FILE = STATE_DIR .. "/panel-session.json"
local WEB_SESSION_FILE = STATE_DIR .. "/web-session"
local RUNTIME_DIR = "/tmp/hkc-connect"
local SYNC_STATUS_FILE = RUNTIME_DIR .. "/sync-status.json"
local SSR_BACKUP_FILE = RUNTIME_DIR .. "/shadowsocksr.before-connect"

local function trim(value)
	if type(value) ~= "string" then
		return ""
	end
	return (value:gsub("^%s*(.-)%s*$", "%1"))
end

local function ensure_dir(path)
	fs.mkdirr(path)
	fs.chmod(path, 700)
end

local function random_token()
	local handle = io.open("/dev/urandom", "rb")
	if not handle then
		return nil
	end
	local raw = handle:read(32)
	handle:close()
	if not raw or #raw ~= 32 then
		return nil
	end
	return nixio.bin.hexlify(raw)
end

local function read_json(path)
	local raw = fs.readfile(path)
	if not raw or raw == "" then
		return nil
	end
	local ok, value = pcall(json.parse, raw)
	if not ok or type(value) ~= "table" then
		return nil
	end
	return value
end

local function write_private(path, value)
	ensure_dir(STATE_DIR)
	local suffix = random_token()
	if not suffix then
		return false
	end
	local temp = path .. ".tmp." .. suffix:sub(1, 12)
	if not fs.writefile(temp, value) then
		return false
	end
	fs.chmod(temp, 600)
	if not os.rename(temp, path) then
		fs.remove(temp)
		return false
	end
	fs.chmod(path, 600)
	return true
end

local function write_private_json(path, value)
	local ok, encoded = pcall(json.stringify, value)
	if not ok or type(encoded) ~= "string" then
		return false
	end
	return write_private(path, encoded)
end

local function config_cursor()
	return uci_model.cursor()
end

local function get_main(cursor, option, default)
	return cursor:get(CONFIG, SECTION, option) or default
end

local function normalize_flag(value, default)
	if value == "1" or value == 1 or value == true then
		return "1"
	end
	if value == "0" or value == 0 or value == false then
		return "0"
	end
	return default or "0"
end

local function panel_url()
	local cursor = config_cursor()
	local value = trim(get_main(cursor, "panel_url", "https://eziplc.com")):gsub("/+$", "")
	if not value:match("^https://[%w%.%-]+[:%d]*/?.*$") or value:find("%s") then
		return nil
	end
	return value
end

local function form_encode(payload)
	local function encode(value)
		return (tostring(value or ""):gsub("([^%w%-_%.~])", function(char)
			return string.format("%%%02X", string.byte(char))
		end))
	end
	local fields = {}
	for key, value in pairs(payload or {}) do
		fields[#fields + 1] = encode(key) .. "=" .. encode(value)
	end
	table.sort(fields)
	return table.concat(fields, "&")
end

local function curl_json(path, method, payload, bearer, body_format)
	local base = panel_url()
	if not base then
		return nil, "invalid_panel_url", 500
	end

	ensure_dir(RUNTIME_DIR)
	local nonce = random_token()
	if not nonce then
		return nil, "random_unavailable", 500
	end
	local request_file = RUNTIME_DIR .. "/request-" .. nonce:sub(1, 12) .. ".body"
	local response_file = RUNTIME_DIR .. "/response-" .. nonce:sub(1, 12) .. ".json"
	local auth_file = RUNTIME_DIR .. "/auth-" .. nonce:sub(1, 12) .. ".txt"
	local has_body = method ~= "GET" and method ~= "HEAD"
	if has_body then
		local encoded
		if body_format == "form" then
			encoded = form_encode(payload)
		else
			local ok
			ok, encoded = pcall(json.stringify, payload or {})
			if not ok then encoded = nil end
		end
		if type(encoded) ~= "string" or not fs.writefile(request_file, encoded) then
			return nil, "request_encode_failed", 500
		end
		if not fs.chmod(request_file, 600) then
			fs.remove(request_file)
			return nil, "request_permissions_failed", 500
		end
	end

	local auth = ""
	if bearer and bearer ~= "" then
		if not fs.writefile(auth_file, "Authorization: Bearer " .. bearer .. "\n") then
			if has_body then fs.remove(request_file) end
			return nil, "auth_header_failed", 500
		end
		if not fs.chmod(auth_file, 600) then
			fs.remove(auth_file)
			if has_body then fs.remove(request_file) end
			return nil, "auth_permissions_failed", 500
		end
		auth = " --header @" .. util.shellquote(auth_file)
	end
	local body_argument = has_body and ("--data-binary @" .. util.shellquote(request_file)) or ""
	local content_type = body_format == "form"
		and "application/x-www-form-urlencoded"
		or "application/json"
	local command = table.concat({
		"curl --silent --show-error --location --max-redirs 2",
		"--proto '=https' --proto-redir '=https' --tlsv1.2",
		"--connect-timeout 10 --max-time 25",
		"--request", util.shellquote(method or "GET"),
		"-H 'Accept: application/json' -H " .. util.shellquote("Content-Type: " .. content_type),
		auth,
		body_argument,
		"--output " .. util.shellquote(response_file),
		"--write-out '%{http_code}'",
		util.shellquote(base .. path),
		"2>/dev/null"
	}, " ")

	local status = tonumber(trim(sys.exec(command))) or 0
	if has_body then
		fs.remove(request_file)
	end
	fs.remove(auth_file)
	local response = read_json(response_file)
	fs.remove(response_file)

	if type(response) ~= "table" then
		return nil, "invalid_panel_response", status > 0 and status or 502
	end
	if status < 200 or status >= 300 or tonumber(response.ret or 0) ~= 1 then
		return nil, tostring(response.code or response.msg or "panel_request_failed"), status > 0 and status or 502
	end
	if type(response.data) ~= "table" then
		return nil, "missing_panel_data", 502
	end
	return response.data, nil, status
end

local function mask_email(email)
	email = trim(email)
	local local_part, domain = email:match("^([^@]+)@(.+)$")
	if not local_part or not domain then
		return ""
	end
	local first = local_part:sub(1, 1)
	return first .. "***@" .. domain
end

local function subscription_url()
	local ok, storage = pcall(require, "luci.model.shadowsocksr.subscription_storage")
	if not ok or not storage then
		return ""
	end
	return trim(storage.get(config_cursor()))
end

local function install_subscription(url)
	url = trim(url)
	if not url:match("^https://[^%s]+$") then
		return false, "invalid_subscription_url"
	end
	local ok, storage = pcall(require, "luci.model.shadowsocksr.subscription_storage")
	if not ok or not storage then
		return false, "subscription_storage_unavailable"
	end
	local cursor = config_cursor()
	if not storage.replace(cursor, url) then
		return false, "subscription_store_failed"
	end
	if not cursor:commit(SSR_CONFIG) then
		return false, "subscription_commit_failed"
	end
	return true
end

function M.new_csrf_token()
	return random_token()
end

function M.create_web_session()
	local token = random_token()
	if not token or not write_private(WEB_SESSION_FILE, token) then
		return nil
	end
	return token
end

function M.web_session_valid(token)
	token = trim(token)
	local expected = trim(fs.readfile(WEB_SESSION_FILE) or "")
	return token ~= "" and expected ~= "" and #token == #expected and token == expected
end

function M.clear_web_session()
	fs.remove(WEB_SESSION_FILE)
end

function M.is_bound()
	return subscription_url() ~= ""
end

function M.login(email, password, mfa_code)
	email = trim(email):lower()
	password = tostring(password or "")
	mfa_code = trim(mfa_code)
	if email == "" or #email > 254 or password == "" or #password > 256 then
		return nil, "credentials_required", 400
	end
	if mfa_code ~= "" and not mfa_code:match("^%d%d%d%d%d%d%d?%d?$") then
		return nil, "invalid_mfa_code", 400
	end

	local data, err, status = curl_json("/client/api/v1/login", "POST", {
		email = email,
		password = password,
		mfa_code = mfa_code,
		device_name = "HKC-router"
	}, nil, "form")
	password = nil
	if not data then
		return nil, err, status
	end

	local token = trim(data.accessToken)
	local subscription = type(data.subscription) == "table" and trim(data.subscription.url) or ""
	if token == "" or subscription == "" then
		return nil, "incomplete_panel_session", 502
	end
	if type(data.usage) == "table" and data.usage.canConnect == false then
		return nil, "account_cannot_connect", 403
	end

	local previous_subscription = subscription_url()
	local installed, install_err = install_subscription(subscription)
	if not installed then
		return nil, install_err, 500
	end

	local state = {
		access_token = token,
		expires_at = tonumber(data.accessTokenExpiresAt or 0) or 0,
		user = {
			email = type(data.user) == "table" and tostring(data.user.email or "") or "",
			name = type(data.user) == "table" and tostring(data.user.userName or "") or ""
		},
		usage = type(data.usage) == "table" and data.usage or {},
		bound_at = os.time(),
		last_panel_sync = os.time()
	}
	if not write_private_json(SESSION_FILE, state) then
		local restored = config_cursor()
		local ok, storage = pcall(require, "luci.model.shadowsocksr.subscription_storage")
		if ok and storage then
			if previous_subscription ~= "" then
				storage.replace(restored, previous_subscription)
			else
				storage.clear(restored)
			end
			restored:commit(SSR_CONFIG)
		end
		return nil, "session_store_failed", 500
	end

	M.start_sync()
	return M.public_account(state), nil, 200
end

function M.public_account(state)
	state = state or read_json(SESSION_FILE) or {}
	local user = type(state.user) == "table" and state.user or {}
	local usage = type(state.usage) == "table" and state.usage or {}
	return {
		bound = M.is_bound(),
		email = mask_email(user.email or ""),
		name = tostring(user.name or ""),
		usage = {
			todayUsed = tonumber(usage.todayUsed or 0) or 0,
			used = tonumber(usage.used or 0) or 0,
			total = tonumber(usage.total or 0) or 0,
			remaining = tonumber(usage.remaining or 0) or 0,
			isUnlimited = usage.isUnlimited == true,
			expireAt = tostring(usage.expireAt or ""),
			canConnect = usage.canConnect ~= false
		}
	}
end

function M.refresh_account()
	local state = read_json(SESSION_FILE)
	if not state or trim(state.access_token) == "" then
		return nil, "missing_panel_session", 401
	end
	local data, err, status = curl_json("/client/api/v1/me", "GET", {}, state.access_token)
	if not data then
		return nil, err, status
	end
	state.user = type(data.user) == "table" and data.user or state.user
	state.usage = type(data.usage) == "table" and data.usage or state.usage
	state.last_panel_sync = os.time()
	write_private_json(SESSION_FILE, state)
	return M.public_account(state), nil, 200
end

function M.list_nodes()
	local cursor = config_cursor()
	local selected = cursor:get_first(SSR_CONFIG, "global", "global_server", "nil")
	local nodes = {}
	cursor:foreach(SSR_CONFIG, "servers", function(node)
		local sid = tostring(node[".name"] or "")
		local alias = trim(node.alias)
		if alias == "" then
			alias = "线路 " .. tostring(#nodes + 1)
		end
		local protocol = trim(node.v2ray_protocol)
		if protocol == "" then
			protocol = trim(node.type):upper()
		else
			protocol = protocol:upper()
		end
		nodes[#nodes + 1] = {
			id = sid,
			name = alias,
			protocol = protocol,
			selected = sid == selected
		}
	end)
	table.sort(nodes, function(a, b)
		return tostring(a.name) < tostring(b.name)
	end)
	return nodes
end

local function selected_node(cursor)
	local sid = cursor:get_first(SSR_CONFIG, "global", "global_server", "nil")
	if sid == "nil" or cursor:get(SSR_CONFIG, sid) ~= "servers" then
		return nil
	end
	return {
		id = sid,
		name = trim(cursor:get(SSR_CONFIG, sid, "alias")) ~= "" and trim(cursor:get(SSR_CONFIG, sid, "alias")) or "当前线路",
		protocol = (trim(cursor:get(SSR_CONFIG, sid, "v2ray_protocol")) ~= "" and trim(cursor:get(SSR_CONFIG, sid, "v2ray_protocol")) or trim(cursor:get(SSR_CONFIG, sid, "type"))):upper()
	}
end

local function selected_runtime_healthy()
	local cursor = config_cursor()
	local sid = cursor:get_first(SSR_CONFIG, "global", "global_server", "nil")
	if sid == "nil" or cursor:get(SSR_CONFIG, sid) ~= "servers" then
		return false
	end

	local node_type = trim(cursor:get(SSR_CONFIG, sid, "type"))
	if node_type == "v2ray" then
		local port = tostring(cursor:get_first(SSR_CONFIG, "global", "default_node_local_port", "1234"))
		if not port:match("^%d+$") then
			return false
		end
		if sys.call("pidof xray >/dev/null 2>&1") ~= 0 then
			return false
		end
		local listener = "busybox netstat -lnt 2>/dev/null | awk " ..
			util.shellquote('$6 == "LISTEN" && $4 ~ /:' .. port .. '$/ { found=1 } END { exit !found }')
		return sys.call(listener) == 0
	end

	return sys.call("ps w 2>/dev/null | grep -E '[s]sr-retcp|[s]s-redir|[s]sr-redir|[i]pt2socks|[m]ihomo|[t]uic-client' >/dev/null 2>&1") == 0
end

function M.is_running()
	return selected_runtime_healthy()
end

local function restart_and_validate()
	if sys.call("/etc/init.d/shadowsocksr restart >/dev/null 2>&1") ~= 0 then
		return false
	end
	for _ = 1, 25 do
		if selected_runtime_healthy() then
			return true
		end
		sys.call("sleep 1")
	end
	return false
end

function M.connect(sid)
	sid = trim(sid)
	if not sid:match("^[%w_]+$") then
		return false, "invalid_node"
	end
	local cursor = config_cursor()
	if cursor:get(SSR_CONFIG, sid) ~= "servers" then
		return false, "missing_node"
	end

	ensure_dir(RUNTIME_DIR)
	if sys.call("cp -f /etc/config/shadowsocksr " .. util.shellquote(SSR_BACKUP_FILE)) ~= 0 then
		return false, "snapshot_failed"
	end
	fs.chmod(SSR_BACKUP_FILE, 600)

	local global_sid = cursor:get_first(SSR_CONFIG, "global")
	if not global_sid then
		fs.remove(SSR_BACKUP_FILE)
		return false, "missing_global_config"
	end
	cursor:set(SSR_CONFIG, global_sid, "global_server", sid)
	if not cursor:commit(SSR_CONFIG) then
		fs.remove(SSR_BACKUP_FILE)
		return false, "node_commit_failed"
	end

	local started = restart_and_validate()
	if not started then
		sys.call("cp -f " .. util.shellquote(SSR_BACKUP_FILE) .. " /etc/config/shadowsocksr")
		fs.remove(SSR_BACKUP_FILE)
		sys.call("/etc/init.d/shadowsocksr restart >/dev/null 2>&1")
		return false, "runtime_validation_failed"
	end
	fs.remove(SSR_BACKUP_FILE)

	local settings = config_cursor()
	settings:set(CONFIG, SECTION, "last_server", sid)
	settings:set(CONFIG, SECTION, "auto_connect", "1")
	settings:commit(CONFIG)
	return true
end

function M.disconnect(remember_intent)
	local cursor = config_cursor()
	local current = cursor:get_first(SSR_CONFIG, "global", "global_server", "nil")
	local global_sid = cursor:get_first(SSR_CONFIG, "global")
	if current ~= "nil" and cursor:get(SSR_CONFIG, current) == "servers" then
		cursor:set(CONFIG, SECTION, "last_server", current)
	end
	if global_sid then
		cursor:set(SSR_CONFIG, global_sid, "global_server", "nil")
		cursor:commit(SSR_CONFIG)
	end
	if remember_intent ~= false then
		cursor:set(CONFIG, SECTION, "auto_connect", "0")
	end
	cursor:commit(CONFIG)
	sys.call("/etc/init.d/shadowsocksr failopen >/dev/null 2>&1")
	sys.call("/usr/libexec/hkc-connect-schedule >/dev/null 2>&1")
	return true
end

function M.settings()
	local cursor = config_cursor()
	return {
		autoConnect = get_main(cursor, "auto_connect", "1") == "1",
		domesticProtection = get_main(cursor, "domestic_protection", "1") == "1",
		autoUpdate = get_main(cursor, "auto_update", "1") == "1",
		updateHour = tonumber(get_main(cursor, "update_hour", "5")) or 5,
		updateMinute = tonumber(get_main(cursor, "update_minute", "0")) or 0,
		gameUdp = true,
		gameUdpManaged = true
	}
end

function M.update_settings(values)
	values = values or {}
	local auto_connect = normalize_flag(values.auto_connect, "1")
	local protection = normalize_flag(values.domestic_protection, "1")
	local auto_update = normalize_flag(values.auto_update, "1")
	local hour = tonumber(values.update_hour)
	local minute = tonumber(values.update_minute)
	if not hour or hour < 0 or hour > 23 or hour ~= math.floor(hour) then
		return nil, "invalid_update_hour"
	end
	if not minute or minute < 0 or minute > 59 or minute ~= math.floor(minute) then
		return nil, "invalid_update_minute"
	end

	local cursor = config_cursor()
	local global_sid = cursor:get_first(SSR_CONFIG, "global")
	local old_protection = global_sid and cursor:get(SSR_CONFIG, global_sid, "monitor_enable") or "1"
	cursor:set(CONFIG, SECTION, "auto_connect", auto_connect)
	cursor:set(CONFIG, SECTION, "domestic_protection", protection)
	cursor:set(CONFIG, SECTION, "auto_update", auto_update)
	cursor:set(CONFIG, SECTION, "update_hour", tostring(hour))
	cursor:set(CONFIG, SECTION, "update_minute", tostring(minute))
	cursor:commit(CONFIG)

	local subscribe_sid = cursor:get_first(SSR_CONFIG, "server_subscribe")
	if subscribe_sid then
		cursor:set(SSR_CONFIG, subscribe_sid, "auto_update", auto_update)
		cursor:set(SSR_CONFIG, subscribe_sid, "config_auto_update_mode", "0")
		cursor:set(SSR_CONFIG, subscribe_sid, "auto_update_week_time", "*")
		cursor:set(SSR_CONFIG, subscribe_sid, "auto_update_day_time", tostring(hour))
		cursor:set(SSR_CONFIG, subscribe_sid, "auto_update_min_time", tostring(minute))
	end
	if global_sid then
		cursor:set(SSR_CONFIG, global_sid, "monitor_enable", protection)
	end
	cursor:commit(SSR_CONFIG)
	sys.call("/usr/libexec/hkc-connect-schedule >/dev/null 2>&1")

	local current = cursor:get_first(SSR_CONFIG, "global", "global_server", "nil")
	if auto_connect == "0" and current ~= "nil" then
		M.disconnect(true)
	elseif auto_connect == "1" and current == "nil" then
		local last = trim(get_main(cursor, "last_server", ""))
		if last ~= "" and cursor:get(SSR_CONFIG, last) == "servers" then
			local connected, connect_err = M.connect(last)
			if not connected then
				return nil, connect_err
			end
		end
	elseif auto_connect == "1" and current ~= "nil" and old_protection ~= protection then
		if not restart_and_validate() then
			cursor:set(CONFIG, SECTION, "domestic_protection", old_protection)
			cursor:commit(CONFIG)
			cursor:set(SSR_CONFIG, global_sid, "monitor_enable", old_protection)
			cursor:commit(SSR_CONFIG)
			if not restart_and_validate() then
				sys.call("/etc/init.d/shadowsocksr failopen >/dev/null 2>&1")
				sys.call("/usr/libexec/hkc-connect-schedule >/dev/null 2>&1")
			end
			return nil, "runtime_validation_failed"
		end
	end
	return M.settings()
end

function M.start_sync()
	if not M.is_bound() then
		return false, "not_bound"
	end
	ensure_dir(RUNTIME_DIR)
	if not fs.writefile(SYNC_STATUS_FILE, '{"state":"queued"}\n') then
		return false, "sync_status_failed"
	end
	sys.call("(/usr/libexec/hkc-connect-sync >/dev/null 2>&1) &")
	return true
end

function M.sync_status()
	return read_json(SYNC_STATUS_FILE) or { state = "idle" }
end

function M.status()
	local cursor = config_cursor()
	local node = selected_node(cursor)
	local running = M.is_running()
	local fail_open = fs.access("/var/run/ssrplus.fail-open")
	local update_status = get_main(cursor, "last_update_status", "never")
	return {
		hostname = sys.hostname() or "HKC",
		bound = M.is_bound(),
		running = running,
		connectionState = running and "connected" or (fail_open and "protected" or "disconnected"),
		selectedNode = node,
		account = M.public_account(),
		settings = M.settings(),
		lastUpdate = tonumber(get_main(cursor, "last_update", "0")) or 0,
		lastUpdateStatus = update_status,
		sync = M.sync_status()
	}
end

function M.logout()
	local state = read_json(SESSION_FILE)
	if state and trim(state.access_token) ~= "" then
		curl_json("/client/api/v1/logout", "POST", {}, state.access_token)
	end
	M.disconnect(true)
	local ok, storage = pcall(require, "luci.model.shadowsocksr.subscription_storage")
	if ok and storage then
		local cursor = config_cursor()
		storage.clear(cursor)
		cursor:commit(SSR_CONFIG)
	end
	fs.remove(SESSION_FILE)
	M.clear_web_session()
	return true
end

return M
