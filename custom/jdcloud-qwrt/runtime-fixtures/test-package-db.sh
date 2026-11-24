#!/bin/ash
# Reads synthetic/metadata-only guest files; never runs opkg install/update/remove.
set -eu
# Preserve no original private config; satisfy status stat() calls with empty fixtures.
for file in /etc/ssrplus/netflix.list /etc/ssrplus/oversea_list.conf; do
 [ -e "$file" ] || : >"$file"
done
opkg list-installed >/tmp/opkg-installed.txt 2>/tmp/opkg-query-errors
[ ! -s /tmp/opkg-query-errors ]
opkg status luci-app-ssr-plus >/tmp/opkg-ssr-status.txt 2>/tmp/opkg-query-errors
[ ! -s /tmp/opkg-query-errors ]
opkg files coreutils-timeout >/tmp/opkg-timeout-files.txt 2>/tmp/opkg-query-errors
[ ! -s /tmp/opkg-query-errors ]
grep -q '/usr/bin/gnu-timeout' /tmp/opkg-timeout-files.txt
grep -q '/usr/bin/timeout' /tmp/opkg-timeout-files.txt
lua - <<'EOF'
local json=require('luci.jsonc')
local f=assert(io.open('/PACKAGE-DB-EXPECTED.json'));local expected=assert(json.parse(f:read('*a')));f:close()
local got={};local n=0
for line in io.lines('/tmp/opkg-installed.txt') do
 local p,v=line:match('^(%S+) %- (%S+)$')
 assert(p and v and not got[p], 'unexpected opkg output');got[p]=v;n=n+1
end
assert(n==expected.total_packages, 'package count mismatch')
for name,version in pairs(expected.packages) do assert(got[name]==version,'package version mismatch: '..name) end
local s=assert(io.open('/tmp/opkg-ssr-status.txt')):read('*a')
assert(s:match('Status: install hold installed'),'SSR hold status missing')
print('PACKAGE_DB_NATIVE PASS',n)
EOF
