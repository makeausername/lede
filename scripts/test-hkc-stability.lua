
local fs=require "nixio.fs"
local sys=require "luci.sys"
local uci=require "luci.model.uci"
local nixio=require "nixio"
-- Run with the OpenWrt Lua/LuCI libraries. All UCI mutations use a fresh fixture.
local runtime = assert(arg[1], "Usage: lua test-hkc-stability.lua RUNTIME_ROOT")
local root = "/tmp/hkc-stability-test-" .. nixio.getpid()
assert(not fs.access(root), "test directory already exists")
fs.mkdirr(root.."/config"); fs.mkdirr(root.."/saved")
local safe=dofile(runtime .. "/usr/share/shadowsocksr/hkc-update-safe.lua")
assert(safe.atomic_write(root.."/atomic","original"))
assert(fs.readfile(root.."/atomic")=="original")
assert(not safe.atomic_write(root.."/missing/no-file","bad"))
local ip={}
for i=1,20 do ip[#ip+1]="1.2."..i..".0/24\n" end
assert(safe.atomic_write(root.."/ip",table.concat(ip)))
assert(safe.valid_rules(root.."/ip","ip_data"))
assert(safe.atomic_write(root.."/bad","999.2.3.0/24\n"..table.concat(ip)))
assert(not safe.valid_rules(root.."/bad","ip_data"))
assert(safe.atomic_write(root.."/html","<!doctype html><html>google.com error</html>"))
assert(safe.is_error_document(root.."/html"))
assert(safe.atomic_write(root.."/dns",string.rep("server=/example.com/127.0.0.1#5335\n",20)))
assert(safe.valid_rules(root.."/dns","gfw_data"))
assert(safe.install_rules(root.."/ip",root.."/atomic",root.."/runtime"))
local preserved=fs.readfile(root.."/atomic")
assert(not safe.install_rules(root.."/dns",root.."/atomic",root.."/missing/runtime"))
assert(fs.readfile(root.."/atomic")==preserved)
assert(safe.fingerprint({server="1.2.3.4",alias="old"})==safe.fingerprint({server="1.2.3.4",alias="new"}))
print("PASS rules-format, atomic-write, runtime-copy rollback, active-fingerprint")

local original_cursor=require("uci").cursor
local original_call=sys.call
local original_exec=sys.exec
local original_read=fs.readfile
local original_dofile=dofile
local gh=original_exec("printf %s https://example.invalid/test | md5sum"):match("^(%x+)")
local source=assert(original_read(runtime .. "/usr/share/shadowsocksr/subscribe.lua"))
source=source:gsub("^#![^\n]*\n", "")
source=source:sub(1,assert(source:find("\nif subscribe_items and #subscribe_items > 0 then",1,true))-1)
source=source.."\nreturn execute"
source=source:gsub('local function write_new_md5%(groupHash, md5, url%)','local function write_new_md5(groupHash, md5, url) TEST_MD5 = TEST_MD5 + 1; do return end')
source=source:gsub('local function read_old_md5%(groupHash%)','local function read_old_md5(groupHash) do return nil end')
source=source:gsub('local function read_old_groupHash%(url%)','local function read_old_groupHash(url) do return nil end')
local fixture=[[
config global 'global'
 option global_server 'manual'
config server_subscribe 'sub'
 option enable_mihomo '0'
 option filter_words ''
 option proxy '0'
 list subscribe_url 'https://example.invalid/test'
config servers 'manual'
 option type 'v2ray'
 option v2ray_protocol 'vless'
 option server '192.0.2.1'
 option server_port '443'
 option alias 'manual'
config servers 'old'
 option type 'v2ray'
 option v2ray_protocol 'vless'
 option server '192.0.2.2'
 option server_port '443'
 option alias 'old'
 option hashkey 'oldhash'
 option grouphashkey 'GROUP'
]]
fixture=fixture:gsub("GROUP",gh)
local cases={
 {"empty","",true},
 {"html","<html>upstream error</html>",true},
 {"garbage","not a subscription payload",true},
 {"json-error",'{"error":"upstream unavailable"}',true},
 {"partial-invalid","vless://00000000-0000-4000-8000-000000000001@192.0.2.3:443?security=tls&type=tcp#candidate\ninvalid-node",true},
 {"valid-vless","vless://00000000-0000-4000-8000-000000000001@192.0.2.3:443?security=tls&type=tcp#candidate",false},
}
-- Test runner arguments must not become the subscription's optional section filter.
local runner_args = arg
arg = {}
for _,case in ipairs(cases) do
 fs.writefile(root.."/config/shadowsocksr",fixture)
 local native=original_cursor(root.."/config",root.."/saved")
 local cursor=setmetatable({}, {__index=function(_,k) return function(_,...) return native[k](native,...) end end})
 function cursor:get_first(config,kind,option,default)
   local result=default
   native:foreach(config,kind,function(s) if option then result=s[option] else result=s['.name'] end; return false end)
   if result==nil then return default end
   return result
 end
 function cursor:tset(config,section,values)
   for k,v in pairs(values) do if k:sub(1,1)~='.' then native:set(config,section,k,v) end end
   return true
 end
 function cursor:section(config,kind,id,values)
   native:set(config,id,kind)
   if values then self:tset(config,id,values) end
   return id
 end
 assert(cursor:get("shadowsocksr","manual","server")=="192.0.2.1", "fixture cursor is not isolated")
 uci.cursor=function() return cursor end
 local commands=0
 sys.call=function(cmd)
   commands=commands+1
   error("Unexpected command in subscription test")
 end
 sys.exec=function(cmd)
   if cmd:find("type -t -p xray",1,true) then return "/usr/bin/xray" end
   if cmd:find("type -t -p",1,true) then return "" end
   if cmd:find("md5sum",1,true) then return original_exec(cmd) end
   error("Unexpected exec in subscription test")
 end
 fs.readfile=function(path)
   if path=="/etc/config/shadowsocksr" then return original_read(root.."/config/shadowsocksr") end
   return original_read(path)
 end
 local mock={}
 for k,v in pairs(safe) do mock[k]=v end
 mock.lock=function() return {} end
 mock.download=function(url,path) fs.writefile(path,case[2]); return #case[2]>0 end
 dofile=function(path) assert(path=="/usr/share/shadowsocksr/hkc-update-safe.lua"); return mock end
 TEST_MD5=0
 local fn=assert(loadstring(source))()
 local ok,err=pcall(fn)
 -- Malformed source can throw; outer production handler reverts without service mutation.
 if not ok then cursor:revert("shadowsocksr") end
 cursor:unload("shadowsocksr")
 cursor:load("shadowsocksr")
 assert(cursor:get("shadowsocksr","manual","server")=="192.0.2.1")
 assert(commands==0,case[1].." restarted active service")
 if case[3] then
   assert(cursor:get("shadowsocksr","old","server")=="192.0.2.2",case[1].." deleted old node")
   assert(TEST_MD5==0,case[1].." wrote invalid MD5")
 else
   assert(ok,err)
   assert(TEST_MD5==1,"valid VLESS not imported")
   local count=0;cursor:foreach("shadowsocksr","servers",function(s) if s.server=="192.0.2.3" then count=count+1 end end)
   assert(count==1,"candidate missing")
 end
 print("PASS subscription "..case[1].." old-state protection / no unrelated restart")
end
arg = runner_args
sys.call=original_call;sys.exec=original_exec;fs.readfile=original_read;dofile=original_dofile
-- The fixture remains under /tmp for inspection and is discarded at reboot.
