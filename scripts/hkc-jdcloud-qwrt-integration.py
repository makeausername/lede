"""Explicit integration delta for offline review; never a device installer."""
from pathlib import Path

FILES = {
    "usr/libexec/hkc-qwrt-defaults": ("defaults.sh", 0o755),
    "usr/libexec/hkc-qwrt-defaults.lua": ("defaults.lua", 0o644),
    "etc/uci-defaults/luci-ssr-plus": ("ssr-deferred.sh", 0o755),
    "etc/uci-defaults/zzz_hkc-qwrt": ("uci-defaults.sh", 0o755),
}
LINKS = {
    "usr/bin/timeout": "gnu-timeout",
    "etc/rc.d/S99hkc-stability": "../init.d/hkc-stability",
    "etc/rc.d/K14hkc-stability": "../init.d/hkc-stability",
}

def payloads(repo):
    root = Path(repo) / "custom/jdcloud-qwrt/integration"
    result = {}
    for target, (source, mode) in FILES.items():
        data = (root / source).read_bytes()
        if b"\r" in data or data.startswith(b"\x7fELF"):
            raise ValueError("Invalid integration text: " + target)
        result[target] = (data, mode)
    return result
