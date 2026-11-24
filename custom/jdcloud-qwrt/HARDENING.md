# JDCloud QWRT offline hardening candidate

This phase supersedes the earlier factory-LAN and maintenance-upgrade gaps only
where the tests below pass. It is not authorization to install a firmware.

## Scope

- `hardening/99_hkc_lan` adds 192.168.2.1/24 to generated board defaults for the
  exact board. The original config generator is unchanged. Existing UCI addresses,
  LAN eth0/eth1/eth2, WAN eth3, and WAN protocol remain intact. No live network
  restart or UCI migration is performed by this hook.
- The private-key cleanup removes an explicit list of original OpenVPN/Easy-RSA
  generated credentials/certificates and the empty Dropbear key placeholder. It
  retains programs and other application configuration. The disabled VPN server
  must receive newly generated credentials before use. Retaining a user's old
  overlay can retain old private keys; this is not an overlay-cleanup service.
- All 12 accepted HKC runtime files, original kernel/FIT/DTB, NSS, Ethernet and
  wireless binaries, libraries and service order remain unchanged.
- Package file lists, conffile hashes, checksums and status are reconciled for
  affected packages, which receive `+hkc.safe1` versions and remain held.

## Maintenance upgrade behavior

The new platform requires the exact board, original 6 MiB kernel partition hash,
the known mmcblk0p16/p17 names and sizes, and an image with the explicit `hkc_qwrt`
metadata contract. Lua checks exact USTAR member order/types, checksums, sizes,
SquashFS format, 64 KiB root alignment, and metadata boundary/length. Original
fwtool checks CRC/board metadata; independently extracted kernel/root SHA256 values
must match. The original hardware kernel must match and is **not rewritten**.

The validated root is staged in RAM before writes. Root write and readback,
ext4 formatting, mount, optional backup copy, sync, unmount and loop detach must
succeed. Errors cause platform_do_upgrade to exit the stage2 shell, preventing
the vendor runner's unconditional completion/reboot tail from executing.
Force-upgrade does not bypass the second check in the maintenance writer.

The retained-backup path accepts a deliberately limited set of regular config
files/directories. Links, special files, traversal and unrelated paths are refused
before writing the root. A normal user's full vendor-generated backup may include
additional files and requires separate review. Synthetic-backup success does not
qualify all retained configurations. Backup rejection in late stage2 occurs after
services have stopped; recoverability/usability of that situation still needs a
physical test. Do not present this as a fully released keep-settings upgrade.

The first migration from original QWRT still runs the original system's installer,
not the new candidate's guarded writer. This candidate cannot retroactively fix
that first installer. Power loss during root writing is not atomic and can still
require U-Boot recovery; no brick-proof claim is made.

## Evidence and limits

`build-hkc-jdcloud-qwrt-hardened.py` consumes the exact pinned previous rootfs tar.
It rejects unplanned changes, newly encountered config private keys, and runtime
hash drift. SquashFS is explicitly padded to 64 KiB, fully round-tripped and
compared before USTAR/fwtool packaging. No sensitive material is printed or pushed.

`verify-hkc-jdcloud-qwrt-hardening.py` independently applies the current source delta
to the pinned prior tree and compares every candidate inode. The unchanged vendor
5.4.250 kernel runs a RAM-only VM with no NIC or host disks/shares. The original UCI
and config generator test factory/reset/custom-address behavior. All regular-file
hashes are checked against the actual mounted candidate. The actual guarded
writer tests reset and synthetic backup preservation on RAM loop devices. Nine
faults cover validation, partition lookup, detach, write, readback, format, mount,
copy and sync, requiring failure and no reboot sentinel.

Test substitutions are explicit: device lookup maps RAM loop devices; detach-all
retains those simulated targets; preparation is tested in full once, then its
validated payload is reused to isolate writer faults; the caller's reboot tail
is a sentinel. Bash syntax alone is insufficient: fixtures also pass the actual
old BusyBox shell. This VM does not exercise the physical IPQ/NSS/Wi-Fi DTB and
does not establish real-device memory headroom, boot, throughput, upgrade or recovery.

Remaining release gates include the original system's first installer, complete
retained-backup compatibility, optional-service default credential policy, live
hardware boot/traffic and recovery. Artifact names remain PRIVATE-OFFLINE-ONLY.
