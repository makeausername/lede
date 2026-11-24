# JDCloud QWRT application port: offline integration stage

No router was contacted or modified. No installable package or device firmware is produced. The recovered kernel, NSS, wireless firmware, Ethernet stack, bootloader, LuCI dispatcher and system libraries remain the hardware/runtime base.

## Qualified scope

The original QWRT base is r47727-b292599003, Linux 5.4.250, GCC 7.5.0, musl 1.1.24-2. Its exact vendor SDK remains unverified. The pinned official 19.07.10 mvebu/cortexa53 SDK is only a userspace candidate; never use its kernel, target images or BSP on JDCloud. SDK compilation and QEMU probe passed in runs 44964806075 and 44965663065.

The review generator stages 77 unchanged HKC application/UI/runtime files and 51 legacy-theme files. It verifies all 5271 original regular files and preserves all 12 accepted runtime hashes. It refuses ELF payloads, privileged modes and hardware/core-system destinations. Native dependency candidates stay in a separate locked test pool.

## Rendered incompatibility fixed

Argon 2.3.1 parsed successfully but failed against the actual old dispatcher: `disp.lookup` is absent and its JS menu needs missing `luci.js`. The theme is now pinned to the upstream 18.06 branch, Argon 1.8.4, commit d6dd165802938d455e4967aefd8a95e47773b5d7. It uses the original Lua menu tree and existing cbi.js/xhr.js.

HKC branding is applied with checked source anchors. Login includes are scoped to the theme rather than installing a global header_login template. The upstream init script would rewrite dispatcher.lua; the generator replaces it with board-guarded theme registration only. QWRT already supports theme sysauth. The real authentication/session implementation is not changed or bypassed.

## Native offline evidence

A local QEMU Cortex-A53 virtual machine runs selected, hash-checked original QWRT libc/Lua/LuCI/client files, candidate helpers, synthetic configuration and the HKC review files. It has no NIC, device disks or host shares. It runs a purpose-built test init, never QWRT startup scripts. The test kernel is Alpine 6.12.115-0-virt, NOT the device kernel. Original private configurations are excluded. VM shutdown is unrelated to the physical router.

Passed: 10 Lua/C modules load, YAML parse, 33 original-parser template checks, 10 client/helper version/help checks, SSR TCP/UDP/combined generated configuration startup, and original Xray 25.1.30 validation of generated VLESS/Reality configuration. No external proxy traffic or DNS service was tested.

The original CBI renderer produces English/Chinese subscription and login HTML using synthetic HTTP context, menu tree and board ubus response. A local browser verifies desktop and mobile subscription layouts, no JS errors or missing resources, correct translated headings, aligned time control, and proxy-update unchecked when the setting is absent. Login rendering is not an authentication test. Only the tested pages have this evidence; do not generalize to all pages.

The old SSR 2.5.6-9 binaries are retained: donor SSR requires unavailable OpenSSL 3 functions. The old library's displayed package version differs from its own banner; neither SONAME nor package name alone establishes ABI. No global OpenSSL, libc or liblua replacement is permitted. Version/help execution is not a full protocol or security qualification.

## Reproduction and remaining gates

1. Run `scripts/prepare-hkc-jdcloud-qwrt.py` on the pinned audit/base/donor and legacy theme inputs to a fresh review directory.
2. Run `scripts/build-hkc-jdcloud-qwrt-runtime.py --audit-dir AUDIT --review-dir REVIEW --dependency-dir POOL --output FRESH` to make a RAM-only test archive. It is NOT an uploadable image.
3. Run `scripts/run-hkc-jdcloud-qwrt-runtime.py --qemu QEMU_SYSTEM_AARCH64 --kernel TEST_KERNEL --ramfs ARCHIVE --output FRESH`. It fails unless expected runtime sentinels pass and writes HTML/evidence locally. Do not upload original backups to CI.
4. Eleven isolated port/theme/LAN tests run in `scripts/test-hkc-jdcloud-qwrt.py`; the Linux workflow also performs the pinned SDK probe. Native QWRT tests require local audit inputs and are not claimed as CI tests.

Still required before an installable candidate: full QSDK boot integration (beyond the synthetic tests below), all required protocol/config combinations on the old kernel, all backend pages/actions, rootfs metadata/hardware preservation proof, and a recoverable device boot/traffic test. Current browser tests stub board metadata and background RPC replies; they do not test live services. SDK/QEMU success or sysupgrade acceptance cannot guarantee physical boot. Old upstream software and matching ABI are not a commercial security/support endorsement.


## Boot defaults integration candidate

The accepted health checker needs `timeout`, absent from the recovered rootfs. A pinned official 19.07.10 coreutils-timeout 8.30-2 candidate supplies gnu-timeout plus an explicit timeout symlink. Native old-QWRT tests verify normal exit and timeout status 124; no global libraries are replaced. This is not an opkg installation: package database/dependency records still need integration.

The generic donor SSR initializer changes legacy node types and DNS settings. The generic initializer is disabled in the review assembly; `zzz_hkc-qwrt` performs dedicated initialization after all vendor defaults, including odhcpd.defaults. The dedicated replacement uses the original Lua UCI cursor against private staging copies of six packages. It seeds missing defaults, migrates only missing/667-second intervals to 30, preserves custom intervals, explicit monitor/proxy choices, existing nodes and subscription schedules, and preserves a legacy update hour. Unsupported legacy DNS modes 2/3 fail before any publication rather than silently selecting a different resolver. Empty SSR configuration gets the accepted HKC defaults; a nonempty legacy configuration is not replaced wholesale.

Legacy LAN checks require the exact bridge schema and eth0/eth1/eth2 LAN, eth3 WAN. Only LAN IPv6/DHCPv6/RA, the first dnsmasq AAAA filter and the explicit forwarding rejection rule change. IPv4 address, WAN protocol, WAN6, loopback, wireless and hardware startup remain untouched. The helper registers the SSR firewall include and ucitrack handler. HKC theme selection and LAN policy are applied after all vendor defaults, retaining the chosen language. The complete original boot sequence has NOT been executed.

The helper rejects pending UCI edits, wrong board/layout and conflicting named sections. A lock prevents duplicate instances; configuration files are staged, validated and compared before publication. An injected rename failure proves normal-error rollback. A completion marker makes successful reruns inert. Multiple file renames are NOT power-loss atomic; SIGKILL/power-loss recovery remains a separate gate. No helper starts or restarts services.

The assembly adds only S99hkc-stability/K14hkc-stability links, retaining original SSR, sysntpd, NSS, Ethernet and wireless service order. The original procd Lua-independent shell API emits command `[hkc-ssr-health, daemon]` and the vendor-format respawn array `["3600","5","0"]`; this is a captured registration payload, not an exercised procd daemon respawn. Clock fixtures use original date/flock/parsing/retry code and synthetic HTTPS headers. A NIC-less health-daemon fixture confirms no clock request before WAN readiness and independent clock synchronization without SSR intent. These do not prove real DNS/TLS/NTP/WAN operation.

## Private assembly audit (not firmware)

`scripts/assemble-hkc-jdcloud-qwrt-review.py` verifies the pinned base rootfs/kernel, original regular-file hashes and inode listing, overlays only the review/app integration and locked native candidates, then writes a local private tar. It reads the entire tar back to check content, modes, owners, symlink targets and the console device node. It preserves original protected hardware, non-SSR configuration and startup inodes and rechecks all 12 accepted runtime hashes. Never upload or commit this archive: it includes original private base files.

This tar has no FIT/sysupgrade/container header and is NOT for flashing. The original filesystem has no xattr table. Per-file times are normalized to its build timestamp and hardlink identity is not independently qualified; these need resolution before final SquashFS generation. Package ownership/status, first-boot completeness and existing-node schema compatibility remain unqualified. A firmware that reuses original hardware files still needs recoverable physical boot, LAN/Wi-Fi/NSS, proxy traffic and recovery validation. No claim of a brick-proof or production-ready image is made.

The assembly explicitly replaces only the factory `/etc/config/shadowsocksr` with the pinned HKC template (no selected node, proxy-update off, 30-second monitoring). This distinguishes reset defaults from retained user overlay settings, whose explicit choices are preserved by the migration. The initializer is asserted to sort last after all vendor defaults so odhcpd cannot re-enable LAN RA/DHCPv6 afterwards.


## Package database and SquashFS qualification (2026-11-24)

`scripts/package-hkc-jdcloud-qwrt.py` consumes only the pinned 704da376 integration tar and original rootfs/kernel hashes. `packaging.json` pins metadata controls and the local conversion tools. The tool never uploads, installs or executes package maintainer scripts. Its output names begin PRIVATE-NOT-FIRMWARE and must not be used with a router upgrade interface.

The original SquashFS is converted directly with `sqfs2tar --no-skip --root-becomes .`. Unlike the earlier Windows-oriented manifest, this preserves the root inode, individual timestamps, modes, owners, symlink targets and console device node. The actual original image has no hardlink records or xattr table. Legal Linux filenames containing colons stay inside tar streams; no Windows extraction or alternate data stream is involved. Standard long-name/link PAX records are interpreted; unknown extended attributes, hardlinks, traversal and duplicate paths are rejected.

Two existing SSR packages receive explicit `+hkc.qwrt1` versions. Twelve packages are registered for the tested helpers, Lua binding, Argon and integration. Package status, control files, owned-file lists, MD5 inventories and SSR conffile checksums are reconciled with actual image files. All original unrelated package metadata remains unchanged. The 14 affected packages are marked `install hold installed`, requiring explicit maintenance before later package replacement rather than silently using incompatible feed versions. This is a built-image database reconciliation, not proof that arbitrary opkg upgrades or removals are safe.

The resulting rootfs uses the original XZ compressor and 262144-byte blocks, fixed SOURCE_DATE_EPOCH, and stays below the 300 MiB rootfs partition. It is fully converted back to tar and every inode/content/metadata record compared. 6337 entries round-trip; 6131 original entries remain unchanged in full; 798 protected entries (including the root directory) and all 12 accepted runtime hashes match. Original kernel bytes are checked and kept separate. The new rootfs is 76677120 bytes, SHA256 `bc7a6738004af7d3bf935249a28f7863658d7548bb5c70741d0a9756d0147724`.

Seven archive/control/dependency regression tests complement the existing 11 branch tests. For native verification, `build-hkc-jdcloud-qwrt-runtime.py --package-db PACKAGE-DB-TEST.tar` adds only status/control/list/checksum metadata and the recovered original opkg binary to the NIC-less VM. `run-hkc-jdcloud-qwrt-runtime.py --require-package-db` requires successful original-opkg queries for all 645 installed records, affected versions, SSR hold state and timeout file ownership, without stderr errors. Query fixtures use blank placeholders instead of private configuration. All prior native application, UI rendering and 14 integration checks still run.

This closes the earlier timestamp/ownership and package-database gaps for the offline research rootfs. It does NOT validate mounting with the actual vendor 5.4 kernel, a combined boot/upgrade container, full hardware boot, live NSS/Wi-Fi/ports, every legacy node schema, protocol traffic or recovery. No flashable release is produced. The exact vendor SDK is still unverified; original hardware components remain intact. The previous phase's limitations remain applicable wherever this section does not explicitly supersede them.
