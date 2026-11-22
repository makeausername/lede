#!/usr/bin/env python3
"""Negative overlay guards and isolated legacy QWRT UCI regression fixtures."""
import hashlib, importlib.util, json, os, shlex, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path
sys.dont_write_bytecode = True
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('port',ROOT/'scripts/prepare-hkc-jdcloud-qwrt.py')
port=importlib.util.module_from_spec(spec);spec.loader.exec_module(port)

def mock_uci():
    file=Path(os.environ['HKC_TEST_STATE']);state=json.loads(file.read_text())
    args=[a for a in sys.argv[2:] if a!='-q'];cmd,key=args
    if cmd=='get':
        if key not in state:return 1
        print(state[key]);return 0
    if cmd=='set':k,v=key.split('=',1);state[k]=v
    elif cmd=='delete':
        if key not in state:return 1
        del state[key]
    elif cmd=='commit':
        assert key in ['network','dhcp','firewall'];return 0
    else:raise AssertionError(args)
    file.write_text(json.dumps(state));return 0

class OverlayTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name);self.donor=self.base/'donor';self.donor.mkdir()
        self.path='usr/libexec/hkc-ssr-health';f=self.donor/self.path;f.parent.mkdir(parents=True);f.write_bytes(b'#!/bin/sh\nexit 0\n')
        self.profile={'overlay':{self.path:{'sha256':port.digest(f),'mode':'0755'}},'required_new_packages':['chinadns-ng'],'not_installable_until':['runtime']}
    def test_noninstallable_success(self):
        out=self.base/'out';r=port.write_review_overlay(self.profile,self.donor,out)
        self.assertFalse(r['installable']);self.assertFalse(r['boot_tested']);self.assertEqual(r['missing_dependency_names'],['chinadns-ng'])
        self.assertEqual((out/'review-only-files'/self.path).read_bytes(),(self.donor/self.path).read_bytes())
    def test_wrong_hash_no_output(self):
        self.profile['overlay'][self.path]['sha256']='0'*64;out=self.base/'out'
        with self.assertRaises(ValueError):port.write_review_overlay(self.profile,self.donor,out)
        self.assertFalse(out.exists())
    def test_elf_not_allowed_even_with_matching_hash(self):
        f=self.donor/self.path;f.write_bytes(b'\x7fELFbad');self.profile['overlay'][self.path]['sha256']=port.digest(f)
        with self.assertRaises(ValueError):port.write_review_overlay(self.profile,self.donor,self.base/'out')
    def test_protected_paths(self):
        for p in ['etc/config/network','lib/modules/5.4.250/test.ko','lib/firmware/qca-nss0.bin','etc/init.d/network','lib/upgrade/platform.sh','sbin/procd','usr/lib/libc.so']:
            self.assertFalse(port.allowed(p),p)
    def test_path_traversal(self):
        for p in ['../escape','/etc/config/network','C:/escape','usr\\bin\\test']:
            with self.assertRaises(ValueError):port.safe_path(p)
    def test_existing_output_preserved(self):
        out=self.base/'out';out.mkdir();keep=out/'keep';keep.write_text('keep')
        with self.assertRaises(ValueError):port.write_review_overlay(self.profile,self.donor,out)
        self.assertEqual(keep.read_text(),'keep')
    def test_input_overlap(self):
        with self.assertRaises(ValueError):port.write_review_overlay(self.profile,self.donor,self.donor/'out')
    def test_privileged_mode(self):
        self.profile['overlay'][self.path]['mode']='4755'
        with self.assertRaises(ValueError):port.validate_payload(self.profile,self.donor)
    def test_pinned_profile_runtime_contract(self):
        p=json.loads((ROOT/'custom/jdcloud-qwrt/profile.json').read_text())
        for path in p['overlay']:self.assertTrue(port.allowed(path),path)
        count=0
        for line in (ROOT/'custom/hkc-stability-runtime.sha256').read_text().splitlines():
            if not line or line.startswith('#'):continue
            digest,path=line.split();self.assertEqual(p['overlay'][path]['sha256'],digest);count+=1
        self.assertEqual(count,12);self.assertFalse(p['sdk']['exact_qwrt_sdk']);self.assertEqual(p['sdk']['scope'],'userspace-only-candidate')
        self.assertFalse(any('.ut'==Path(p).suffix for p in p['legacy_theme']['files']))

class LegacyLanTests(unittest.TestCase):
    def test_legacy_bridge_policy_and_rejections(self):
        shell=os.environ.get('HKC_TEST_SHELL') or shutil.which('bash') or shutil.which('sh');self.assertTrue(shell)
        source=(ROOT/'custom/jdcloud-qwrt/lan-ipv4-only.sh').read_text()
        source=source.replace('. /lib/functions.sh\n','').replace('. /lib/functions/system.sh\n','')
        before={'network.lan.type':'bridge','network.lan.ifname':'eth2 eth0 eth1','network.wan.ifname':'eth3','network.lan.ipaddr':'192.168.2.1','network.lan.ip6assign':'60','network.wan.proto':'dhcp','network.wan6.proto':'dhcpv6','network.loopback.ifname':'lo','network.loopback.ipv6':'1','dhcp.lan.interface':'lan','dhcp.@dnsmasq[0]':'dnsmasq','dhcp.@dnsmasq[1]':'dnsmasq','dhcp.@dnsmasq[1].filter_aaaa':'0','wireless.radio0.channel':'auto','shadowsocksr.@global[0].global_server':'unchanged'}
        delta={'network.lan.ipv6':'0','dhcp.lan.ra':'disabled','dhcp.lan.dhcpv6':'disabled','dhcp.lan.ndp':'disabled','dhcp.lan.ra_slaac':'0','dhcp.@dnsmasq[0].filter_aaaa':'1','firewall.hkc_lan_ipv4_only':'rule','firewall.hkc_lan_ipv4_only.name':'HKC LAN IPv4 only','firewall.hkc_lan_ipv4_only.src':'lan','firewall.hkc_lan_ipv4_only.dest':'wan','firewall.hkc_lan_ipv4_only.family':'ipv6','firewall.hkc_lan_ipv4_only.proto':'all','firewall.hkc_lan_ipv4_only.target':'REJECT','firewall.hkc_lan_ipv4_only.enabled':'1'}
        after={**before,**delta};del after['network.lan.ip6assign']
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);state=root/'state.json';shim=root/'uci';shim.write_text('#!/bin/sh\nexec "$HKC_TEST_PYTHON" "$HKC_TEST_FILE" --uci "$@"\n');shim.chmod(0o755)
            env=dict(os.environ,HKC_TEST_STATE=state.as_posix(),HKC_TEST_FILE=Path(__file__).resolve().as_posix(),HKC_TEST_PYTHON=Path(sys.executable).as_posix())
            posix=root.as_posix()
            if os.name=='nt':posix='/'+posix[0].lower()+posix[2:]
            fixture='export PATH='+shlex.quote(posix)+':"$PATH"\nboard_name() { printf "%s\\n" "$HKC_TEST_BOARD"; }\n'+source
            def check(label,start,end,ok=True,board='jdcloud,ax1800-pro'):
                state.write_text(json.dumps(start));env['HKC_TEST_BOARD']=board
                p=subprocess.run([shell],input=fixture,text=True,env=env,capture_output=True,timeout=60)
                self.assertEqual(p.returncode==0,ok,(label,p.stderr));self.assertEqual(json.loads(state.read_text()),end,label)
            check('legacy bridge exact delta',before,after);check('idempotent',after,after)
            for key,value in [('network.wan.ifname','eth0'),('network.lan.ifname','eth0 eth1 eth3'),('network.lan.type',''),('dhcp.lan.interface','guest'),('firewall.hkc_lan_ipv4_only','zone')]:
                invalid={**before,key:value};check(key,invalid,invalid,False)
            check('wrong board',before,before,False,'other,board')

if __name__=='__main__':
    if sys.argv[1:2]==['--uci']:sys.exit(mock_uci())
    unittest.main()
