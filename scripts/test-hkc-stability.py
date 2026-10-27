#!/usr/bin/env python3
"""Verify accepted runtime hashes and run isolated shell/default regressions.

Usage: python3 scripts/test-hkc-stability.py SSR_PACKAGE_ROOT
No router access, configuration writes, firmware compilation, or network calls.
"""
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

package = Path(sys.argv[1]).resolve()
repo = Path(__file__).resolve().parents[1]
shell = os.environ.get("HKC_TEST_SHELL") or shutil.which("bash") or shutil.which("sh")
assert shell, "A POSIX shell is required"
manifest = repo / "custom/hkc-stability-runtime.sha256"
count = 0
for line in manifest.read_text().splitlines():
    if not line or line.startswith("#"):
        continue
    digest, rel = line.split(None, 1)
    data = (package / "root" / rel).read_bytes()
    assert hashlib.sha256(data).hexdigest() == digest, f"Accepted runtime drift: {rel}"
    if data.startswith(b"#!/bin/sh"):
        subprocess.run([shell, "-n"], input=data, check=True)
    count += 1
print(f"PASS {count} accepted runtime hashes and shell syntax")

def run_shell(source):
    subprocess.run([shell], input=("set -eu\n" + source).encode(), check=True)

init = (package / "root/etc/init.d/shadowsocksr").read_text(encoding="utf-8")
switch = (package / "root/usr/bin/ssr-switch").read_text(encoding="utf-8")
probe = switch[switch.index("probe_http_ok() {"):switch.index("probe_endpoint() {")]
run_shell(probe + """
for code in 200 204 299; do probe_http_ok "$code"; done
for code in 000 100 301 403 451 500 599 garbage; do
    if probe_http_ok "$code"; then exit 1; fi
done
echo 'PASS health rejects errors and redirects'
""")

firstboot = (package / "root/etc/uci-defaults/luci-ssr-plus").read_text(encoding="utf-8")
begin = firstboot.index("    # HKC stability: migrate")
end = firstboot.index("    # HKC stability interval migration end.", begin)
migration = firstboot[begin:end]
run_shell("""
uci() {
    test "$1" = -q
    case "$2:$3" in
        'get:shadowsocksr.@global[0].switch_time')
            [ "$interval" != missing ] || return 1
            printf '%s\\n' "$interval" ;;
        'set:shadowsocksr.@global[0].switch_time=30')
            interval=30; writes=$((writes + 1)) ;;
        *) echo 'Unexpected UCI operation' >&2; exit 1 ;;
    esac
}
for initial in missing 667 30 60 300 1800; do
    interval="$initial"
    writes=0
""" + migration + """
    case "$initial" in
        missing|667) [ "$interval" = 30 ]; [ "$writes" = 1 ] ;;
        *) [ "$interval" = "$initial" ]; [ "$writes" = 0 ] ;;
    esac
""" + migration + """
    [ "$interval" = 30 ] || [ "$interval" = "$initial" ]
    case "$initial" in missing|667) [ "$writes" = 1 ] ;; *) [ "$writes" = 0 ] ;; esac
    echo "PASS interval migration $initial -> $interval; idempotent"
done
""")
template = (package / "root/usr/share/shadowsocksr/shadowsocksr.config").read_text(encoding="utf-8")
assert re.search(r"option switch_time '30'", template)
advanced = (package / "luasrc/model/cbi/shadowsocksr/advanced.lua").read_text(encoding="utf-8")
section = advanced.split('"switch_time"', 1)[1].split('o = s:option', 1)[0]
assert "o.default = 30" in section
print("PASS reset template and UI default agree")

# Extract real lock/wrapper logic. Replace only the core preflight and service bodies.
lock = init[init.index("set_lock() {"):init.index("_exit() {")]
wrapper = init[init.index("hkc_service_action() {"):].replace("/usr/libexec/hkc-ssr-preflight", "true")
if shutil.which("flock"):
    run_shell("""
testdir=$(mktemp -d)
trap 'rm -rf "$testdir"' EXIT
LOCK_FILE="$testdir/lock"
TRACE="$testdir/trace"
: >"$TRACE"
""" + lock + """
hkc_start_unlocked() { echo start-begin >>"$TRACE"; sleep 1; echo start-end >>"$TRACE"; }
hkc_stop_unlocked() { echo stop-begin >>"$TRACE"; sleep 1; echo stop-end >>"$TRACE"; }
hkc_reset_unlocked() { :; }
""" + wrapper + """
restart & first=$!
sleep 1
stop & second=$!
wait "$first"
wait "$second"
expected='stop-begin
stop-end
start-begin
start-end
stop-begin
stop-end'
[ "$(cat "$TRACE")" = "$expected" ]
echo 'PASS restart and stop cannot interleave'
""")
else:
    print("SKIP concurrency regression: flock unavailable on this host (run on Linux/BusyBox)")
