# HKC PAIQ J1900 test firmware

Dedicated to PAIQ EC3-BT19D4L, four Intel I211 ports and Legacy BIOS/GPT disk. This is a candidate, not an already device-qualified release.

- WAN eth0 (DHCP); LAN eth1/eth2/eth3, 192.168.2.1/24; hostname XXX.
- GPT kernel partition: sector 512, 64 MiB. Root: sector 131584, 896 MiB. BIOS GRUB embedding partition 128 retained.
- Use only the dedicated squashfs-combined-efi.img.gz image: it contains BOTH BIOS GPT GRUB and UEFI boot components. Never use a rootfs-only image, N60 image or AX6000 image.
- Preserve N60 SSR monitoring, 30-second checks/migration, bilingual subscription UI, proxy update default off, LAN IPv4-only/internal IPv6 loopback and automatic clock sync. No wireless radios exist on this appliance.
- Xray, Mihomo, SS Rust, SSR, NaiveProxy, ShadowTLS, simple-obfs, v2ray-plugin and ChinaDNS-NG remain; KCPTUN and geographic databases are added. HTTP proxy and SS/SSR servers are not enabled.
- Intel microcode, igb and irqbalance; standard netifd packet steering. Skip generic autocore CPU-count-as-bitmask code only on this board. Preserve thermal/power controls and baseline x86_64 compatibility. No AVX/AES-NI assumption, flow offload or forced maximum clock.
- No private credentials or backups are embedded. Reset login follows the existing HKC default-settings package. Retaining settings keeps existing credentials; third-party configuration migration still needs device validation.

Build only via hkc-paiq-j1900-test-* tags on codex/paiq-j1900. Fixed feed revisions and accepted runtime hashes are checked. Artifacts include PAIQ-VERIFICATION.json, manifest, diffconfig, profiles and ARTIFACT-SHA256SUMS.

Before recommending web upgrade: download the exact run, recheck SHA256 and image contents, review the current router image validator and retained-configuration compatibility. Do not force an unsupported image or partition change. This task does not upload, flash, reboot or change the router. First boot, recovery, sustained-load throughput and J1900 instruction compatibility are not device-tested. Local full-disk backup is an online, non-atomic snapshot with a separate verified logical configuration archive, both outside Git. Upstream ptgen omits alternate GPT by default, matching the existing image scheme; primary GPT and exact partition geometry are verified.
