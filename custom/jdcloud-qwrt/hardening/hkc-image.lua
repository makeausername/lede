-- Strict USTAR/SquashFS envelope checks. Hashes/metadata are checked by the shell.
-- No shell execution, hardware access or extraction in this parser.
local image, root_size = assert(arg[1]), assert(tonumber(arg[2]))
assert(root_size >= 65536 and root_size % 65536 == 0 and root_size + 33554432 < 314572800, 'root size')
local f = assert(io.open(image, 'rb'))
local size = assert(f:seek('end')); assert(size < 321912832, 'image too large'); f:seek('set', 0)
local function read(n) local b=assert(f:read(n),'truncated'); assert(#b==n,'short read'); return b end
local function str(b) local p=b:find('\0',1,true); if p then assert(b:sub(p):match('^%z*$'),'string suffix'); return b:sub(1,p-1) end; return b end
local function oct(b) b=b:gsub('%z',''):match('^%s*(.-)%s*$'); assert(b:match('^[0-7]+$'),'octal'); return assert(tonumber(b,8)) end
local function le(b) local n=0; for i=#b,1,-1 do n=n*256+b:byte(i) end; return n end
local function be(b) local n=0; for i=1,#b do n=n*256+b:byte(i) end; return n end
local dir='sysupgrade-jdcloud-ax1800-pro'
local expected={dir..'/',dir..'/CONTROL',dir..'/kernel',dir..'/root'}
for i,name in ipairs(expected) do
 local h=read(512); assert(str(h:sub(1,100))==name,'member order/name')
 assert(h:sub(258,263)=='ustar\0' and h:sub(264,265)=='00','USTAR required')
 assert(str(h:sub(346,500))=='' and str(h:sub(158,257))=='','prefix/link forbidden')
 assert(oct(h:sub(109,116))==0 and oct(h:sub(117,124))==0,'non-root owner')
 local sum=0; for j=1,512 do sum=sum+((j>=149 and j<=156) and 32 or h:byte(j)) end
 assert(sum==oct(h:sub(149,156)),'header checksum')
 local bytes=oct(h:sub(125,136)); assert(h:sub(157,157)==(i==1 and '5' or '0'),'member type')
 if i==1 then assert(bytes==0,'directory payload')
 elseif i==2 then assert(bytes==#'BOARD=jdcloud-ax1800-pro\n' and read(bytes)=='BOARD=jdcloud-ax1800-pro\n','CONTROL')
 elseif i==3 then assert(bytes==6291456,'kernel size'); assert(f:seek('cur',bytes),'kernel bounds')
 else
  assert(bytes==root_size,'root size metadata mismatch'); local sb=read(96)
  assert(sb:sub(1,4)=='hsqs' and le(sb:sub(13,16))==262144 and le(sb:sub(21,22))==4,'SquashFS/XZ format')
  assert(le(sb:sub(29,30))==4 and le(sb:sub(31,32))==0,'SquashFS version')
  local used=le(sb:sub(41,48)); assert(used>=96 and math.floor((used+65535)/65536)*65536==bytes,'root padding boundary')
  assert(sb:sub(57,64)==string.rep('\255',8),'xattrs unsupported')
  assert(f:seek('cur',used-96)); assert(read(bytes-used):match('^%z*$'),'nonzero root padding')
 end
 local pad=(512-bytes%512)%512; if pad>0 then assert(read(pad):match('^%z*$'),'member padding') end
end
local pos=assert(f:seek()); local boundary=math.ceil((pos+1024)/10240)*10240
assert(read(boundary-pos):match('^%z*$'),'extra member or tar padding')
assert(size-boundary>24 and size-boundary<=30744,'metadata bounds')
assert(read(8)==string.rep('\0',8),'metadata header')
assert(f:seek('set',size-16)); local tail=read(16)
assert(tail:sub(1,4)=='FWx0' and tail:byte(9)==1 and tail:sub(10,12)=='\0\0\0','metadata trailer')
assert(be(tail:sub(13,16))==size-boundary,'metadata length')
f:close()
