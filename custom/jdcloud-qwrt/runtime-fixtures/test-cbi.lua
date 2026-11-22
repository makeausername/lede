local http=require 'luci.http'
local util=require 'luci.util'
local tpl=require 'luci.template'
local disp=require 'luci.dispatcher'
local cbi=require 'luci.cbi'
local i18n=require 'luci.i18n'
local fs=require 'nixio.fs'
local chunks={}
http.context.request=http.Request({REQUEST_METHOD='GET',SCRIPT_NAME='/cgi-bin/luci',PATH_INFO='/admin/services/shadowsocksr/servers',QUERY_STRING=''},function()return nil end,function()end)
http.context.request.parsed_input=true
http.write=function(s) chunks[#chunks+1]=tostring(s or '') end
http.prepare_content=function()end
http.header=function()end
http.status=function()end
http.redirect=function(url) error('unexpected redirect '..url)end
util.ubus=function(obj,method) if obj=='system' and method=='board' then return {hostname='HKC',model='Offline QWRT fixture',release={}} end return {} end
local ctx=disp.context
ctx.requestpath={'admin','services','shadowsocksr','servers'};ctx.path=ctx.requestpath;ctx.request=ctx.requestpath;ctx.dispatched={title='SSR Plus+'};ctx.authuser='root';ctx.authtoken='offline-fixture';ctx.authsession='offline-fixture';ctx.lang='en';ctx.tree={nodes={}};ctx.treecache={};disp.entry({"admin"},disp.firstchild(),"Administration",1);disp.entry({"admin","services"},disp.firstchild(),"Services",1);disp.entry({"admin","services","shadowsocksr"},disp.firstchild(),"SSR Plus+",1);disp.entry({"admin","services","shadowsocksr","servers"},disp.cbi("shadowsocksr/servers"),"Servers",1)
local function attr(cond,key,val)
 if not cond then return '' end
 local env=getfenv(3);local scope=type(env.self)=='table' and env.self or nil
 if type(val)=='table' then if not next(val)then return '' else val=util.serialize_json(val)end end
 return string.format(' %s="%s"',tostring(key),util.pcdata(tostring(val or(type(env[key])~='function' and env[key])or(scope and type(scope[key])~='function' and scope[key])or'')))
end
local ns={write=http.write,include=function(name)tpl.Template(name):render(getfenv(2))end,translate=i18n.translate,translatef=i18n.translatef,export=function(k,v)if tpl.context.viewns[k]==nil then tpl.context.viewns[k]=v end end,striptags=util.striptags,pcdata=util.pcdata,media='/luci-static/argon',theme='argon',resource='/luci-static/resources',ifattr=function(...)return attr(...)end,attr=function(...)return attr(true,...)end,url=disp.build_url,controller='/cgi-bin/luci',REQUEST_URI='/cgi-bin/luci/admin/services/shadowsocksr/servers',token='offline-fixture'}
setmetatable(ns,{__index=_G});tpl.context.viewns=ns
for _,lang in ipairs({arg[1] or 'en'})do
 chunks={};i18n.setlanguage(lang);print('LANG',lang,i18n.translate('Subscription Updates'),i18n.translate('Servers subscription and manage'));i18n.loadc('ssr-plus',lang);i18n.loadc('hkc-ssr-ui',lang)
 local ok,e=pcall(function()
  local maps=cbi.load('shadowsocksr/servers');print('CBI_MAPS',lang,#maps)
  tpl.render('themes/argon/header')
  for _,map in ipairs(maps)do map:render({firstmap=true})end
  tpl.render('themes/argon/footer')
 end)
 print('CBI_RENDER',lang,ok,not ok and tostring(e) or '')
 if ok then local html=table.concat(chunks);fs.writefile('/tmp/servers-'..lang..'.html',html);print('HTML64 '..lang..' '..require('nixio').bin.b64encode(html));print('HTML_BYTES',lang,#html)end
end

chunks={};ctx.template_header_sent=nil;ctx.authsession=nil
local ok,e=pcall(function()tpl.render('themes/argon/sysauth',{duser='root',fuser=nil})end)
print('LOGIN_RENDER',arg[1]or'en',ok,not ok and tostring(e)or'')
if ok then local html=table.concat(chunks);print('LOGIN64 '..(arg[1]or'en')..' '..require('nixio').bin.b64encode(html))end
