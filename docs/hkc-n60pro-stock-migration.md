# N60 PRO 原厂网页迁移：隔离测试构建候选

目标：用户在原厂网页上传专用首次安装包，升级并重启进入 HKC。SSH 仅用于备份、检查和纯校验，不作为交付的刷机方式。

当前状态：源码与离线检查已完成，新增隔离测试构建流程。是否已生成镜像以对应 GitHub Actions 运行和产物验收报告为准；尚未验证实机启动。没有向路由器上传、刷机、重启、修改配置或合并到 master。现有 master 工作流不用于此 target。

基线为 6cb7723430091ab26c3b734b95c743e10eccafa4，独立分支 codex/n60pro-stock-migration。新配置仅切换设备 target，继承稳定 N60 PRO 的应用配置及补丁。稳定 master 和 AX6000 分支保持不变。这代表预期功能相同，不代表新 target 已通过实机验收。

## 原厂证据

- 已检查设备原厂版本 2.0.260529.121244，board 为 mediatek,mt7986a-2500wan-spim-snand-rfb，up_model=N60PRO。
- MTD：BL2 0+1MiB，u-boot-env 1MiB+512KiB，Factory 1.5MiB+2MiB，FIP 3.5MiB+2MiB，ubi 5.5MiB+114.5MiB。
- 当前 slot0；原厂升级程序写 slot1 的 kernel2/rootfs2，并保留原 rootfs_data。
- 原厂网页 CGI 执行 sysupgrade -q -T，通过后自动执行 sysupgrade -c。没有独立的网页上传校验阶段，禁止上传试探。
- 检查时未见 /etc/fw.key 或跳过签名标记。此事实不等于新镜像已经通过原厂校验或 Bootloader 启动验证。
- MTD 环境区和 UBI 环境卷备份均全为 0xff。Bad CRC 表示未保存有效环境，不能据此断言闪存损坏，也不能把内置 bootcmd 当作已保存启动配置。首次升级将由原厂 updater 初始化环境并切槽，此行为未实测。
- 从已核验 UBI 备份重组原厂 kernel 卷：ARM64、LZMA、FIT config-1，load/entry=0x48080000。FIP 内可识别 U-Boot 2022.10。新 Linux 6.12 方案的检查值是 load/entry=0x48000000、ARM64 text_offset=0；必须检查真实编译镜像及启动兼容性，不能机械复制旧地址。

## 已实现的候选逻辑

专用 profile 为 netcore_n60-pro-stock-slot1，compatible 为 netcore,n60-pro-stock-slot1。

1. 内核仅对该 compatible 自动选择 rootfs2。fstools 仅对该 compatible 将 rootfs_data 查找映射到 hkc_data，避免继承原厂设置。
2. 79_hkc_stock_overlay 在挂载 overlay 前校验设备、MTD 布局、UBI 归属与状态、实际 SquashFS 根设备；只创建 hkc_data，复用已有合格卷。8MiB 向上取整为 67 LEB，另留16个可用 LEB。失败不删除或调整原厂卷，并记录 /tmp/hkc-stock-overlay-error；系统可能使用临时内存 overlay，验收必须确认实际持久卷已挂载。
3. 后续维护升级单独校验 tar/CONTROL、镜像类型、尺寸、容量和板卡，仅重建 kernel2/rootfs2/hkc_data。根文件系统先写，内核后写，分别读回核对 SHA256。保留配置归档只恢复至 hkc_data。
4. 写入、读回或配置恢复失败会终止 stage2，避免误报成功和自动重启。此时服务可能已停止，不能保证仍能联网；也不能保证掉电后可启动。未实测恢复前不能交付。
5. LED、网口和双频 Wi-Fi MAC 防冲突规则均沿用 N60 PRO 的板卡逻辑，新增型号分支。首启助手对其他型号和 initramfs 不执行卷创建。
6. scripts/package-hkc-n60pro-stock.py 是离线打包工具：需要维护镜像期望 SHA256、当前设备只读探测结果、fwtool、unsquashfs 以及已准备并应用补丁的 feeds 树。验证 FIT/DTB、分区、载荷、12个已验收运行文件、SSR/UI/默认配置、IPv4-only、中文目录及迁移助手后，才允许生成候选。
7. 不提供 --output 时只校验；提供时输出名必须以 -stock-first-install-slot1.candidate.bin 结尾。首次包只携带原厂 board 与 up_model=N60PRO，维护包只接受新 board，原稳定 N60 PRO 镜像不增加通用 MediaTek 别名。输出标记 release_ready=false，不能把候选标记当作刷写授权。

打包代码已加入，但真实镜像、真实 fwtool 元数据往返和 unsquashfs 完整验收仍待构建后执行。离线 probe 只能反映采集时状态，打包或首次安装前必须重新只读采集。

## 备份与恢复边界

私有备份在主 checkout 的 artifacts/n60pro-stock-audit-20261030/backup，不提交 Git。5个逻辑 MTD 分区已与第二次读取 SHA256 核对；另有配置私有归档、设备树和 UBI 环境卷。在线备份不是原子 NAND 镜像，不能按物理偏移盲写恢复。

用户暂无串口工具。原厂槽位保留是恢复设计基础，自动回退、环境持久化、救援入口均未验证。维护升级原地覆盖 slot1，并非具备原子切换能力的 A/B 升级。不能承诺断电安全，也不能把此研究候选作为商业生产固件。串口是可能的恢复验证手段，正常交付流程仍以网页升级为目标。

## 离线验证方法

- scripts/test-hkc-n60pro-stock.py：稳定源码隔离、配置一致性、硬件及容量负例、shell 语法、平台分流和 stage2 失败退出。--references 配合 --patch-tool 检查 Linux 6.12.95 与固定 fstools 源码零 fuzz 应用。
- scripts/test-hkc-n60pro-runtime.py：合成 FIT/DTB、元数据隔离、tar 成员拒绝、模拟 MTD/挂载状态、overlay 创建与复用、空间边界、11处写操作故障、根/内核读回不符、配置恢复失败、其他型号/initramfs 隔离和 Wi-Fi MAC 对比。所有写入工具均被模拟，不连接路由器。
- scripts/test-hkc-n60pro-build.py：验证固定 feeds、稳定版构建和验收步骤没有遗漏，仅选择候选 target，并检查真实镜像验证失败时不生成成功报告。合计27项 unittest，另有 shell 和补丁检查。
- Windows 需 Python 3 和 Git Bash；受限沙箱不能启动 Git Bash 时，不能把此主机限制误判为源码失败。
- scripts/hkc_n60pro_stock_check.py 始终返回 release_ready=false。源测试与零 fuzz 不等于交叉编译、实际镜像验收或实机启动通过。

## 下一阶段关口

### 2026-10-30 维护候选更新

v2 原厂首次安装包已经实机启动到 slot1，kernel2/rootfs2 与候选载荷一致，hkc_data 挂载正常，开机自动校时及基本 DNS/联网通过。此前普通 netcore,n60-pro 固件不适用于此布局。此结果不等于新的维护升级、恢复或长期稳定性已验收。

本次独立分支将以下修复一起纳入维护镜像构建：

- 专用 profile 在 append-metadata 前补齐 FIT /rootfs size、CRC32、SHA1，按 SquashFS bytes_used 校验；验收拒绝缺失绑定的旧包。
- 新增 31_hkc_stock_env：只在此专用板型与已确认活动根卷下，通过 UBI 卷名发现 u-boot-env；校验尺寸、字符设备、环境读取成功及 current_slot=1 后才生成 /etc/fw_env.config。它不调用 fw_setenv，不切换槽位。保留旧版空 /etc/config/ubootenv 也会执行；已有不匹配配置不覆盖。
- fstools block 的 extroot 探测在此专用板型上使用 hkc_data，MTD和UBI路径都不再探测原厂 rootfs_data；其他板型沿用原路径。保留 extroot 功能，不靠关闭它来绕开问题。
- 增加离线 shell 桩件和实际 C 控制流编译测试，覆盖旧配置升级、读取失败、其他板型及卷缺失，不在测试中执行真实挂载或闪存写入。
- 12个已验收稳定性/校时运行文件、订阅UI、LAN IPv4-only、后台192.168.8.1、无线默认和固定feeds均不改变。

当前 CI 只输出 stock-slot1 维护测试包，不是原厂网页首次包，也不能用于普通稳定版 N60 PRO 或 AX6000。产物仍需实际解包校验、保留配置升级与恢复测试；未经用户授权不得刷机或重启。

1. 使用独立 .github/workflows/hkc-n60pro-stock.yml 构建新 target：推送 hkc-n60pro-stock-test-* 专用标签触发；不监听 master 或其他分支推送。并发组固定，cancel-in-progress=false。固定 feeds、应用补丁和稳定版产物验收均保留。
2. 构建末尾运行 scripts/verify-hkc-n60pro-stock-build.py 检查真实 FIT/DTB 与运行文件，再上传专用 research artifact，包含 manifest、diffconfig、profiles、镜像及 ARTIFACT-SHA256SUMS。专项报告记录完整源码提交、实际载荷大小和所需 LEB；真实设备剩余容量仍需重新只读检查。本流程不生成原厂网页首次安装包。
3. 明确可验证的 Bootloader 恢复路径，评估当前没有串口时的首次启动风险。
4. 对最终候选只使用明确的 sysupgrade -T 纯校验路径；不取消签名检查、不强刷、不在网页上传试探。校验通过本身不证明可启动。
5. 只有最终授权后才网页升级，验证首次启动、配置持久化、网络/无线/代理/DNS/自动校时和后续维护升级。未经这些验收不标为正式版。
