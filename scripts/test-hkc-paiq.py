#!/usr/bin/env python3
"""Device-only regression fixtures, no root privileges or router access."""
import importlib.util
import json
import os
from pathlib import Path
import shlex
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid
import zlib

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('image', REPO / 'scripts/verify-hkc-paiq-image.py')
image = importlib.util.module_from_spec(spec)
spec.loader.exec_module(image)
SHELL = os.environ.get('HKC_TEST_SHELL') or shutil.which('bash') or shutil.which('sh')
if os.environ.get('GITHUB_ACTIONS') == 'true':
    assert os.name == 'posix' and shutil.which('mksquashfs') and shutil.which('unsquashfs'), 'CI must run the real SquashFS regression'

def fixture_gpt():
    d = bytearray(34 * 512)
    d[:2] = b'\xebH'; d[510:512] = b'\x55\xaa'; d[450] = 0xee
    struct.pack_into('<I', d, 454, 1)
    d[512:520] = b'EFI PART'; struct.pack_into('<I', d, 524, 92)
    struct.pack_into('<QIII', d, 584, 2, 128, 128, 0)
    for n, (start, count) in image.EXPECTED.items():
        o = 1024 + (n - 1) * 128
        d[o:o+16] = uuid.UUID(image.BIOS if n == 128 else image.LINUX).bytes_le
        d[o+16:o+32] = uuid.UUID(int=n).bytes_le
        struct.pack_into('<QQ', d, o+32, start, start+count-1)
    return recalc(d)

def recalc(d):
    struct.pack_into('<I', d, 600, zlib.crc32(d[1024:]))
    struct.pack_into('<I', d, 528, 0)
    struct.pack_into('<I', d, 528, zlib.crc32(d[512:604]))
    return d

class ImageTests(unittest.TestCase):
    def test_expected_gpt(self):
        self.assertEqual(image.inspect_gpt(fixture_gpt())['partitions']['2'], [131584,1835008])
    def test_corrupt_header(self):
        d=fixture_gpt(); d[540]^=1
        with self.assertRaisesRegex(ValueError, 'header CRC'): image.inspect_gpt(d)
    def test_corrupt_entries(self):
        d=fixture_gpt(); d[1100]^=1
        with self.assertRaisesRegex(ValueError, 'partition CRC'): image.inspect_gpt(d)
    def test_valid_crc_wrong_geometry(self):
        d=fixture_gpt(); struct.pack_into('<Q',d,1184,131585)
        with self.assertRaisesRegex(ValueError, 'layout differs'): image.inspect_gpt(recalc(d))
    def test_missing_bios_partition(self):
        d=fixture_gpt(); d[1024+127*128:]=bytes(128)
        with self.assertRaisesRegex(ValueError, 'layout differs'): image.inspect_gpt(recalc(d))
    def test_non_bootable_mbr(self):
        d=fixture_gpt(); d[:2]=b'\0\0'
        with self.assertRaisesRegex(ValueError, 'BIOS GRUB'): image.inspect_gpt(d)


class BinaryLinkTests(unittest.TestCase):
    LINK = b'lrwxrwxrwx root/root 19 2026-10-31 00:00 squashfs-root/usr/bin/mihomo -> /usr/libexec/mihomo\n'
    TARGET = b'-rwxr-xr-x root/root 64 2026-10-31 00:00 squashfs-root/usr/libexec/mihomo\n'
    ELF = b'\x7fELF\x02' + bytes(13) + b'\x3e\x00' + bytes(44)

    def test_absolute_alternatives_link_reads_in_image_target(self):
        with patch.object(image, 'run', side_effect=[self.LINK, self.TARGET, self.ELF]) as call:
            self.assertEqual(image.read_proxy_binary('fixture.squashfs', 'usr/bin/mihomo'), self.ELF)
            self.assertEqual(call.call_args.args, ('unsquashfs', '-cat', 'fixture.squashfs', 'usr/libexec/mihomo'))

    def test_wrong_link_rejected(self):
        with patch.object(image, 'run', return_value=self.LINK.replace(b'-> /usr/libexec/mihomo', b'-> /tmp/mihomo')):
            with self.assertRaisesRegex(ValueError, 'link missing or incorrect'):
                image.read_proxy_binary('fixture', 'usr/bin/mihomo')

    def test_missing_link_rejected(self):
        with patch.object(image, 'run', return_value=b''):
            with self.assertRaisesRegex(ValueError, 'link missing or incorrect'):
                image.read_proxy_binary('fixture', 'usr/bin/mihomo')

    def test_non_executable_target_rejected(self):
        with patch.object(image, 'run', side_effect=[self.LINK, self.TARGET.replace(b'-rwxr-xr-x', b'-rw-r--r--')]):
            with self.assertRaisesRegex(ValueError, 'target missing or not executable'):
                image.read_proxy_binary('fixture', 'usr/bin/mihomo')

    def test_dangling_target_rejected(self):
        with patch.object(image, 'run', side_effect=[self.LINK, b'']):
            with self.assertRaisesRegex(ValueError, 'target missing or not executable'):
                image.read_proxy_binary('fixture', 'usr/bin/mihomo')

    def test_regular_binary_read_unchanged(self):
        with patch.object(image, 'run', return_value=self.ELF) as call:
            self.assertEqual(image.read_proxy_binary('fixture', 'usr/bin/xray'), self.ELF)
            call.assert_called_once_with('unsquashfs', '-cat', 'fixture', 'usr/bin/xray')

    @unittest.skipUnless(os.name == 'posix' and shutil.which('mksquashfs') and shutil.which('unsquashfs'),
                         'Real SquashFS link regression requires Linux squashfs-tools (mandatory in CI)')
    def test_real_squashfs_absolute_link_and_dangling_target(self):
        with tempfile.TemporaryDirectory(prefix='paiq-link-') as temp:
            base = Path(temp)
            tree = base / 'root'
            (tree / 'usr/bin').mkdir(parents=True)
            (tree / 'usr/libexec').mkdir(parents=True)
            target = tree / 'usr/libexec/mihomo'
            target.write_bytes(self.ELF)
            target.chmod(0o755)
            (tree / 'usr/bin/mihomo').symlink_to('/usr/libexec/mihomo')
            for present in (True, False):
                if not present:
                    target.unlink()
                rootfs = base / ('valid.squashfs' if present else 'dangling.squashfs')
                subprocess.run(['mksquashfs', str(tree), str(rootfs), '-noappend', '-processors', '1', '-quiet'],
                               check=True, stdout=subprocess.DEVNULL)
                if present:
                    self.assertEqual(image.read_proxy_binary(rootfs, 'usr/bin/mihomo'), self.ELF)
                else:
                    with self.assertRaises((ValueError, subprocess.CalledProcessError)):
                        image.read_proxy_binary(rootfs, 'usr/bin/mihomo')

class ShellTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='paiq-test-')
        self.root=Path(self.temp.name)
        self.base=self.root.as_posix()
        (self.root/'sysinfo').mkdir()
        (self.root/'sysinfo/board_name').write_text(image.BOARD)
    def tearDown(self): self.temp.cleanup()
    def shell(self, text, env=None):
        return subprocess.run([SHELL,'-c',text],text=True,capture_output=True,env=env)
    def upgrade(self, changed='', valid_meta='0', board=image.BOARD):
        (self.root/'sysinfo/board_name').write_text(board)
        script=(REPO/'target/linux/x86/base-files/lib/upgrade/platform.sh').read_text().split('platform_copy_config()',1)[0]
        script=script.replace('/tmp/',self.base+'/')
        mock='''
get_magic_word() { echo eb48; }
export_bootdevice() { return 0; }
export_partdevice() { diskdev=fixture; }
get_image_dd() { :; }
v() { :; }
ask_bool() { return 1; }
fwtool_check_image() { return META; }
get_partitions() {
  if [ "$2" = 'CHANGED' ]; then
    printf '%2d %5d %7d\\n' 1 512 65536 2 66048 1835008 > 'BASE'/partmap."$2"
  else
    printf '%2d %5d %7d\\n' 1 512 131072 2 131584 1835008 > 'BASE'/partmap."$2"
  fi
}
'''.replace('META',valid_meta).replace('CHANGED',changed).replace('BASE',self.base)
        return self.shell(mock+script+'\nplatform_check_image fixture.img\n')
    def test_upgrade_matching_layout(self):
        r=self.upgrade();self.assertEqual(r.returncode,0,r.stderr)
    def test_upgrade_changed_image(self): self.assertNotEqual(self.upgrade('image').returncode,0)
    def test_upgrade_changed_disk(self): self.assertNotEqual(self.upgrade('bootdisk').returncode,0)
    def test_upgrade_wrong_metadata(self): self.assertNotEqual(self.upgrade(valid_meta='1').returncode,0)
    def test_other_board_unaffected(self): self.assertEqual(self.upgrade('image','1','unrelated-board').returncode,0)
    def test_network_layout(self):
        script=(REPO/'target/linux/x86/base-files/etc/board.d/02_network').read_text()
        script='\n'.join(x for x in script.splitlines() if not x.startswith('. /lib/'))
        mock='board_name() { echo paiq-ec3-bt19d4l; }; board_config_update() { :; }; board_config_flush() { :; }; ucidef_set_interfaces_lan_wan() { printf "%s|%s" "$1" "$2"; };\n'
        r=self.shell(mock+script);self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(r.stdout,'eth1 eth2 eth3|eth0')
    def test_autocore_skips_cpu_count_bitmask(self):
        script=(REPO/'package/lean/autocore/files/x86/autocore').read_text().replace('/tmp/',self.base+'/')
        r=self.shell('uci() { exit 97; }; sysctl() { exit 98; };\n'+script+'\nstart\n')
        self.assertEqual(r.returncode,0,r.stderr)
    def test_defaults_and_retained_settings(self):
        state=self.root/'state.json'
        state.write_text('{}')
        uci=self.root/'uci.py'
        uci.write_text('''import json,os,sys
from pathlib import Path
p=Path(os.environ['STATE']);s=json.loads(p.read_text());a=[x for x in sys.argv[1:] if x!='-q'];c,k=a
if c=='get':
 if k not in s:sys.exit(1)
 print(s[k])
elif c=='set':
 k,v=k.split('=',1);s[k]=v;p.write_text(json.dumps(s))
elif c!='commit':sys.exit(2)
''')
        script=(REPO/'custom/hkc-paiq-defaults.sh').read_text()
        script=script.replace('/tmp/',self.base+'/').replace('/usr/share/hkc/forced-proxy-domains.list',self.base+'/domains').replace('/etc/ssrplus',self.base+'/ssrplus')
        (self.root/'domains').write_text('openai.com\nchatgpt.com\n', newline='\n')
        mock=f'uci() {{ {shlex.quote(sys.executable.replace(chr(92),chr(47)))} {shlex.quote(uci.as_posix())} "$@"; }}\n'
        env=dict(os.environ, STATE=str(state))
        r=self.shell(mock+script,env);self.assertEqual(r.returncode,0,r.stderr)
        s=json.loads(state.read_text());self.assertEqual(s['system.@system[0].hostname'],'XXX')
        self.assertEqual(s['network.globals.packet_steering'],'1')
        self.assertEqual(s['firewall.@defaults[0].flow_offloading'],'0')
        self.assertEqual(s['irqbalance.irqbalance.enabled'],'1')
        self.assertFalse(any(x.startswith('network.lan.') or x.startswith('network.wan.') for x in s))
        s['system.@system[0].hostname']='Customer';state.write_text(json.dumps(s))
        r=self.shell(mock+script,env);self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(json.loads(state.read_text()),s)
        self.assertEqual((self.root/'ssrplus/black.list').read_text(),'openai.com\nchatgpt.com\n')
    def test_other_board_defaults_noop(self):
        (self.root/'sysinfo/board_name').write_text('other')
        s=(REPO/'custom/hkc-paiq-defaults.sh').read_text().replace('/tmp/',self.base+'/')
        self.assertEqual(self.shell('uci() { exit 97; };\n'+s).returncode,0)

if __name__=='__main__': unittest.main(verbosity=2)
