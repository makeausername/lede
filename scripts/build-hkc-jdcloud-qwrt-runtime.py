#!/usr/bin/env python3
from pathlib import Path
import json,shlex,hashlib,gzip,stat
import argparse
p=argparse.ArgumentParser(description="Build an offline userspace test initramfs, never a device image")
p.add_argument('--audit-dir',required=True,type=Path)
p.add_argument('--review-dir',required=True,type=Path)
p.add_argument('--dependency-dir',required=True,type=Path)
p.add_argument('--output',required=True,type=Path)
a=p.parse_args()
repo=Path(__file__).resolve().parents[1]
out=a.output.resolve();audit=a.audit_dir.resolve();review=a.review_dir.resolve();pool=a.dependency_dir.resolve()
if out.exists() or any(out.is_relative_to(x) or x.is_relative_to(out) for x in [audit,review,pool]):raise ValueError('Fresh output outside inputs required')
out.mkdir(parents=True)
profile=json.loads((repo/'custom/jdcloud-qwrt/profile.json').read_text(encoding='utf-8'))
for filename,key in [('working-qwrt-file-hashes.json','base_file_manifest_sha256'),('working-qwrt-inode-list.txt','base_inode_manifest_sha256')]:
 if hashlib.sha256((audit/filename).read_bytes()).hexdigest()!=profile[key]:raise ValueError('Audit manifest mismatch')
fixtures=repo/'custom/jdcloud-qwrt/runtime-fixtures'
root=audit/'working-qwrt-complete';mapping=json.loads((audit/'working-qwrt-path-map.json').read_text());hashes=json.loads((audit/'working-qwrt-file-hashes.json').read_text());entries={};source={}
def put(p,data,mode=0o100644,origin='fixture'):
 assert not p.startswith('/') and '..' not in p.split('/') and '\\' not in p
 entries[p]=(data,mode);source[p]=origin
 for parent in Path(p).parents:
  n=parent.as_posix()
  if n!='.' and n not in entries:entries[n]=(b'',0o40755)
clients={'usr/bin/lua','usr/bin/ssr-local','usr/bin/ssr-redir','usr/bin/xray','usr/bin/sslocal','usr/bin/jq','usr/bin/curl','usr/bin/resolveip','usr/bin/nping','usr/bin/microsocks','usr/bin/obfs-local','usr/bin/dns2tcp','usr/bin/tcping','usr/bin/ipt2socks','usr/bin/unzip','usr/libexec/base64-coreutils','sbin/uci'}
def allowed(p):
 return p=='bin/busybox' or p in clients or (p.startswith(('lib/','usr/lib/')) and '.so' in Path(p).name and not p.startswith(('lib/modules/','lib/firmware/'))) or p.startswith(('usr/lib/lua/','usr/share/lua/','usr/lib/lua/luci/view/'))
for line in (audit/'working-qwrt-inode-list.txt').read_text().splitlines():
 x=shlex.split(line);kind,p=x[:2]
 if kind=='file' and allowed(p):
  data=(root/mapping[p]).read_bytes();assert hashlib.sha256(data).hexdigest()==hashes[p];put(p,data,stat.S_IFREG|int(x[2],8),'original-qwrt')
 elif kind=='slink' and (allowed(p) or p.startswith(('bin/','sbin/','usr/bin/')) and x[5].endswith('busybox')):put(p,x[5].encode(),0o120777,'original-qwrt-link')
modes=json.loads((review/'MODES.json').read_text())
import importlib.util
spec=importlib.util.spec_from_file_location('port',repo/'scripts/prepare-hkc-jdcloud-qwrt.py');port=importlib.util.module_from_spec(spec);spec.loader.exec_module(port)
for p,mode in modes.items():
 # Review payloads are confined by the production review generator's allowlist.
 if int(mode,8) not in [0o600,0o644,0o755]:raise ValueError('Unapproved file mode')
 if not port.allowed(p):raise ValueError('Review includes protected path: '+p)
 payload=port.regular(review/'review-only-files',p).read_bytes()
 if payload.startswith(b'\x7fELF'):raise ValueError('Native binaries must enter via dependency lock')
 if p in profile['overlay'] and hashlib.sha256(payload).hexdigest()!=profile['overlay'][p]['sha256']:raise ValueError('Runtime drift: '+p)
 put(p,payload,stat.S_IFREG|int(mode,8),'HKC-review')
lock=json.loads((repo/'custom/jdcloud-qwrt/dependency-lock.json').read_text())
meta=json.loads((pool/'VERIFIED-PACKAGES.json').read_text())
for pkg in ['nping','xz','xz-utils','liblzma']:
 pinned=lock['official_candidates'][pkg]
 if meta[pkg]['files']!=pinned['files'] or meta[pkg]['symlinks']!=pinned['symlinks']:raise ValueError('Dependency lock drift: '+pkg)
 for p,v in meta[pkg]['files'].items():
  assert p not in entries,p;data=(pool/pkg/p).read_bytes();assert hashlib.sha256(data).hexdigest()==v['sha256'];put(p,data,stat.S_IFREG|int(v['mode'],8),'candidate-'+pkg)
 for p,t in meta[pkg]['symlinks'].items():
  assert p not in entries,p;put(p,t.encode(),0o120777,'candidate-'+pkg)
donor=audit/'hkc-diagnostic-complete'
for pkg,v in lock['donor_candidates'].items():
 for p,h in v['files'].items():
  data=(donor/p).read_bytes();assert hashlib.sha256(data).hexdigest()==h;put(p,data,0o100755 if data[:4]==b'\x7fELF' else 0o100644,'candidate-'+pkg)
for p in ['proc','sys','dev','tmp','var','var/run','var/lock','etc/config','etc/uci-defaults','run']:
 if p not in entries:put(p,b'',0o40755)
put('etc/passwd',b'root:x:0:0:Offline test:/root:/bin/ash\n');put('etc/group',b'root:x:0:\n');put('etc/TZ',b'UTC\n')
put('etc/config/luci',b"config core 'main'\n option lang 'en'\n option mediaurlbase '/luci-static/argon'\n option resourcebase '/luci-static/resources'\nconfig internal 'ccache'\n option enable '0'\nconfig internal 'themes'\n option Argon '/luci-static/argon'\n")
put('etc/config/shadowsocksr',b"config global\n option monitor_enable '1'\n option switch_time '30'\nconfig server_subscribe\n option auto_update '1'\n option auto_update_time '2'\nconfig servers 'fixture'\n option type 'ssr'\n option server '192.0.2.1'\n option server_port '443'\n option password 'test-only'\n option encrypt_method 'aes-256-cfb'\n option protocol 'auth_aes128_md5'\n option obfs 'tls1.2_ticket_auth'\n option timeout '60'\n")
put('test.lua',b'''local modules={"nixio","nixio.fs","uci","luci.model.uci","luci.sys","luci.jsonc","luci.template.parser","luci.cbi","url","lyaml"}
for _,n in ipairs(modules) do local ok,e=pcall(require,n);print("MODULE",n,ok,not ok and tostring(e) or "") end
local ok,e=pcall(function()local y=require("lyaml");local v=y.load("name: HKC\\nvalue: 30\\n");assert(v.name=="HKC" and v.value==30)end);print("YAML_ROUNDTRIP",ok,e)
local fs=require("nixio.fs");local parser=require("luci.template.parser");local count,errors=0,0
local function walk(dir)for n in fs.dir(dir) do local p=dir.."/"..n;if fs.stat(p,"type")=="dir" then walk(p)elseif n:match("%.htm$") then local f,_,e=parser.parse(p);count=count+1;if not f then errors=errors+1;print("TEMPLATE_ERROR",p,e)end end end end
walk("/usr/lib/lua/luci/view/shadowsocksr");walk("/usr/lib/lua/luci/view/themes/argon");print("TEMPLATES",count,errors)
''')
init='''#!/bin/ash
export PATH=/bin:/sbin:/usr/bin:/usr/sbin
mount -t proc proc /proc
mount -t sysfs sysfs /sys
mount -t devtmpfs devtmpfs /dev
mkdir -p /dev/pts
exec >/dev/console 2>&1
echo HKC_OFFLINE_RUNTIME_BEGIN
uname -a
lua /test.lua
for p in tcp udp tcp,udp; do lua /usr/share/shadowsocksr/gen_config.lua fixture "$p" 1234 0 0 >/tmp/config-$p.json; echo CONFIG_GENERATED $p $?; done
for command in 'ssr-local -h' 'ssr-redir -h' 'xray version' 'sslocal --version' 'naive --version' 'shadow-tls --version' 'v2ray-plugin -version' 'chinadns-ng -V' 'nping --version' 'xz --version'; do
 echo CLIENT_BEGIN "$command"
 sh -c "$command" >/tmp/client.log 2>&1 &
 client_pid=$!
 (sleep 12; kill "$client_pid" 2>/dev/null) &
 timer_pid=$!
 wait "$client_pid"
 echo CLIENT_EXIT $?
 kill "$timer_pid" 2>/dev/null
 wait "$timer_pid" 2>/dev/null
 head -8 /tmp/client.log
done
echo HKC_OFFLINE_RUNTIME_END
sync
poweroff -f
'''
put('test-clients.sh',(fixtures/'test-clients.sh').read_bytes().removeprefix(b'\xef\xbb\xbf').replace(b'\r\n',b'\n'),0o100755)
put('test-cbi.lua',(fixtures/'test-cbi.lua').read_bytes().removeprefix(b'\xef\xbb\xbf'))
init=init.replace('echo HKC_OFFLINE_RUNTIME_END','/bin/ash /test-clients.sh\nlua /test-cbi.lua en\nlua /test-cbi.lua zh_cn\necho HKC_OFFLINE_RUNTIME_END')
put('init',init.encode(),0o100755)
# newc archive, entirely in guest RAM; no original configuration or disks.
data=bytearray()
for ino,(name,(payload,mode)) in enumerate(sorted(entries.items()),1):
 n=name.encode()+b'\0';fields=[ino,mode,0,0,2 if stat.S_ISDIR(mode) else 1,0,len(payload),0,0,0,0,len(n),0];header=b'070701'+b''.join(f'{x:08x}'.encode() for x in fields);data.extend(header+n);data.extend(b'\0'*(-len(data)%4));data.extend(payload);data.extend(b'\0'*(-len(data)%4))
n=b'TRAILER!!!\0';data.extend(b'070701'+b''.join(f'{x:08x}'.encode() for x in [0,0,0,0,1,0,0,0,0,0,0,len(n),0])+n);data.extend(b'\0'*(-len(data)%4));packed=gzip.compress(bytes(data),compresslevel=1,mtime=0);(out/'userspace-test.cpio.gz').write_bytes(packed)
(out/'INITRAMFS-MANIFEST.json').write_text(json.dumps({'sha256':hashlib.sha256(packed).hexdigest(),'files':{p:{'mode':oct(m),'sha256':hashlib.sha256(d).hexdigest(),'source':source.get(p,'directory')} for p,(d,m) in entries.items()},'no_original_configuration':True,'no_device_disks':True,'network_disabled':True},indent=2),encoding='utf-8')
print('initramfs files',len(entries),'bytes',len(packed))
