# FNOS Rescue

> 当前进度：前四个运行阶段已完成，第五阶段 Live 环境工程实现和第六阶段发布加固已完成。ISO 二进制仍必须由 Linux CI 构建并完成虚拟机启动验收后才会作为发行附件提供。

FNOS Basic 单盘 Btrfs 数据恢复开源工具，默认只读、先救数据、可审计、可继续。

## 为什么做这个项目

FNOS 的“删除”和“卸载”在操作体验上不够醒目，而且删除前缺少足够强的元数据备份与
恢复提示。用户点击删除后，硬盘仍能被识别，数据块也可能仍然存在，但卷头、Btrfs
超级块、chunk tree 或 root tree 已无法正常打开。很多用户既不知道从哪里开始，也容易
在焦急时运行会进一步破坏数据的修复命令。

FNOS Rescue 希望把这类恢复变成一套安全、重复、可验证的流程。

## v0.1.0 能做什么

- 显示磁盘型号、序列号、容量、层级和挂载状态。
- 必须输入正确序列号才能将源盘各层设为只读。
- 检查恢复目标是否与源盘重合。
- 为每块盘建立独立 JSON 案例目录。
- 检查三个 Btrfs 超级块镜像。
- 提供高速只读根树扫描器和历史根工具。
- 所有重建元数据只允许写入镜像或 QCOW2 叠加层。
- 对恢复文件进行类型识别、完整读取和 SHA-256 验证。
- 提供 FNOS/Btrfs Codex Skill 和详细 Runbook。

当前版本是 Alpha，不应被宣传为“一键恢复”或“保证 100% 成功”。

## 最重要的安全规则

1. 原盘、分区、MD/LVM 和 loop 每一层都必须只读。
2. 恢复结果必须写到另一块磁盘或网络共享。
3. 不在原盘运行 `btrfs check --repair`、`zero-log`、`mdadm --create`、格式化或读写挂载。
4. 需要写入的实验只能发生在可丢弃的 QCOW2 叠加层中。
5. 文件名和大小正确不等于内容正确，必须检查文件格式并完整读取。

## 开发安装

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
fnos-rescue --version
```

底层块设备操作仅支持 Linux。Windows 用户优先使用 Live USB，WSL2 作为备选；
macOS 用户优先使用 Live USB、Linux 虚拟机直通或另一台 Linux 主机。具体参见
[Windows 使用方式](docs/WINDOWS.zh-CN.md) 与 [macOS 使用方式](docs/MACOS.zh-CN.md)。

## 飞牛 fnOS 原生包

```bash
./scripts/build-fnos-package.sh
tar -xzf dist/fnos-rescue_0.1.0_fnos_x86_64.tar.gz
sudo ./fnos-rescue_0.1.0_x86_64/install.sh
/var/apps/fnos-rescue/bin/fnos-rescue fnos-detect
```

原生安装位置为 `/var/apps/fnos-rescue`。`fnos-quiesce-plan` 默认只输出服务和挂载计划，
不会自动停止飞牛服务；底层 helper 只允许固定诊断与只读保护命令，拒绝任务执行、shell
和解释器。需要 root 的后台任务必须由受控服务或管理员明确启动。

接触块设备前先检查完整运行环境：

```bash
fnos-rescue doctor
```

在 Debian/Ubuntu 上运行 `./scripts/build-deb.sh` 可生成原生 `.deb`；安装包会明确声明
`util-linux`、`file`、`btrfs-progs`、`mdadm` 和 `qemu-utils` 系统依赖。

## 安全起步

```bash
sudo fnos-rescue inspect /dev/nvme0n1
sudo fnos-rescue protect /dev/nvme0n1 \
  --confirm-serial '检查结果中的序列号' --dry-run
sudo fnos-rescue protect /dev/nvme0n1 \
  --confirm-serial '检查结果中的序列号'
sudo fnos-rescue btrfs-probe /dev/loop16
```

持久任务把可续作状态、JSONL 进度和只追加失败清单保存在恢复案例目录中：

```bash
fnos-rescue job-create ./case-001 copy --parameters \
  '{"source_device":"/dev/sda","source_root":"/mnt/recovery-view","destination":"/mnt/recovery","paths":["Photos/2025"]}'
fnos-rescue job-list ./case-001
fnos-rescue job-show ./case-001 job-0123456789ab
fnos-rescue job-run ./case-001 job-0123456789ab --background
fnos-rescue job-control ./case-001 job-0123456789ab pause
fnos-rescue job-control ./case-001 job-0123456789ab resume
```

P1 阶段已接入 `verify` 执行器。创建任务只记录恢复意图，只有明确运行 `job-run` 才会开始或
续作受支持的任务。后台 worker 会在任务目录写入 PID、日志、JSONL 进度和原子结果状态。

经过校验的目录复制使用明确的源目录、目标目录和相对路径列表：

```bash
fnos-rescue job-create ./case-001 copy --parameters \
  '{"source_device":"/dev/sda","source_root":"/mnt/recovery-view","destination":"/mnt/output","paths":["Photos/2025"]}'
```

复制器强制要求提供原始物理 `source_device`，拒绝同盘目标、绝对选择路径、`..` 越界和
符号链接，保留相对目录结构，并在每个文件完成前比较源端和目标端 SHA-256。

在 Linux 上，可以先检查已挂载的本地磁盘、SMB/CIFS 共享或 NFS 目录：

```bash
fnos-rescue destination-inspect /mnt/output --required-bytes 10737418240
```

命令会报告底层来源、挂载点、文件系统类别、只读状态、可写性和可用容量。复制任务在写入
前也会自动执行同一安全检查。

Btrfs 证据采集也可以作为持久任务运行：

```bash
fnos-rescue job-create ./case-001 btrfs-probe \
  --parameters '{"device":"/dev/loop16"}'
fnos-rescue job-create ./case-001 btrfs-root-scan --parameters \
  '{"device":"/dev/loop16","fsid":"11111111-2222-3333-4444-555555555555"}'
fnos-rescue job-run ./case-001 job-0123456789ab --background
```

两种任务都要求 Linux 块设备已经处于只读状态，只采集证据，不挂载、不修复、不改写超级块。

私有 Btrfs v7 工具可以生成可复用 chunk cache、列出历史文件树，并把一个已知 inode 提取到
私密任务目录：

```bash
fnos-rescue job-create ./case-001 btrfs-chunk-cache --parameters \
  '{"device":"/dev/loop16"}'
fnos-rescue job-create ./case-001 btrfs-list --parameters \
  '{"device":"/dev/loop16","chunk_cache":"./case-001/jobs/JOB/chunk-mappings.cache","filesystem_root":123456}'
fnos-rescue job-create ./case-001 btrfs-extract-inode --parameters \
  '{"device":"/dev/loop16","chunk_cache":"./case-001/jobs/JOB/chunk-mappings.cache","filesystem_root":123456,"rootid":257,"inode":9001,"expected_size":4096}'
```

提取结果先进入案例任务目录。将已验证文件送到最终目标仍使用独立 `copy` Job，确保不能绕过
物理同盘检查。

继续前请阅读 [FNOS/Btrfs 恢复流程](docs/FNOS-BTRFS.md) 和
[安全边界](docs/SAFETY.md)。

## 格式扩展

Btrfs、ext4、NTFS、ZFS 的底层结构完全不同。项目统一只读保护、镜像、日志和验证，
但每种文件系统使用独立插件，不会把 Btrfs 方法强行套到其他格式。
