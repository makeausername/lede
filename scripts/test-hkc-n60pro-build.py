#!/usr/bin/env python3
"""Check build isolation and verification rejection paths without building or flashing."""
import argparse
import importlib.util
import re
import subprocess
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SHELL = '/bin/bash'
spec = importlib.util.spec_from_file_location('verify', ROOT/'scripts/verify-hkc-n60pro-stock-build.py')
verify = importlib.util.module_from_spec(spec); spec.loader.exec_module(verify)

def steps(text):
    parts = re.split(r'^      - name: (.+)\n', text, flags=re.M)
    return dict(zip(parts[1::2], parts[2::2]))

def good_metadata():
    return {'supported_devices': [verify.BOARD], 'version': {'target':'mediatek/filogic','board':verify.PROFILE}}

class BuildTests(unittest.TestCase):
    def test_metadata_rejects_legacy_or_factory_identity(self):
        verify.check_metadata(good_metadata())
        for value in ['netcore,n60-pro','mediatek,mt7986a-2500wan-spim-snand-rfb']:
            meta=good_metadata(); meta['supported_devices']=[value]
            with self.assertRaises(ValueError): verify.check_metadata(meta)
        for key,value in [('up_model','N60PRO'),('compat_version','2.0')]:
            meta=good_metadata();meta[key]=value
            with self.assertRaises(ValueError): verify.check_metadata(meta)
    def test_report_requires_every_image_gate(self):
        with tempfile.TemporaryDirectory() as folder:
            image=Path(folder)/'fixture.bin';image.write_bytes(b'fixture')
            with patch.object(verify,'metadata',return_value=good_metadata()), \
                 patch.object(verify,'read_payload',return_value={'kernel':bytes(126977),'root':bytes(126976)}), \
                 patch.object(verify,'check_fit') as kernel, patch.object(verify,'check_root') as root:
                report=verify.verify(image,Path('fwtool'),Path('unsquashfs'),'0'*40)
                self.assertEqual(report['required_free_lebs_before_first_install'],86)
                self.assertFalse(report['release_ready']);self.assertFalse(report['flash_authorized'])
                self.assertEqual(report['verified_stability_runtime_files'],12)
                kernel.assert_called_once();root.assert_called_once()
                kernel.side_effect=ValueError('bad FIT')
                with self.assertRaises(ValueError): verify.verify(image,Path('fwtool'),Path('unsquashfs'),'0'*40)
                kernel.side_effect=None;root.side_effect=ValueError('bad runtime')
                with self.assertRaises(ValueError): verify.verify(image,Path('fwtool'),Path('unsquashfs'),'0'*40)
    def test_stable_build_steps_preserved(self):
        stable=(ROOT/'.github/workflows/openwrt-ci.yml').read_text()
        candidate=(ROOT/'.github/workflows/hkc-n60pro-stock.yml').read_text()
        old,new=steps(stable),steps(candidate)
        for name in ['Checkout firmware source','Free runner disk space','Install build dependencies',
                     'Fetch and pin package feeds','Apply helloworld/luci customizations',
                     'Inject HKC defaults and forced proxy domains','Download source packages','Compile firmware']:
            self.assertEqual(old[name].rstrip(),new[name].rstrip(),name)
        for name in ['PACKAGES_REV','LUCI_REV','ROUTING_REV','TELEPHONY_REV','HELLOWORLD_REV']:
            pattern=rf'^      {name}: ([0-9a-f]{{40}})$'
            self.assertEqual(re.search(pattern,stable,re.M).group(1),re.search(pattern,candidate,re.M).group(1))
        old_check=old['Verify firmware scope and package manifest'].replace('*netcore_n60-pro*','*netcore_n60-pro-stock-slot1*').replace('HKC-N60-PRO-SHA256SUMS','HKC-N60-PRO-STOCK-SLOT1-SHA256SUMS')
        self.assertEqual(old_check.rstrip(),new['Verify firmware scope and package manifest'].rstrip())
    def test_only_new_target_and_dedicated_trigger(self):
        text=(ROOT/'.github/workflows/hkc-n60pro-stock.yml').read_text(); section=steps(text)
        triggers=text.split('on:\n',1)[1].split('permissions:',1)[0]
        self.assertIn('hkc-n60pro-stock-test-*',triggers)
        self.assertIn('      - "codex/n60pro-stock-migration"',triggers)
        self.assertIn('      - ".github/workflows/hkc-n60pro-stock.yml"',triggers)
        self.assertNotIn('master',triggers)
        self.assertNotIn('redmi',triggers)
        config=section['Generate and validate build configuration']
        self.assertIn('cp configs/hkc-n60-pro-stock-slot1.config .config',config)
        self.assertIn("reject_config 'CONFIG_TARGET_mediatek_filogic_DEVICE_netcore_n60-pro=y'",config)
        self.assertIn("require_config 'CONFIG_TARGET_mediatek_filogic_DEVICE_netcore_n60-pro-stock-slot1=y'",config)
        self.assertLess(text.index('- name: Verify stock-slot1 FIT'),text.index('- name: Upload HKC'))
        self.assertNotIn('package-hkc-n60pro-stock.py',text)
        self.assertNotIn('backup/',text);self.assertNotIn('preflight.txt',text)
        self.assertIn('cancel-in-progress: false',text)
    def test_all_run_blocks_have_valid_bash_syntax(self):
        for name,body in steps((ROOT/'.github/workflows/hkc-n60pro-stock.yml').read_text()).items():
            if '        run: |\n' not in body:continue
            block=body.split('        run: |\n',1)[1]
            code='\n'.join(line[10:] if line.startswith('          ') else line for line in block.splitlines())
            result=subprocess.run([SHELL,'-n'],input=code,text=True,capture_output=True)
            self.assertEqual(result.returncode,0,name+': '+result.stderr)

if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--shell',default=SHELL);args=ap.parse_args();SHELL=args.shell
    if not unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(__import__(__name__))).wasSuccessful():raise SystemExit(1)
