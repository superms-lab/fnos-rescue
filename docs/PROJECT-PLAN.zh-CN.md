# OpenRescueFS 开源规划（工作名）

## 1. 核心结论

不要只做一个 Skill，也不要只做一个零散脚本。最合适的开源形态是四层组合：

1. **Linux 恢复核心 `rescuectl`**：真正执行设备识别、只读保护、元数据扫描、恢复和验证。
2. **可启动 Live ISO/USB**：让 Windows、macOS、NAS 用户都能进入一致的 Linux 恢复环境。
3. **本地 Web UI**：浏览器中选择磁盘、查看目录、勾选恢复内容和监控速度；所有危险动作仍由核心引擎把关。
4. **AI Skill**：负责解释错误、选择策略、生成计划和引导操作，但不承载核心恢复算法。

Skill 是“懂方法的操作员”，CLI 是“可测试的执行器”，Live ISO 是“跨平台交付物”，Web UI 是“普通用户入口”。

## 2. 产品定位

项目工作名：`OpenRescueFS`；命令行名：`rescuectl`。

目标：

- 帮助因 NAS 删除存储空间、分区表损坏、卷头或关键元数据丢失而无法挂载磁盘的用户。
- 默认目标是**把内容恢复到另一块盘**，不是强行修复原盘并重新上线。
- 支持目录名、文件名、原路径、大小、哈希和失败清单的可审计恢复。
- 面向个人用户、NAS 用户、维修人员和数据恢复研究者。

明确不做：

- 不承诺 100% 恢复。
- 不在原盘上自动执行修复命令。
- 不把文件名存在、文件大小非零当作恢复成功。
- 不把 Btrfs 的根树/设备树办法直接套用到 ZFS、ext4、NTFS。
- 不替代专业实验室处理物理损坏、磁头故障或严重闪存退化。

## 3. 统一恢复流水线

所有文件系统共享下面的安全骨架：

```text
发现设备
  -> 锁定序列号和拓扑
  -> 全层只读保护
  -> 健康检查与是否先做镜像
  -> 识别分区/MD/LVM/文件系统
  -> 创建镜像或 QCOW2 叠加层
  -> 调用文件系统插件
  -> 列目录并选择恢复范围
  -> 抽样完整读取与格式验证
  -> 批量恢复到另一设备
  -> 失败清单与二次策略
  -> 保存案例包并安全解除设备
```

建议命令：

```bash
rescuectl inspect /dev/nvme0n1
rescuectl protect --source /dev/nvme0n1
rescuectl image --source /dev/nvme0n1 --map case.map
rescuectl diagnose --case cases/CASE-ID
rescuectl list --case cases/CASE-ID --depth 1
rescuectl recover --case cases/CASE-ID --path /1000/Photos --dest /mnt/recovery
rescuectl verify --case cases/CASE-ID
rescuectl status --case cases/CASE-ID
rescuectl detach --case cases/CASE-ID
```

每条命令同时输出人类可读文本和 JSON/JSONL，便于 Web UI、Skill 和第三方工具复用。

## 4. 安全机制必须内建

这是项目能否被信任的关键：

- 根据序列号而不是 `/dev/sdX` 名称锁定源盘。
- 整盘、分区、MD、LVM、loop 每一层均检查只读状态。
- 自动拒绝把目标目录放在源盘或其子设备上。
- 所有元数据写入只能发生在镜像或 QCOW2 叠加层。
- 原盘写操作必须在核心层硬编码禁止；不能只依靠文档提醒。
- 禁止默认运行 `btrfs check --repair`、`zero-log`、`mdadm --create`、格式化、读写挂载等命令。
- 执行前展示源盘型号、序列号、容量和完整计划；高风险分支要求输入序列号确认。
- 支持 `--dry-run`，输出将执行的命令、读取范围、预计扫描量和空间需求。
- 物理读错误时优先切换到 GNU ddrescue，并强制使用 mapfile，以便断点续传。
- 每个案例保存工具版本、命令、耗时、速度、哈希、错误和设备事实。
- 日志导出前自动脱敏 SMB 密码、SSH 密码、用户名和私人文件名。

## 5. 架构建议

### 5.1 核心引擎

首版使用 Python 3.11：

- Python 只负责设备编排、状态机、案例文件、任务队列和报告。
- 高速块扫描继续使用 C；以后可逐步改为 Rust，但首版不应为重写而延误发布。
- 原生工具通过子进程调用，不把 btrfs-progs、OpenZFS、TestDisk 等代码链接进核心。
- 每个插件实现统一接口：`probe / diagnose / list / extract / verify / teardown`。
- 后台任务状态写入 `state.json`，进度写入 JSONL，断开终端后任务仍继续。

### 5.2 文件系统插件

```text
plugins/
  btrfs/
  ext4/
  zfs/
  ntfs/
  xfs/
  fat-exfat/
  apfs/
```

插件只负责文件系统特有逻辑；镜像、只读保护、SMB/NFS 目标、日志、验证由核心统一处理。

### 5.3 本地 Web UI

UI 只连接本机 `127.0.0.1`：

- 第一步选择源盘，并明显显示序列号。
- 第二步选择恢复目标并做空间检查。
- 第三步显示检测到的层级：GPT -> MD/LVM -> 文件系统。
- 第四步以文件树形式选择目录。
- 运行页显示已写入容量、实际目标增长、速度、ETA、错误和样本验证。
- 完成页区分：目录项、非空文件、验证文件、失败文件、真正空文件、占用空间。

首版 Web UI 不提供“修复原盘”按钮。

### 5.4 AI Skill

Skill 单独发布，内容保持精简：

- 识别用户描述应进入哪个插件。
- 读取 `rescuectl` JSON 状态并解释。
- 引导用户安全接盘、选目录和理解失败清单。
- 复杂细节放在 `references/btrfs.md`、`ext4.md`、`zfs.md`、`ntfs.md`。
- 确定性扫描、缓存生成、验证必须放在脚本/CLI 中，而不是让 AI 临时重写命令。

## 6. 跨平台交付

| 环境 | 推荐方式 | 支持等级 | 说明 |
|---|---|---:|---|
| 原生 Linux | 直接安装 CLI | 一级 | 最完整、性能最好、最容易保证只读 |
| Windows | Live USB 优先；WSL2 为备选 | 一级/二级 | WSL2 可附加物理磁盘，但硬件、版本和直通限制较多 |
| macOS Intel | Live USB 或 Linux VM 直通 | 二级 | UI 可原生，恢复引擎仍建议 Linux |
| macOS Apple Silicon | Linux VM/另一台 Linux 主机 | 二级 | 外置启动和设备直通差异较大，不承诺所有硬件原生可用 |
| NAS/Linux 服务器 | 原生 CLI 或救援系统 | 一级 | 应停用自动挂载和存储服务后操作 |
| Docker | 仅高级用户 | 三级 | 需要特权和块设备映射，容易误传设备，不作为默认入口 |

真正的跨平台不是把所有低层工具重写三遍，而是让所有平台都能启动同一套 Linux 恢复环境，并通过浏览器使用。

## 7. 文件系统可行性矩阵

| 格式 | 是否可做 | 主要恢复依据 | 主要限制 | 建议优先级 |
|---|---:|---|---|---:|
| Btrfs | 是，当前案例已验证 | 超级块镜像、根树、文件树、chunk tree、device tree、历史根、DUP 元数据 | 元数据/数据块映射都可能被清零；RAID 拓扑更复杂 | P0 |
| ext4 | 是 | 备用超级块、块组描述符、inode、目录块、extent、journal | 删除后目录项和 inode 可能很快复用；日志不保证保留正文 | P1 |
| NTFS | 是 | 主/备启动扇区、MFT、MFTMirr、runlist、日志 | MFT 复用、压缩/加密、碎片化会降低成功率 | P1 |
| ZFS | 是，但完全不同 | labels、uberblocks、MOS、历史 txg、vdev 拓扑、校验和 | 多盘池必须理解拓扑；加密需要密钥；极端回滚风险高 | P2 |
| XFS | 部分可行 | 主/次超级块、AG 元数据、inode btree、目录 btree | 原生“删除恢复”能力较弱；repair 可能产生 lost+found | P2 |
| FAT/exFAT | 是 | 备份引导区、FAT 表、目录项、簇链 | 覆盖后难恢复；长文件名和碎片可能丢失 | P2 |
| APFS | 有限 | 容器超级块、checkpoint、对象映射、快照 | 开源生态弱、结构复杂、加密常见；优先使用 macOS 原生路径 | P3/实验性 |

### 7.1 Btrfs

当前 FNOS 案例可以直接成为首个插件：

- 识别 mdadm data offset 与 Btrfs offset。
- 检查三个超级块镜像。
- 扫描或直接定位历史根树/文件树。
- 从 device tree 生成持久 chunk cache。
- 在 QCOW2 叠加层重建最小可读视图。
- 按 inode/路径恢复并验证文件内容。

但 `1GiB + 8MiB` 物理映射规律只能作为 FNOS 案例中的候选探测，必须用 FSID、logical bytenr、owner、generation、checksum 和 DUP 双副本验证，不能硬编码为通用规则。

### 7.2 ext4

可实现：

- `e2image` 保存关键元数据或创建稀疏/QCOW2 元数据镜像。
- `dumpe2fs`/`debugfs` 做只读检查和 inode/目录提取。
- `e2fsck -n` 只检查；任何真正修复只在克隆或叠加层上进行。
- 搜索备用超级块和历史 journal 线索。
- TestDisk 可辅助寻找备用 ext2/3/4 超级块。

如果只是卷头/主超级块损坏，成功率通常较好；如果是文件删除且 inode、extent 或目录项已复用，无法保证恢复原文件名和目录结构。

### 7.3 ZFS

可实现：

- 首先收集所有池成员和 ZFS labels，不以单盘视角误判多盘池。
- 使用 `zpool import -N -o readonly=on` 只读导入且不挂载数据集。
- 使用 `zpool import -F -n` 预演是否能回退到可导入 txg。
- 用 `zdb` 检查 uberblock、MOS、dataset 和对象。
- checkpoint 或历史 txg 仅在只读视图/克隆中尝试。

`-X` 或指定 `-T` 属于高风险极端恢复，只允许在克隆上执行。ZFS 不能使用 Btrfs 的 chunk/device-tree 重建逻辑。

### 7.4 NTFS

可实现：

- 对比主启动扇区和备份启动扇区。
- 对比 MFT 与 MFTMirr。
- TestDisk 先“List”验证，再决定是否在克隆上重建 boot sector 或修复 MFT。
- 从 MFT 属性和 runlist 恢复原目录和文件数据。
- 对丢失元数据的文件再进入 PhotoRec/签名雕刻，但必须单独标记为“无原路径恢复”。

Windows `chkdsk` 会修改文件系统，不应成为默认第一步。

## 8. 案例包标准

每块盘创建独立案例目录：

```text
cases/CASE-ID/
  case.yaml
  device-facts.json
  topology.json
  superblocks/
  scans/
  mappings/
  inventories/
  validation/
  logs/
  failed-files.tsv
  recovered-files.tsv
  report.html
```

`case.yaml` 必须记录：

- 源盘型号、序列号、容量和扇区大小。
- 分区、MD、LVM、文件系统偏移。
- FSID/UUID、文件系统类型和工具版本。
- 镜像、叠加层和恢复目标。
- 每一步的状态、耗时、速度和可继续点。
- 是否有物理 I/O 错误。

案例包默认不保存密码，不公开真实私人文件名。社区提交故障案例时提供可脱敏的元数据镜像和日志。

## 9. 仓库结构

```text
openrescuefs/
  README.md
  LICENSES/
  rescuectl/
  plugins/
    btrfs/
    ext4/
    ntfs/
    zfs/
    xfs/
    fat_exfat/
  helpers/
    scan-btrfs-roots/
  ui/
  live/
  skill/
    SKILL.md
    references/
  schemas/
  tests/
    generated-images/
    corruption-fixtures/
  docs/
```

测试镜像必须由脚本生成，不上传用户真实磁盘内容。每个插件至少覆盖：主超级块清零、分区表丢失、目录树损坏、部分数据块不可读和目标空间不足。

## 10. 开源许可

建议：

- 自研 orchestrator、Web UI 和协议：Apache-2.0。
- 当前修改过的 btrfs-progs 源码/补丁：按其 GPL-2.0 要求独立存放和发布。
- TestDisk、OpenZFS、e2fsprogs 等保持外部依赖，通过命令行调用，不复制进核心库。
- Live ISO 的第三方包保留各自许可证和源码获取说明。
- 发布前做一次正式许可证审查，尤其注意 GPL-2.0 与 OpenZFS CDDL 的边界。

## 11. 分阶段路线

### P0：整理当前成果

- 将现有 `recover-fnos-btrfs-disks` 脚本移入独立仓库。
- 清除密码、IP、用户名和真实私人路径。
- 把三块真实盘的成功步骤抽象成参数，不硬编码序列号和地址。
- 固化案例 schema、只读守卫和失败清单格式。

验收：在人工生成的 FNOS/Btrfs 损坏镜像上，能够列第一层目录、选择单一目录恢复、验证内容并安全解除设备。

### P1：Linux CLI MVP

- 发布 `rescuectl`。
- 完成 Btrfs 插件和 ext4/NTFS 的只读诊断插件。
- 支持本地盘、SMB/NFS 目标、后台任务和断点状态。
- 提供 Debian/Ubuntu 安装包。

验收：普通 Linux 用户只需提供源盘和目标目录，不需要手写底层命令。

### P2：Live ISO 与 Web UI

- 构建可启动 ISO/USB。
- 自动关闭 automount，启动本地 Web UI。
- 支持在 Windows/macOS 机器上通过重启进入恢复环境。
- 提供日志打包和脱敏导出。

验收：没有 Linux 环境的用户可以从 U 盘启动并完成目录选择恢复。

### P3：更多文件系统

- ext4 完整插件。
- NTFS 完整插件。
- ZFS 只读 import/zdb 插件。
- XFS、FAT/exFAT 诊断与恢复插件。

每个插件独立标注成熟度：`experimental / beta / stable`，不能用“支持”二字掩盖恢复能力差异。

### P4：社区与可持续维护

- 发布生成式损坏镜像测试集。
- 建立“设备拓扑 + 错误日志 + 脱敏元数据”Issue 模板。
- 建立安全披露和不可恢复边界说明。
- Skill 只从稳定 CLI 和插件文档生成，避免 Skill 与工具行为漂移。

## 12. 第一版最值得做的内容

第一版不要追求所有格式。建议只交付：

1. FNOS Basic 单盘 Btrfs。
2. 主/次超级块被清零、第三镜像保留的场景。
3. chunk root 被清零但 root tree/device tree 可找回的场景。
4. 第一层目录浏览、按目录恢复、样本验证、错误清单。
5. Linux CLI + Live ISO；Web UI 只做最小流程。

这是已经被真实硬盘验证过的差异化能力。ext4、NTFS、ZFS 应在框架稳定后分别开发，不应为了“全格式”降低第一版可靠性。

## 13. 参考依据

- Btrfs restore：<https://btrfs.readthedocs.io/en/latest/btrfs-restore.html>
- Btrfs rescue：<https://btrfs.readthedocs.io/en/stable/btrfs-rescue.html>
- GNU ddrescue：<https://www.gnu.org/software/ddrescue/manual/ddrescue_manual.html>
- QEMU NBD：<https://www.qemu.org/docs/master/tools/qemu-nbd.html>
- WSL 物理磁盘：<https://learn.microsoft.com/en-us/windows/wsl/basic-commands>
- ext4 e2image：<https://man7.org/linux/man-pages/man8/e2image.8.html>
- ext4 e2fsck：<https://man7.org/linux/man-pages/man8/e2fsck.8.html>
- OpenZFS zpool import：<https://openzfs.github.io/openzfs-docs/man/v2.0/8/zpool-import.8.html>
- TestDisk 文档：<https://www.cgsecurity.org/testdisk.pdf>
- XFS metadump：<https://man7.org/linux/man-pages/man8/xfs_metadump.8.html>
- XFS repair：<https://man7.org/linux/man-pages/man8/xfs_repair.8.html>
- exfatprogs：<https://github.com/exfatprogs/exfatprogs>
