#!/usr/bin/env python3
"""Offline env-config fixtures and compiled extroot control flow. No router access."""
import argparse
import hashlib
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SHELL = '/bin/bash'
CC = 'gcc'
PATCH = 'patch'
ENV = ROOT/'target/linux/mediatek/filogic/base-files/etc/uci-defaults/31_hkc_stock_env'


def q(path):
    s = str(path).replace('\\', '/')
    if len(s) > 2 and s[1:3] == ':/': s = '/' + s[0].lower() + s[2:]
    return shlex.quote(s)


class EnvTests(unittest.TestCase):
    def fixture(self, folder, board='netcore,n60-pro-stock-slot1', existing=None,
                size='1142784', name='u-boot-env', context=0, active=0, slot='1', reader=0):
        def put(path, value):
            f=folder/path; f.parent.mkdir(parents=True,exist_ok=True); f.write_text(value)
        put('tmp/sysinfo/board_name',board)
        put('sys/class/ubi/ubi0_0/name',name)
        put('sys/class/ubi/ubi0_0/data_bytes',size)
        put('dev/ubi0_0','device fixture')
        put('etc/config/ubootenv','')  # Retained empty config from the first image.
        if existing is not None: put('etc/fw_env.config',existing)
        source=ENV.read_text()
        for line in ('. /lib/functions.sh','. /lib/upgrade/nand.sh','. /lib/upgrade/hkc-n60pro-slot1.sh'):
            source=source.replace(line, ':')
        # A regular fixture stands in for the character device; no real device is opened.
        source=source.replace('[ -c "/dev/$volume" ]','[ -f "/dev/$volume" ]')
        for prefix in ('/tmp/','/etc/','/sys/','/dev/'):
            source=source.replace(prefix,folder.as_posix()+prefix)
        mock=f'''hkc_slot1_context() {{ HKC_UBI=ubi0; return {context}; }}
hkc_slot1_active_root() {{ return {active}; }}
hkc_slot1_volume() {{ [ "$1" = u-boot-env ] || exit 90; echo ubi0_0; }}
fw_printenv() {{ [ "$1" = -c ] && [ "$3" = -n ] && [ "$4" = dual_boot.current_slot ] || exit 91; echo {q(slot)}; return {reader}; }}
fw_setenv() {{ exit 92; }}
logger() {{ :; }}
'''
        return mock+source

    def run_script(self, source):
        return subprocess.run([SHELL],input=source,text=True,capture_output=True)

    def test_first_boot_and_preserved_empty_config_idempotent(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp); source=self.fixture(folder)
            result=self.run_script(source);self.assertEqual(result.returncode,0,result.stderr)
            out=folder/'etc/fw_env.config'
            self.assertEqual(out.read_text(),folder.as_posix()+'/dev/ubi0_0 0x0 0x80000 0x80000 1\n')
            before=out.stat().st_mtime_ns
            self.assertEqual(self.run_script(source).returncode,0)
            self.assertEqual(out.stat().st_mtime_ns,before)
            self.assertEqual((folder/'etc/config/ubootenv').read_text(),'')

    def test_other_boards_do_not_create_or_change_config(self):
        for board in ('netcore,n60-pro','xiaomi,redmi-router-ax6000','unknown'):
            with self.subTest(board=board), tempfile.TemporaryDirectory() as temp:
                folder=Path(temp);source=self.fixture(folder,board=board,existing='custom')
                self.assertEqual(self.run_script(source).returncode,0)
                self.assertEqual((folder/'etc/fw_env.config').read_text(),'custom')

    def test_bad_context_volume_or_crc_never_creates_config(self):
        for change in ({'context':1},{'active':1},{'size':'524287'},{'size':'bad'},
                       {'name':'Factory'},{'slot':'0'},{'slot':'1','reader':1}):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temp:
                folder=Path(temp);source=self.fixture(folder,**change)
                self.assertNotEqual(self.run_script(source).returncode,0)
                self.assertFalse((folder/'etc/fw_env.config').exists())
                self.assertEqual(list((folder/'tmp').glob('hkc-fw-env.*')),[])

    def test_existing_unknown_config_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp);source=self.fixture(folder,existing='/dev/mtd1 wrong-layout\n')
            self.assertNotEqual(self.run_script(source).returncode,0)
            self.assertEqual((folder/'etc/fw_env.config').read_text(),'/dev/mtd1 wrong-layout\n')


STUBS = r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define UBIFS_EXTROOT 1
#define MS_NOATIME 1024
#define MNT_DETACH 2
#define LOG_INFO 6
#define ULOG_ERR(...) fprintf(stderr,__VA_ARGS__)
typedef int libubi_t;
struct probe_info {const char *type;};
static const char *board_file, *mode;
static FILE *test_fopen(const char *path,const char *mode_) {
 if(strcmp(path,"/proc/device-tree/compatible")) exit(80);
 return fopen(board_file,mode_);
}
#define fopen test_fopen
#define getenv(n) "1"
static void make_devs(void) {}
static void cache_load(int n) {}
static void ulog_threshold(int n) {}
static int mount_extroot(const char *p) { printf("CONFIG %s\n",p?p:"ROM"); return -1; }
static void find_block_mtd(const char *n,char *p,size_t size) {
 printf("MTD %s\n",n);if(!strcmp(mode,"mtd"))snprintf(p,size,"/dev/mtd-fixture");
}
static struct probe_info *find_block_info(void *a,void *b,const char *c) {
 static struct probe_info p={"jffs2"};return &p;
}
static void mkdir_p(const char *p,int mode_) {}
static int mount(const char *dev,const char *target,const char *fs,int flags,void *data) {
 printf("MOUNT %s %s\n",dev,fs);return 0;
}
static void umount2(const char *p,int flags) {}
static void rmdir(const char *p) {}
static libubi_t libubi_open(void) {return 1;}
static void libubi_close(libubi_t x) {}
static void find_block_ubi(libubi_t x,const char *n,char *p,size_t size) {
 printf("UBI %s\n",n);if(!strcmp(mode,"ubi"))snprintf(p,size,"/dev/ubi-fixture");
}
'''


class ExtrootTests(unittest.TestCase):
    def test_actual_patched_extroot_control_flow(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp); code=folder/'block.c'
            code.write_bytes((ROOT/'scripts/tests/fixtures/hkc-fstools-extroot.c').read_bytes())
            patch_file=ROOT/'package/system/fstools/patches/101-hkc-n60pro-stock-extroot-isolation.patch'
            p=subprocess.run([PATCH,'-p1','--batch','--fuzz=0','-i',str(patch_file)],cwd=folder,capture_output=True)
            self.assertEqual(p.returncode,0,(p.stdout+p.stderr).decode(errors='replace'))
            program=folder/'test.c'
            program.write_text(STUBS+'\n'+code.read_text()+r'''
int main(int argc,char **argv) {
 if(argc!=3)return 90;board_file=argv[1];mode=argv[2];
 main_extroot(2,argv);return 0;
}
''',encoding='utf-8')
            exe=folder/('test.exe' if os.name=='nt' else 'test')
            if CC=='msvc':
                vc=Path('C:/Program Files/Microsoft Visual Studio/18/Community/VC/Auxiliary/Build/vcvars64.bat')
                batch=folder/'build.cmd'
                batch.write_text('@echo off\ncall "'+str(vc)+'" >nul\ncl /nologo /std:c11 /D_CRT_SECURE_NO_WARNINGS "'+str(program)+'" /Fe:"'+str(exe)+'"\n')
                p=subprocess.run(['cmd.exe','/c',str(batch)],cwd=folder,capture_output=True)
            else:
                p=subprocess.run([CC,'-std=c11',str(program),'-o',str(exe)],capture_output=True)
            self.assertEqual(p.returncode,0,(p.stdout+p.stderr).decode(errors='replace'))
            for board in ('netcore,n60-pro-stock-slot1','netcore,n60-pro','xiaomi,redmi-router-ax6000','missing'):
                board_path=folder/'compatible'
                if board!='missing': board_path.write_bytes(board.encode()+b'\0mediatek,mt7986a\0')
                elif board_path.exists(): board_path.unlink()
                for mode in ('ubi','mtd','none'):
                    with self.subTest(board=board,mode=mode):
                        p=subprocess.run([str(exe),str(board_path),mode],capture_output=True,text=True)
                        self.assertEqual(p.returncode,0,p.stderr)
                        expected='hkc_data' if board=='netcore,n60-pro-stock-slot1' else 'rootfs_data'
                        self.assertIn('MTD "'+expected+'"',p.stdout)
                        if mode!='mtd': self.assertIn('UBI '+expected,p.stdout)
                        if mode=='none': self.assertNotIn('MOUNT ',p.stdout)
                        if board=='netcore,n60-pro-stock-slot1': self.assertNotIn('rootfs_data',p.stdout)


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--shell',default=SHELL);ap.add_argument('--cc',default=CC);ap.add_argument('--patch-tool',default=PATCH)
    args=ap.parse_args();SHELL=args.shell;CC=args.cc;PATCH=args.patch_tool
    suite=unittest.defaultTestLoader.loadTestsFromModule(__import__(__name__))
    if not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful():raise SystemExit(1)
