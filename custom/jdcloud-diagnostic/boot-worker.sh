#!/bin/sh
# Bounded diagnostic worker; never restart network, unload drivers or reboot.
set -u
umask 077
[ "$(cat /tmp/sysinfo/board_name 2>/dev/null)" = 'jdcloud,re-ss-01' ] || exit 0
mkdir /var/run/hkc-jdcloud-boot.lock 2>/dev/null || exit 0
trap 'rmdir /var/run/hkc-jdcloud-boot.lock' EXIT

snapshot() {
	{
		printf 'HKC JDCloud diagnostic v1; elapsed=%s; wifi_nss_expected=0\n' "$elapsed"
		printf 'wifi_nss_actual=%s\n' "$(cat /sys/module/ath11k/parameters/nss_offload 2>/dev/null || echo unavailable)"
		for module in qca_ssdk qca_nss_dp qca_nss_drv ath11k ath11k_ahb; do
			[ ! -d "/sys/module/$module" ] || printf 'module=%s present\n' "$module"
		done
		for name in lan1 lan2 lan3 wan; do
			for attr in operstate carrier speed; do
				value="$(cat "/sys/class/net/$name/$attr" 2>/dev/null)" || value=unavailable
				printf '%s.%s=%s\n' "$name" "$attr" "$value"
			done
		done
		for phy in /sys/class/ieee80211/phy*; do
			[ ! -e "$phy" ] || printf 'radio=%s\n' "${phy##*/}"
		done
		# Kernel driver messages only, never UCI/config dumps or hostapd keys.
		dmesg | grep -Ei 'mdio|qca.?ssdk|qca.?nss|qca807|ath11k|remoteproc|q6v5|firmware.*(fail|error)|phy_addr' | tail -n 120 | cut -c 1-240
	} > /tmp/hkc-jdcloud-diagnostic.log
}

elapsed=0
snapshot
while [ "$elapsed" -le 120 ]; do
	[ -f /etc/hkc-jdcloud-wifi-pending ] || break
	radios=0
	for phy in /sys/class/ieee80211/phy*; do
		[ ! -e "$phy" ] || radios=$((radios + 1))
	done
	if [ "$radios" -eq 2 ]; then
		# Encrypted board defaults are installed by board_detect in S10boot.
		# Standard detection adds missing sections, preserving existing radios.
		wifi config >/dev/null 2>&1
		/bin/sh /rom/etc/uci-defaults/zz-hkc-minimal-defaults --wireless >/dev/null 2>&1
		rc=$?
		case "$rc" in
			0)
				# Ask netifd to reread config after it is ready. No restart/ifdown.
				# The standard reload evaluates all interfaces; only wireless was edited.
				if ubus list network.wireless 2>/dev/null | grep -qx 'network.wireless' && ubus call network reload >/dev/null 2>&1; then
					rm -f /etc/hkc-jdcloud-wifi-pending
					logger -t hkc-jdcloud 'Wireless defaults applied; verify radio and link status'
					break
				fi
				;;
			2)
				rm -f /etc/hkc-jdcloud-wifi-pending
				logger -t hkc-jdcloud 'Existing or changed wireless settings preserved'
				break
				;;
		esac
	fi
	[ "$elapsed" -lt 120 ] || break
	sleep 5
	elapsed=$((elapsed + 5))
done
snapshot
[ ! -f /etc/hkc-jdcloud-wifi-pending ] || logger -t hkc-jdcloud 'Wireless initialization timed out; wired startup was not blocked; retry next boot'
exit 0
