#!/usr/bin/env python3
"""Offline clock regressions. No network, device config, or system clock writes.

Usage: python3 scripts/test-hkc-time-sync.py SSR_PACKAGE_ROOT [--emit-shell]
The emitted fixture also runs on the target BusyBox shell without Python.
"""
import os
from pathlib import Path
import shutil
import subprocess
import sys

package = Path(sys.argv[1]).resolve()
clock = (package / "root/usr/libexec/hkc-time-sync").read_text()
health = (package / "root/usr/libexec/hkc-ssr-health").read_text()
assert clock.endswith('main "$@"\n')
assert "/etc/init.d/sysntpd restart" not in health
assert "--insecure" not in clock
assert "--proto '=https'" in clock
assert "/var/run/hkc-ntp-synced" not in clock
source = clock.rsplit('main "$@"', 1)[0]
source = source.replace("/var/run/", "$TEST_DIR/run/")
source = source.replace("/etc/hkc-last-good-time", "$TEST_DIR/saved")
source = source.replace("/tmp/hkc-time.", "$TEST_DIR/hkc-time.")
fixture = r'''set -eu
TEST_DIR=$(mktemp -d)
export TEST_DIR
trap 'rm -rf "$TEST_DIR"' EXIT
mkdir "$TEST_DIR/run"
'''+source+r'''
# Functions override external effects; date parsing still uses the native utility.
uptime_s() { cat "$TEST_DIR/uptime"; }
logger() { :; }
flock() { [ "$TEST_CASE" != locked ]; }
date() {
    if [ "$1" = +%s ]; then cat "$TEST_DIR/now"; return; fi
    if [ "$1" = -u ] && [ "$2" = -s ]; then
        echo "$3" >>"$TEST_DIR/date-set.log"
        [ "$TEST_CASE" != set_failure ] || return 1
        echo "${3#@}" >"$TEST_DIR/now"
        return 0
    fi
    # BusyBox supports -D; GNU date can parse the same RFC date without it.
    if [ "$1" = -u ] && [ "$2" = -D ]; then
        command date "$@" 2>/dev/null || command date -u -d "$5" "$6" 2>/dev/null
        return
    fi
    echo 'Unexpected date invocation' >&2
    return 1
}
curl() {
    local file='' url='' value='Wed, 28 Oct 2026 00:10:00 GMT'
    while [ "$#" -gt 0 ]; do
        case "$1" in -D) file="$2"; shift ;; https:*) url="$1" ;; esac
        shift
    done
    echo query >>"$TEST_DIR/queries"
    [ "$TEST_CASE" != tls_failure ] || return 60
    case "$TEST_CASE:$url" in disagreement:*cloudflare*) value='Wed, 28 Oct 2026 00:15:00 GMT' ;; esac
    [ "$TEST_CASE" != bad_date ] || value='not a date'
    printf 'HTTP/1.1 200 OK\r\n' >"$file"
    [ "$TEST_CASE" = no_date ] || printf 'Date: %s\r\n' "$value" >>"$file"
    [ "$TEST_CASE" != stale ] || printf 'Age: 100\r\n' >>"$file"
    if [ "$TEST_CASE" = bad_status ]; then printf 503; else printf 200; fi
}
reset_case() {
    rm -f "$TEST_DIR"/run/* "$TEST_DIR/date-set.log" "$TEST_DIR/saved" "$TEST_DIR/queries"
    echo 1793130800 >"$TEST_DIR/now"
    echo 1000 >"$TEST_DIR/uptime"
}
for TEST_CASE in tls_failure disagreement stale bad_date no_date bad_status; do
    reset_case
    if (main sync); then echo "FAIL accepted $TEST_CASE"; exit 1; fi
    test ! -e "$TEST_DIR/date-set.log"
    test ! -e "$TEST_DIR/run/hkc-time-valid"
    test -e "$TEST_DIR/run/hkc-clock-retry"
    echo "PASS reject $TEST_CASE without setting clock"
done
TEST_CASE=success
reset_case
(main sync)
test "$(cat "$TEST_DIR/now")" = 1793146200
test "$(wc -l <"$TEST_DIR/date-set.log")" -eq 1
test -s "$TEST_DIR/run/hkc-time-valid"
test -s "$TEST_DIR/run/hkc-clock-verified-uptime"
grep -q 'method=https-dual' "$TEST_DIR/run/hkc-clock-synced"
test ! -e "$TEST_DIR/run/hkc-ntp-synced"
echo 'PASS automatic correction with honest HTTPS status'
(main sync)
test "$(wc -l <"$TEST_DIR/queries")" -eq 2
echo 'PASS rate limit skips additional network requests'
echo 1060 >"$TEST_DIR/uptime"
(main sync)
test "$(wc -l <"$TEST_DIR/date-set.log")" -eq 1
echo 'PASS accurate clock is not stepped again'
echo 1120 >"$TEST_DIR/uptime"
TEST_CASE=tls_failure
if (main sync); then exit 1; fi
test -s "$TEST_DIR/run/hkc-time-valid"
echo 'PASS transient failure retains recently verified time'
echo 23000 >"$TEST_DIR/uptime"
if (main sync); then exit 1; fi
test ! -e "$TEST_DIR/run/hkc-time-valid"
echo 'PASS expired verification is invalidated'
reset_case
TEST_CASE=set_failure
if (main sync); then exit 1; fi
test ! -e "$TEST_DIR/run/hkc-time-valid"
echo 'PASS failed clock write is not marked successful'
reset_case
TEST_CASE=success
(main probe)
test ! -e "$TEST_DIR/date-set.log"
test ! -e "$TEST_DIR/run/hkc-time-valid"
echo 'PASS query-only mode never sets time'
reset_case
TEST_CASE=locked
(main sync)
test ! -e "$TEST_DIR/queries"
test ! -e "$TEST_DIR/date-set.log"
echo 'PASS busy lock suppresses duplicate synchronization'
'''

# Exercise the actual supervisor loop; only services, WAN and sleep are mocked.
loop = health[health.index("failures=0\nticks=0\nsleep 20"):]
loop = loop.replace("/var/run/", "$TEST_DIR/run/")
loop = loop.replace("sleep 20", "i=0")
loop = loop.replace("    sleep 30", '    i=$((i+1)); [ "$i" -lt 6 ] || break')
for scenario in ("late_wan", "initial_failure"):
    fixture += "\nreset_case\nrm -f \"$TEST_DIR/calls\"\n"
    fixture += "wan_ready() { " + ('[ "$i" -ge 2 ]' if scenario == "late_wan" else "return 0") + "; }\n"
    fixture += 'clock_check() {\n echo "$i" >>"$TEST_DIR/calls"\n'
    if scenario == "initial_failure":
        fixture += ' [ "$i" -gt 0 ] || { touch "$TEST_DIR/run/hkc-clock-retry"; return 1; }\n'
    fixture += ' echo 1 >"$TEST_DIR/run/hkc-clock-verified-uptime"\n rm -f "$TEST_DIR/run/hkc-clock-retry"\n}\n'
    fixture += loop
    expected = "2" if scenario == "late_wan" else "0 1"
    fixture += 'test "$(tr \'\\n\' \' \' <"$TEST_DIR/calls" | sed \'s/ $//\')" = "' + expected + '"\n'
    fixture += f"echo 'PASS supervisor {scenario}'\n"

if "--emit-shell" in sys.argv:
    print(fixture)
else:
    shell = os.environ.get("HKC_TEST_SHELL") or shutil.which("bash") or shutil.which("sh")
    assert shell, "A POSIX shell is required"
    subprocess.run([shell], input=fixture.encode(), check=True)
