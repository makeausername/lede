#!/bin/sh
# Exercise only the subscription proxy migration, without invoking real UCI.
set -eu

ssr_root=${1:?Usage: test-hkc-subscription-defaults.sh SSR_PACKAGE_ROOT}
block=$(mktemp)
trap 'rm -f "$block"' EXIT

awk '
    index($0, "if ! uci -q get shadowsocksr.@server_subscribe[0].proxy ") { copy = 1 }
    copy { print }
    copy && /^[[:space:]]*fi[[:space:]]*$/ { exit }
' "$ssr_root/root/etc/uci-defaults/luci-ssr-plus" >"$block"
test -s "$block"
sh -n "$block"

uci() {
    test "$1" = '-q'
    case "$2:$3" in
        'get:shadowsocksr.@server_subscribe[0].proxy')
            test "$proxy_value" != missing
            ;;
        'set:shadowsocksr.@server_subscribe[0].proxy=0'|'set:shadowsocksr.@server_subscribe[0].proxy=1')
            proxy_value=${3##*=}
            writes=$((writes + 1))
            ;;
        *) echo "Unexpected UCI operation in proxy migration" >&2; exit 1 ;;
    esac
}

for initial in missing 0 1; do
    proxy_value=$initial
    writes=0
    . "$block"
    if [ "$initial" = missing ]; then
        test "$proxy_value" = 0
        test "$writes" = 1
    else
        test "$proxy_value" = "$initial"
        test "$writes" = 0
    fi
    printf 'PASS: proxy=%s -> %s (%s writes)\n' "$initial" "$proxy_value" "$writes"
done

# New/reset configurations must use the same default as the migration and UI.
awk '
    /^config / { subscribe = ($2 == "server_subscribe") }
    subscribe && $1 == "option" && $2 == "proxy" { print $3 }
' "$ssr_root/root/usr/share/shadowsocksr/shadowsocksr.config" | grep -Fxq "'0'"
grep -A4 'Through proxy update' "$ssr_root/luasrc/model/cbi/shadowsocksr/servers.lua" | grep -Fq 'o.default = "0"'
echo 'PASS: reset template and UI default off'
