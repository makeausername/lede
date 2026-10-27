#!/usr/bin/env python3
"""Run the real defaults script against an isolated UCI command fixture."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def mock_uci():
    state_file = Path(os.environ["HKC_TEST_STATE"])
    state = json.loads(state_file.read_text(encoding="utf-8"))
    args = [arg for arg in sys.argv[2:] if arg != "-q"]
    command, key = args
    if command == "get":
        if key not in state:
            return 1
        print(state[key])
        return 0
    if command == "show" and key == "network":
        for name, value in state.items():
            if name.startswith("network."):
                print(f"{name}={value}")
        return 0
    if command == "set":
        key, value = key.split("=", 1)
        state[key] = value
    elif command == "delete":
        if key not in state:
            return 1
        del state[key]
    elif command == "commit":
        if key not in ("network", "dhcp", "firewall"):
            raise AssertionError(f"Unexpected commit: {key}")
        return 0
    else:
        raise AssertionError(f"Unexpected UCI command: {args}")
    state_file.write_text(json.dumps(state), encoding="utf-8")
    return 0


def main():
    script = Path(sys.argv[1]).resolve()
    # Place WAN before LAN to catch accidental modification of @device[0].
    original = {
        "network.@device[0]": "device",
        "network.@device[0].name": "eth1",
        "network.@device[0].ipv6": "1",
        "network.@device[1]": "device",
        "network.@device[1].name": "br-lan",
        "network.lan.device": "br-lan",
        "network.lan.ip6assign": "60",
        "network.lan.ipaddr": "192.168.8.1",
        "network.lan.netmask": "255.255.255.0",
        "network.wan.proto": "dhcp",
        "network.wan6.proto": "dhcpv6",
        "network.loopback.device": "lo",
        "network.loopback.ipv6": "1",
        "network.globals.ula_prefix": "fd12:3456:789a::/48",
        "dhcp.lan.interface": "lan",
        "dhcp.lan.ra": "server",
        "dhcp.lan.dhcpv6": "server",
        "dhcp.lan.ra_slaac": "1",
        "dhcp.lan.dhcpv4": "server",
        "dhcp.lan.start": "100",
        "dhcp.lan.limit": "150",
        "dhcp.@dnsmasq[0]": "dnsmasq",
        "dhcp.@dnsmasq[0].filter_aaaa": "0",
        "dhcp.@dnsmasq[0].server": "192.0.2.53",
        "dhcp.@dnsmasq[1]": "dnsmasq",
        "dhcp.@dnsmasq[1].filter_aaaa": "0",
        "firewall.@forwarding[0].src": "lan",
        "firewall.@forwarding[0].dest": "wan",
        "wireless.default_radio0.ssid": "unchanged",
        "shadowsocksr.@global[0].global_server": "unchanged",
    }
    # This delta matches the accepted router fix, with LAN's device index moved.
    changes = {
        "network.@device[1].ipv6": "0",
        "dhcp.lan.ra": "disabled",
        "dhcp.lan.dhcpv6": "disabled",
        "dhcp.lan.ndp": "disabled",
        "dhcp.lan.ra_slaac": "0",
        "dhcp.@dnsmasq[0].filter_aaaa": "1",
        "firewall.hkc_lan_ipv4_only": "rule",
        "firewall.hkc_lan_ipv4_only.name": "HKC LAN IPv4 only",
        "firewall.hkc_lan_ipv4_only.src": "lan",
        "firewall.hkc_lan_ipv4_only.dest": "wan",
        "firewall.hkc_lan_ipv4_only.family": "ipv6",
        "firewall.hkc_lan_ipv4_only.proto": "all",
        "firewall.hkc_lan_ipv4_only.target": "REJECT",
        "firewall.hkc_lan_ipv4_only.enabled": "1",
    }
    expected = dict(original, **changes)
    del expected["network.lan.ip6assign"]

    with tempfile.TemporaryDirectory(prefix="hkc-ipv4-test-") as temp:
        root = Path(temp)
        state_file = root / "state.json"
        shim = root / "uci"
        shim.write_bytes(b'#!/bin/sh\nexec "$HKC_TEST_PYTHON" "$HKC_TEST_FILE" --uci "$@"\n')
        shim.chmod(0o755)
        env = dict(os.environ, HKC_TEST_STATE=state_file.as_posix(),
                   HKC_TEST_PYTHON=Path(sys.executable).as_posix(),
                   HKC_TEST_FILE=Path(__file__).resolve().as_posix())
        env["PATH"] = str(root) + os.pathsep + env["PATH"]

        def run_case(label, before, after, success=True):
            state_file.write_text(json.dumps(before), encoding="utf-8")
            result = subprocess.run(["sh", script.as_posix()], env=env,
                                    capture_output=True, text=True, timeout=60)
            assert (result.returncode == 0) == success, (label, result.stderr)
            assert json.loads(state_file.read_text(encoding="utf-8")) == after, label
            print(f"PASS: {label}")

        run_case("exact accepted changes; WAN, IPv4, loopback and other settings preserved", original, expected)
        run_case("reapplying does not add rules or change any additional settings", expected, expected)
        for key, value in (("network.lan.device", "eth1"),
                           ("network.@device[1].name", "other-bridge"),
                           ("dhcp.lan.interface", "guest"),
                           ("firewall.hkc_lan_ipv4_only", "zone")):
            invalid = dict(original, **{key: value})
            run_case(f"invalid {key} rejected before writes", invalid, invalid, False)


if __name__ == "__main__":
    if sys.argv[1:2] == ["--uci"]:
        sys.exit(mock_uci())
    main()
