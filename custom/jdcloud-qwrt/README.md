# JDCloud QWRT application port: review stage

This work preserves the recovered QWRT hardware base. It does not build a replacement kernel or a flashable image. The review output is intentionally not installable.

## Pinned base and SDK

The recovered base is QWRT r47727-b292599003, Linux 5.4.250, GCC 7.5.0 (r47716-58e28de107), musl 1.1.24-2. The exact vendor SDK has not been located and verified. The official OpenWrt 19.07.10 mvebu/cortexa53 SDK matches the compiler/libc family and is an application-only candidate. Never use its target image, kernel, modules or BSP for this device.

SDK artifact SHA256 is in profile.json. Cross compilation and qemu-aarch64 execution passed in run 44964806075 at 9135f8fefde7f432bd3a6411e773641066575de2. The probe covers pointer/time sizes, pthread, monotonic clock, flock and dlopen. It runs against SDK libraries, not the extracted QWRT root. Matching 1694 libc export names does not establish complete ABI compatibility.

## Local port prepared

The offline generator verifies the original SquashFS, donor image and all 5271 extracted QWRT regular files. It stages 77 HKC application/UI/runtime files plus 39 pinned legacy Argon Lua theme files, with HKC branding. All 12 accepted runtime hashes are retained. It rejects ELF, privileged modes, path traversal and hardware/core-system destinations. Symlinks and modes are audited as metadata, not reconstructed into a Windows-built image.

Argon 2.3.1 is pinned to f2eb62b34b6be806297ec69dbda7ffb96e16a566 because the donor ucode theme is incompatible with the old Lua rendering stack. Rendering and login behavior are not yet qualified. The legacy LAN policy has isolated, idempotent tests preserving eth0/1/2 LAN, eth3 WAN, the IPv4 address and internal IPv6 loopback; it is a separate research script and is not installed or executed on the device.

## Dependencies and incompatibility found

The eight package names absent from the base have candidate sources recorded in dependency-lock.json. Official IPKs were downloaded with pinned checksums and only their data archives inspected; no package scripts ran. nping, xz and associated libraries pass static symbol closure against the old library set. lyaml requires Lua host exports in addition to DT_NEEDED libraries.

Do NOT copy donor ssr-local or ssr-redir: they import EVP_CIPHER_get_iv_length and EVP_CIPHER_get_key_length, absent from the old OpenSSL 1.1 compatibility shim. A libcrypto.so.3 name in QWRT is not proof of OpenSSL 3 ABI. Retain the QWRT 2.5.6-9 binaries while qualifying their CLI/config contract. Do not upgrade global OpenSSL/libc/liblua to satisfy an application.

The original clients and candidate helper libraries have no unresolved strong symbol names under the checked dependency closure. This is not execution, protocol, TLS, kernel API or security validation. The native candidates are held separately and are not admitted into the review overlay.

## Regression evidence and remaining gates

- 10 port/legacy-LAN regression tests pass locally and on Linux CI.
- All 12 accepted runtime hashes and shell syntax pass; interval migration and time-sync regressions pass locally. Windows has no flock command, so the separate monitor concurrency test is skipped there; the SDK flock probe does not replace it.
- 16 staged Lua scripts compile under Lua 5.1; this is syntax validation, not a LuCI render test.
- No router connection, upload, installation, configuration change, reboot or flash was performed.

Before creating an installable package: validate the full LuCI module/API and template behavior, execute client/config combinations against the old userspace, validate service registration and QSDK-specific defaults, and prove that the eventual root filesystem reconstruction preserves permissions, symlinks and all protected hardware files. Device boot, recovery and real traffic tests remain separate gates. Neither SDK success nor sysupgrade -T establishes boot safety. No new flashable image is produced by this workflow.
