#!/usr/bin/env python3
"""Exercise diagnostic boot scripts in a disposable filesystem; no router I/O."""
import hashlib, importlib.util, json, os, shlex, shutil, struct, subprocess, sys, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SECRET='FixtureOnly1234'

def defaults(radios=2):
    result={}
    for i in range(radios):
        r=f'radio{i}'; a=f'default_radio{i}'
        result.update({r:'wifi-device',r+'.band':['2g','5g'][i],r+'.disabled':'0',a:'wifi-iface',a+'.device':r,a+'.ssid':['HKC','HKC-5G'][i],a+'.encryption':'sae-mixed',a+'.key':SECRET,a+'.mode':'ap',a+'.disabled':'0',a+'.network':'lan'})
    return result

def mock(command,args):
    root=Path(os.environ['FIXTURE_ROOT']);config=root/'etc/config';delta=None
    trace=root/'trace'
    def log(s):
        with trace.open('a') as f:f.write(s+'\n')
    def state():return json.loads((root/'state').read_text())
    if command=='uci':
        while args and args[0].startswith('-'):
            flag=args.pop(0)
            if flag in ['-c','-t']:
                val=Path(args.pop(0))
                if flag=='-c':config=val
                else:delta=val
        op=args[0];key=args[1] if len(args)>1 else '';pkg=key.split('.')[0]
        file=config/pkg
        data=json.loads(file.read_text()) if file.exists() and file.stat().st_size else {}
        if op=='changes':
            if state().get('unsaved'): print('wireless.radio0.disabled=1')
            return 0
        if op=='show':
            for k,v in data.items():print(f'{pkg}.{k}='+ (v if '.' not in k else "'"+v+"'"))
            return 0
        if op=='get':
            k=key.split('.',1)[1]
            if k not in data:return 1
            print(data[k]);return 0
        if op=='set':
            if state().get('write_fail') and key.startswith('wireless.'): return 1
            lhs,value=key.split('=',1);data[lhs.split('.',1)[1]]=value
            file.write_text(json.dumps(data));log('set:'+pkg)
            return 0
        if op=='commit':
            log('commit:'+pkg)
            if state().get('concurrent') and pkg=='wireless':(root/'etc/config/wireless').write_text(json.dumps({'changed-by-user':True}))
            return 0
        return 5
    if command=='sleep':
        ticks=root/'ticks';n=int(ticks.read_text())+1 if ticks.exists() else 1;ticks.write_text(str(n))
        if n>=state().get('ready_after',999):
            for i in range(2):(root/f'sys/class/ieee80211/phy{i}').mkdir(parents=True,exist_ok=True)
        return 0
    if command=='wifi':
        log('wifi:'+','.join(args))
        if args==['config']:
            file=root/'etc/config/wireless'
            if not file.exists() or not file.stat().st_size:file.write_text(json.dumps(defaults()))
        if args==['reload'] and state().get('reload_fail'):return 1
        return 0
    if command=='ubus':
        if state().get('netifd_missing'):return 1
        if args==['call','network','reload']:
            log('netifd:reload');return 0
        print('network.wireless');return 0
    if command=='logger':log('logger:'+' '.join(args));return 0
    if command=='dmesg':print('[ 1.0] qca-ssdk initialized\n[ 2.0] ath11k probe');return 0
    if command=='jsonfilter':
        if not (root/'etc/board.json').exists():return 1
        print('sae-mixed');return 0
    return 9

class Diagnostic(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.shell=os.environ.get('HKC_TEST_SHELL') or shutil.which('bash') or shutil.which('sh')
        self.assertTrue(self.shell)
        for d in ['etc/config','etc/ssrplus','tmp/sysinfo','var/run','usr/share/hkc','sys/class/ieee80211','bin','rom/etc/uci-defaults']:(self.root/d).mkdir(parents=True,exist_ok=True)
        self.write('tmp/sysinfo/board_name','jdcloud,re-ss-01')
        self.write('usr/share/hkc/forced-proxy-domains.list','openai.com\nchatgpt.com\n')
        self.write('state','{}');self.write('trace','')
        for command in ['uci','sleep','wifi','ubus','logger','dmesg','jsonfilter']:
            script='#!/bin/sh\nexec '+shlex.quote(sys.executable.replace('\\','/'))+' '+shlex.quote(str(Path(__file__).resolve()).replace('\\','/'))+' --mock '+command+' "$@"\n'
            self.write('bin/'+command,script);(self.root/'bin'/command).chmod(0o755)
        self.env=dict(os.environ,FIXTURE_ROOT=str(self.root),PATH=str(self.root/'bin')+os.pathsep+os.environ['PATH'])
        self.script('defaults.sh.in','rom/etc/uci-defaults/zz-hkc-minimal-defaults')
        self.script('boot-worker.sh','worker.sh')
    def write(self,name,text):
        p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text,encoding='utf-8',newline='\n')
    def state(self,**kw):self.write('state',json.dumps(kw))
    def script(self,source,dest):
        text=(ROOT/'custom/jdcloud-diagnostic'/source).read_text().replace('__WIFI_PASSWORD__',SECRET)
        # Production paths are remapped into the disposable fixture only.
        for prefix in ['/rom/','/usr/share/hkc/','/sys/','/var/run/','/tmp/','/etc/']:
            # Each original prefix is replaced once; don't recursively rewrite
            # the temporary directory's own /tmp prefix on Linux.
            text=text.replace(prefix,'@@'+prefix[1:].replace('/','_')+'@@')
        for prefix in ['/rom/','/usr/share/hkc/','/sys/','/var/run/','/tmp/','/etc/']:
            text=text.replace('@@'+prefix[1:].replace('/','_')+'@@',self.root.as_posix()+prefix)
        text=text.replace('/bin/sh ',shlex.quote(self.shell.replace('\\','/'))+' ').replace('/sbin/wifi','wifi')
        mock_path=(self.root/'bin').as_posix()
        if os.name=='nt':mock_path='/'+mock_path[0].lower()+mock_path[2:]
        text=text.replace('set -u','export PATH='+shlex.quote(mock_path)+':"$PATH"\nset -u',1) if 'set -u' in text else text.replace('#!/bin/sh\n','#!/bin/sh\nexport PATH='+shlex.quote(mock_path)+':"$PATH"\n',1)
        self.write(dest,text)
    def run_script(self,name,*args):
        return subprocess.run([self.shell,str(self.root/name),*args],env=self.env,capture_output=True,text=True,timeout=45)
    def wireless(self,data=None):self.write('etc/config/wireless',json.dumps(defaults() if data is None else data))
    def wifi_run(self):return self.run_script('rom/etc/uci-defaults/zz-hkc-minimal-defaults','--wireless')
    def ready(self):
        for i in range(2):(self.root/f'sys/class/ieee80211/phy{i}').mkdir(exist_ok=True)
    def test_general_defaults_do_not_wait_for_radios(self):
        r=self.run_script('rom/etc/uci-defaults/zz-hkc-minimal-defaults');self.assertEqual(r.returncode,0,r.stderr)
        self.assertIn('chatgpt.com',(self.root/'etc/ssrplus/black.list').read_text())
        self.assertTrue((self.root/'etc/hkc-jdcloud-wifi-pending').exists())
        self.assertNotIn('wireless',(self.root/'trace').read_text())
    def test_staged_two_radio_success(self):
        self.wireless();r=self.wifi_run();self.assertEqual(r.returncode,0,r.stderr)
        data=json.loads((self.root/'etc/config/wireless').read_text())
        self.assertEqual(data['default_radio0.ieee80211w'],'1');self.assertEqual(data['default_radio1.ieee80211w'],'1')
        self.assertNotIn(SECRET,r.stdout+r.stderr)
    def test_one_radio_or_duplicate_band_never_partially_writes(self):
        for data in [defaults(1),dict(defaults(),**{'radio1.band':'2g'})]:
            self.wireless(data);before=(self.root/'etc/config/wireless').read_bytes();r=self.wifi_run()
            self.assertEqual(r.returncode,1,r.stderr);self.assertEqual((self.root/'etc/config/wireless').read_bytes(),before)
    def test_custom_settings_and_pending_edits_preserved(self):
        for key,value in [('default_radio0.ssid','Personal'),('default_radio0.key','changed'),('radio0.disabled','1'),('default_radio0.disabled','1'),('default_radio0.encryption','psk2')]:
            self.wireless(dict(defaults(),**{key:value}));before=(self.root/'etc/config/wireless').read_bytes();r=self.wifi_run()
            self.assertEqual(r.returncode,2,r.stderr);self.assertEqual((self.root/'etc/config/wireless').read_bytes(),before)
        self.wireless();self.state(unsaved=True);self.assertEqual(self.wifi_run().returncode,2)
    def test_failed_uci_write_cannot_commit_partial_config(self):
        self.wireless();before=(self.root/'etc/config/wireless').read_bytes();self.state(write_fail=True)
        self.assertNotEqual(self.wifi_run().returncode,0);self.assertEqual((self.root/'etc/config/wireless').read_bytes(),before)
    def test_concurrent_change_is_preserved(self):
        self.wireless();self.state(concurrent=True);self.assertEqual(self.wifi_run().returncode,2)
        self.assertEqual(json.loads((self.root/'etc/config/wireless').read_text()),{'changed-by-user':True})
    def test_delayed_radios_retry_then_one_netifd_reload(self):
        self.write('etc/hkc-jdcloud-wifi-pending','');self.state(ready_after=2)
        r=self.run_script('worker.sh');self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual((self.root/'ticks').read_text(),'2');self.assertFalse((self.root/'etc/hkc-jdcloud-wifi-pending').exists())
        self.assertEqual((self.root/'trace').read_text().count('netifd:reload'),1)
        self.assertNotIn(SECRET,(self.root/'tmp/hkc-jdcloud-diagnostic.log').read_text())
    def test_timeout_bounded_and_next_boot_recovers(self):
        self.write('etc/hkc-jdcloud-wifi-pending','');r=self.run_script('worker.sh')
        self.assertEqual(r.returncode,0,r.stderr);self.assertEqual((self.root/'ticks').read_text(),'24')
        self.assertTrue((self.root/'etc/hkc-jdcloud-wifi-pending').exists());self.assertFalse((self.root/'etc/config/wireless').exists())
        self.ready();r=self.run_script('worker.sh');self.assertEqual(r.returncode,0,r.stderr)
        self.assertFalse((self.root/'etc/hkc-jdcloud-wifi-pending').exists())
    def test_completed_boot_does_not_reinitialize_wireless(self):
        self.ready();self.wireless();before=(self.root/'etc/config/wireless').read_bytes()
        self.assertEqual(self.run_script('worker.sh').returncode,0)
        self.assertEqual((self.root/'etc/config/wireless').read_bytes(),before)
        self.assertNotIn('wifi:',(self.root/'trace').read_text())
    def test_foreign_board_no_actions(self):
        self.write('tmp/sysinfo/board_name','netcore,n60-pro')
        self.assertEqual(self.run_script('worker.sh').returncode,0)
        self.assertNotEqual(self.run_script('rom/etc/uci-defaults/zz-hkc-minimal-defaults').returncode,0)
        self.assertEqual((self.root/'trace').read_text(),'')
    def test_hotplug_before_board_defaults_is_deferred(self):
        self.script('wifi-hotplug.sh','hotplug.sh');self.env['ACTION']='add'
        self.assertEqual(self.run_script('hotplug.sh').returncode,0);self.assertEqual((self.root/'trace').read_text(),'')
        self.write('etc/board.json','{}');self.assertEqual(self.run_script('hotplug.sh').returncode,0)
        self.assertIn('wifi:config',(self.root/'trace').read_text())
    def test_shell_syntax(self):
        for path in (ROOT/'custom/jdcloud-diagnostic').glob('*.sh*'):
            r=subprocess.run([self.shell,'-n',str(path)],capture_output=True,text=True)
            self.assertEqual(r.returncode,0,r.stderr)

class HardwareContract(unittest.TestCase):
    def test_reset_delay_rejects_missing_or_short_values(self):
        spec=importlib.util.spec_from_file_location('source_tests',ROOT/'scripts/test-hkc-jdcloud.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        data=module.dtb();module.v.check_dtb(data)
        for old,new in [(struct.pack('>I',100000),struct.pack('>I',10)),(b'reset-post-delay-us',b'reset-lost-delay-us')]:
            with self.assertRaises(ValueError):module.v.check_dtb(data.replace(old,new,1))
    def test_staging_scoped_and_preserves_stable_template(self):
        spec=importlib.util.spec_from_file_location('prepare',ROOT/'scripts/prepare-hkc-jdcloud-diagnostic.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'custom').mkdir();shutil.copytree(ROOT/'custom/jdcloud-diagnostic',root/'custom/jdcloud-diagnostic')
            (root/'package/qca/qca-ssdk/patches').mkdir(parents=True)
            (root/'.config').write_text('CONFIG_TARGET_mediatek=y\n')
            with self.assertRaises(ValueError):module.prepare(root,SECRET)
            self.assertFalse((root/'files').exists())
            (root/'.config').write_text('CONFIG_TARGET_qualcommax_ipq60xx_DEVICE_jdcloud_re-ss-01=y\n')
            with self.assertRaises(ValueError):module.prepare(root,'bad')
            if os.name=='nt':
                # Symlink creation needs Windows privileges; Linux CI exercises
                # the real enabled-service link and validates it in the image.
                from unittest.mock import patch
                with patch.object(Path,'symlink_to',lambda p,t:p.write_text(str(t))):module.prepare(root,SECRET)
            else:
                module.prepare(root,SECRET)
                self.assertTrue((root/'files/etc/rc.d/S19hkc-jdcloud-diagnostic').is_symlink())
            self.assertEqual((root/'files/etc/modules.d/ath11k').read_text(),'ath11k nss_offload=0 frame_mode=2\n')
            self.assertNotIn('__WIFI_PASSWORD__',(root/'files/etc/board.d/04_hkc_jdcloud_wifi').read_text())

if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='--mock':sys.exit(mock(sys.argv[2],sys.argv[3:]))
    unittest.main(verbosity=2)
