# JDCloud QWRT application port: offline runtime stage

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

Still required before an installable candidate: complete QSDK defaults/service integration, all required protocol/config combinations on the old kernel, all backend pages/actions, rootfs metadata/hardware preservation proof, and a recoverable device boot/traffic test. Current browser tests stub board metadata and background RPC replies; they do not test live services. SDK/QEMU success or sysupgrade acceptance cannot guarantee physical boot. Old upstream software and matching ABI are not a commercial security/support endorsement.
