# HKC 京东云 AX1800 Pro 专属测试固件

本分支只面向已只读审计的京东云亚瑟：IPQ6000、1 GiB RAM、64 GB eMMC，旧板型 `jdcloud,ax1800-pro`，现用 QWRT 21.02 / QSDK 12.2。

## 构建与软件

从稳定 N60 master `6cb7723430091ab26c3b734b95c743e10eccafa4` 独立派生。固定 feeds、SSR 协议客户端、Argon 后台、中文/英文、订阅 UI、代理更新默认关闭、30 秒监控与迁移、IPv4-only LAN / 内部 IPv6 回环、开机联网校时均沿用 N60。12 个已验收运行文件必须与稳定 SHA256 清单一致。

配置选择 `configs/hkc-jdcloud-ax1800-pro.config`，管理地址 `192.168.2.1`，主机名 HKC，无线 HKC/HKC-5G，密码使用与 N60 相同的构建 secret 注入。本文件不包含任何私有配置或密码。

WAN 保持物理 dp5 / PHY4，旧称 eth3，新称 wan；三个 LAN 保持 dp2/3/4、PHY1/2/3，新称 lan1/2/3。继承原机型硬件连线，修正旧源码的字符串网络别名为设备树引用，显式描述审计的 1 GiB 内存，保留 NSS/Q6 预留区域与机型无线校准。

## 维护镜像与迁移边界

仅交付名称含 `jdcloud_re-ss-01-squashfs-sysupgrade.bin` 的 tar 维护镜像。不得使用 N60、AX6000、PAIQ、factory/recovery 或整盘镜像。当前 QWRT 的升级脚本将 kernel/root 分别写入 `0:HLOS` / `rootfs`，与本候选一致。

`0:HLOS` 必须是 mmcblk0p16：起始 16418 扇区，长度 12288 扇区（6 MiB）；rootfs 必须是 p17：起始 28706，长度 614400（300 MiB）。内核必须不超过 6 MiB；rootfs 必须按 64 KiB 对齐并为 overlay 保留至少 16 MiB。FIT 必须为 `config@cp03-c2`、ARM64 gzip、load/entry `0x41000000`。不重分区，不写引导环境，不触碰 ART、bootloader、p18 或 p21 数据区。

首次由旧 QWRT 迁移应**不保留旧配置**。旧 `eth0..eth3` 和 QSDK 无线配置不可直接覆盖新配置。保留管理地址和物理端口不代表旧配置文件格式兼容。后续同分支维护升级才可在核验后保留配置。

构建成功与离线验收通过并不代表已获准刷机。交付前还需核对本地下载的 SHA256，并在用户另外授权上传到临时目录后执行现机 `sysupgrade -T`；禁止用 `-F` 绕过失败。旧固件的 platform_check_image 基本放行，故仅此检查通过仍不足以证明可启动。

## 校验和剩余验证

`scripts/test-hkc-jdcloud.py` 校验软件/工作流一致性、分区容量、FIT/DTB、板型兼容、恶意/损坏 tar 拒绝和模拟写失败传播；不访问设备。CI 沿用完整稳定版软件和实际镜像验收，再运行 `verify-hkc-jdcloud-image.py`，生成带提交与镜像 SHA256 的 `JDCLOUD-VERIFICATION.json`，产物清单为 `ARTIFACT-SHA256SUMS`。

现机主 GPT 的头部与分区项 CRC 均有效，但备用 GPT 指针仍指向旧的小容量布局，该位置及物理磁盘末尾均没有有效备用 GPT；现机启动日志也已提示使用主 GPT。此为原有状态，只做备份记录，不自动修复。维护镜像仅写 p16/p17，不覆盖 GPT，实际启动和恢复仍需验证。

新镜像使用 Linux 6.12 / ath11k，与原 QSDK 5.4 无线驱动不同；无线、NSS 与代理共存、首次启动、重启、重置和恢复必须后续实机验证。本候选不是商业正式版。在线全盘备份覆盖原始扇区，但运行中的可写文件系统不等于停机原子快照；RPMB 不属于普通块设备备份范围。

仅 `codex/jdcloud-ax1800-pro` 分支可推进；显式 `hkc-jdcloud-ax1800-test-*` 标签启动专属构建，不触发 N60 的 master 工作流。

## 2026-11-21 诊断候选，尚未允许刷机

旧候选 c5a0cceb6 已发生实机失联并撤回；原 QWRT 已由用户恢复。缺少失败启动串口日志，以下是有证据的兼容性修复和隔离实验，不是已确认的唯一根因。

* 仅 HKC 专用 DTS 把 MDIO PHY reset hold/settle 设为各 100000us，对齐恢复固件中的约 100ms/100ms。基础 DTS、PHY 地址和网口布局不变。
* 构建阶段只为本候选追加 SSDK 诊断补丁，恢复被上游补丁屏蔽的缺失 PHY 报错，并限速避免刷屏。不调整 NSS 固件版本、内存布局或模块依赖顺序。
* 保留编译的 NSS 支持和有线 DP；镜像加载参数固定为 `ath11k nss_offload=0 frame_mode=2`。这隔离无线 NSS 初始化硬依赖，可能降低无线吞吐，不能据此承诺性能。
* 主机名和强制代理域名初始化独立完成。S19 procd 后台任务最多等待 120 秒；无线设置在临时 UCI 配置目录校验并提交，成功后请求标准 netifd reload 重读配置，不调用 network restart 或 ifdown；此接口会重新评估网络配置，实机仍需验证有线连接连续性。超时保留待处理标记，下次启动重试；保留用户改动和未提交设置。
* board_detect 提前定义加密 HKC/HKC-5G 默认值；早于 board.json 就绪的无线 hotplug 不生成开放网络。密钥只由现有 secret 注入，相关文件权限为 0600。
* `/tmp/hkc-jdcloud-diagnostic.log` 仅记录模块、端口状态及截断的相关内核日志，不导出 UCI/节点配置，重启即丢失。若内核或 kmodloader 在 S19 前卡住，此文件无法替代串口早期启动日志。

必须完成新增模拟回归、原有升级拒绝/写失败测试、稳定功能校验和实际镜像验收。镜像报告仍保持 `boot_tested=false`、`production_ready=false`。本次只准备离线诊断候选，不上传、刷机或修改设备；后续实机验证需另行授权和恢复准备。
