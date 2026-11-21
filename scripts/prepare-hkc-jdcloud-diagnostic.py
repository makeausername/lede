#!/usr/bin/env python3
"""Stage board-scoped diagnostic files; never access a router or relax baseline gates."""
import os, re, shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def prepare(root, password):
    if not re.fullmatch(r'[A-Za-z0-9]{8,63}',password):
        raise ValueError('Missing or invalid build Wi-Fi secret')
    config=(root/'.config').read_text()
    if 'CONFIG_TARGET_qualcommax_ipq60xx_DEVICE_jdcloud_re-ss-01=y' not in config.splitlines():
        raise ValueError('Not the dedicated JDCloud build')
    sources={
        'etc/uci-defaults/zz-hkc-minimal-defaults':('defaults.sh.in',0o600),
        'etc/board.d/04_hkc_jdcloud_wifi':('board-wifi.sh.in',0o600),
        'etc/hotplug.d/ieee80211/10-wifi-detect':('wifi-hotplug.sh',0o644),
        'usr/libexec/hkc-jdcloud-boot':('boot-worker.sh',0o755),
        'etc/init.d/hkc-jdcloud-diagnostic':('init.sh',0o755),
    }
    for dest,(src,mode) in sources.items():
        target=root/'files'/dest;target.parent.mkdir(parents=True,exist_ok=True)
        text=(root/'custom/jdcloud-diagnostic'/src).read_text().replace('__WIFI_PASSWORD__',password)
        target.write_text(text,encoding='utf-8',newline='\n');target.chmod(mode)
    module=root/'files/etc/modules.d/ath11k';module.parent.mkdir(parents=True,exist_ok=True)
    module.write_text('ath11k nss_offload=0 frame_mode=2\n',encoding='utf-8')
    link=root/'files/etc/rc.d/S19hkc-jdcloud-diagnostic';link.parent.mkdir(parents=True,exist_ok=True)
    if link.is_symlink(): link.unlink()
    link.symlink_to('../init.d/hkc-jdcloud-diagnostic')
    # Applied after the existing suppression patch, only in this explicit build.
    patch='9100-jdcloud-phy-diagnostics.patch'
    shutil.copyfile(root/'custom/jdcloud-diagnostic'/patch,root/'package/qca/qca-ssdk/patches'/patch)

if __name__=='__main__':
    prepare(ROOT,os.environ.get('WIFI_PASSWORD',''))
    print('JDCloud diagnostic staged: PHY 100ms/100ms, Wi-Fi NSS disabled, bounded worker')
