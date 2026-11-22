#!/usr/bin/env python3
"""Run a local RAM-only, NIC-less ARM64 userspace check. Never a device boot check."""
import argparse,base64,hashlib,json,re,subprocess,time
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--qemu',required=True,type=Path);p.add_argument('--kernel',required=True,type=Path);p.add_argument('--ramfs',required=True,type=Path);p.add_argument('--output',required=True,type=Path)
a=p.parse_args();out=a.output.resolve()
if out.exists():raise ValueError('Fresh output required')
for f in [a.qemu,a.kernel,a.ramfs]:
 if not f.is_file():raise ValueError('Missing input: '+str(f))
out.mkdir(parents=True)
cmd=[str(a.qemu.resolve()),'-machine','virt','-accel','tcg,thread=multi','-cpu','cortex-a53','-smp','2','-m','768','-nic','none','-display','none','-monitor','none','-serial','stdio','-no-reboot','-kernel',str(a.kernel.resolve()),'-initrd',str(a.ramfs.resolve()),'-append','console=ttyAMA0 rdinit=/init panic=-1 quiet']
start=time.monotonic();code=None
with (out/'runtime.log').open('wb') as log:
 try:code=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,timeout=180).returncode
 except subprocess.TimeoutExpired:code='timeout'
text=(out/'runtime.log').read_text(encoding='utf-8',errors='replace');errors=[]
for needle in ['HKC_OFFLINE_RUNTIME_BEGIN','HKC_OFFLINE_RUNTIME_END','YAML_ROUNDTRIP\ttrue','REALITY_CORE_TEST 0','SSR_CONFIG_LISTENER tcp PASS','SSR_CONFIG_LISTENER udp PASS','SSR_CONFIG_LISTENER tcp,udp PASS']:
 if needle not in text:errors.append('Missing '+needle)
for check in ['DEFAULTS','IDEMPOTENT','CUSTOM_PRESERVED','EMPTY_DEFAULTS','REJECT_board','REJECT_ports','REJECT_dns','REJECT_conflict','REJECT_uncommitted','ROLLBACK','TIMEOUT','PROCD','CLOCK_FIXTURES','DAEMON_NO_NODE','ALL']:
 if 'INTEGRATION_'+check+' PASS' not in text:errors.append('integration '+check)
for lang in ['en','zh_cn']:
 for check in ['CBI_RENDER','LOGIN_RENDER']:
  if check+'\t'+lang+'\ttrue' not in text:errors.append(check+' '+lang)
for module in ['nixio','nixio.fs','uci','luci.model.uci','luci.sys','luci.jsonc','luci.template.parser','luci.cbi','url','lyaml']:
 if 'MODULE\t'+module+'\ttrue' not in text:errors.append('module '+module)
if not re.search(r'^TEMPLATES\t33\t0\s*$',text,re.M):errors.append('template parser')
if text.count('CLIENT_EXIT 0')!=10:errors.append('client smoke checks')
if code!=0:errors.append('VM exit '+str(code))
for line in text.splitlines():
 if line.startswith(('HTML64 ','LOGIN64 ')):
  kind,lang,payload=line.split(' ',2)
  if lang not in ['en','zh_cn']:raise ValueError('Unexpected language')
  data=base64.b64decode(payload,validate=True);(out/(('servers-' if kind=='HTML64' else 'login-')+lang+'.html')).write_bytes(data)
report={'passed':not errors,'errors':errors,'returncode':code,'seconds':round(time.monotonic()-start,3),'inputs':{k:hashlib.sha256(v.read_bytes()).hexdigest() for k,v in [('qemu',a.qemu),('kernel',a.kernel),('ramfs',a.ramfs)]},'network':'none','device_disks':'none','userspace':'selected original QWRT files plus candidate apps, synthetic settings','kernel':'Alpine virt test kernel; NOT original QWRT kernel','device_boot_tested':False,'proxy_traffic_tested':False,'authentication_tested':False,'integration_uses_synthetic_config':True,'clock_transport':'synthetic HTTPS headers, no external server or TLS test','procd_transport':'original QWRT API with captured JSON, no ubus daemon','cbi_scope':'original renderer with synthetic HTTP context, menu tree and board ubus reply; no login authorization exercised'}
(out/'RUNTIME-VERIFICATION.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8');print(json.dumps(report,indent=2));raise SystemExit(bool(errors))
