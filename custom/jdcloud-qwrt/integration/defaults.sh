#!/bin/sh
# Offline-qualified candidate only. No daemon start, network reload or hardware changes.
set -eu
umask 077
[ "$(cat /tmp/sysinfo/board_name)" = jdcloud,ax1800-pro ]
for tool in uci lua flock timeout cmp; do command -v "$tool" >/dev/null; done
exec 9>/var/lock/hkc-qwrt-defaults.lock
flock -n 9
[ ! -f /etc/hkc-qwrt-defaults-v1 ] || exit 0
# Do not discard uncommitted edits from another process.
[ -z "$(uci changes)" ]
work="$(mktemp -d /tmp/hkc-qwrt.XXXXXX)"
done_files=''
finished=0
cleanup() {
    code=$?
    trap - EXIT HUP INT TERM
    if [ "$finished" = 0 ]; then
        for package in $done_files; do
            cp -p "$work/original/$package" "/etc/config/.hkc-$package" &&
                mv -f "/etc/config/.hkc-$package" "/etc/config/$package" || code=1
        done
    fi
    rm -rf "$work"
    exit "$code"
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM
mkdir "$work/original" "$work/stage" "$work/stage/.delta"
for package in network dhcp firewall shadowsocksr ucitrack luci; do
    [ -f "/etc/config/$package" ] && [ ! -L "/etc/config/$package" ]
    cp -p "/etc/config/$package" "$work/original/$package"
    cp -p "/etc/config/$package" "$work/stage/$package"
done
if [ ! -s "$work/stage/shadowsocksr" ]; then
    cp /usr/share/shadowsocksr/shadowsocksr.config "$work/stage/shadowsocksr"
    chmod 600 "$work/stage/shadowsocksr"
fi
lua /usr/libexec/hkc-qwrt-defaults.lua "$work/stage"

for package in network dhcp firewall shadowsocksr ucitrack luci; do
    command uci -q -c "$work/stage" -P "$work/stage/.delta" export "$package" >/dev/null
    cmp -s "/etc/config/$package" "$work/original/$package"
done
[ -z "$(uci changes)" ]
for package in network dhcp firewall shadowsocksr ucitrack luci; do
    cmp -s "/etc/config/$package" "$work/original/$package"
    if ! cmp -s "$work/stage/$package" "$work/original/$package"; then
        cp -p "$work/stage/$package" "/etc/config/.hkc-$package"
        # Include the destination before renaming so signals can roll it back.
        done_files="$package $done_files"
        mv -f "/etc/config/.hkc-$package" "/etc/config/$package"
    fi
done
printf '%s\n' '1' >/etc/.hkc-qwrt-defaults-v1.new
mv /etc/.hkc-qwrt-defaults-v1.new /etc/hkc-qwrt-defaults-v1
finished=1
# Multi-file publication is not power-loss atomic; physical recovery still needs testing.
