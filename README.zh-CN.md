# FNOS Rescue

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

底层块设备操作仅支持 Linux。Windows 用户未来优先使用 Live USB，WSL2 作为备选；
macOS 用户优先使用 Live USB、Linux 虚拟机直通或另一台 Linux 主机。

## 安全起步

```bash
sudo fnos-rescue inspect /dev/nvme0n1
sudo fnos-rescue protect /dev/nvme0n1 \
  --confirm-serial '检查结果中的序列号' --dry-run
sudo fnos-rescue protect /dev/nvme0n1 \
  --confirm-serial '检查结果中的序列号'
sudo fnos-rescue btrfs-probe /dev/loop16
```

继续前请阅读 [FNOS/Btrfs 恢复流程](docs/FNOS-BTRFS.md) 和
[安全边界](docs/SAFETY.md)。

## 格式扩展

Btrfs、ext4、NTFS、ZFS 的底层结构完全不同。项目统一只读保护、镜像、日志和验证，
但每种文件系统使用独立插件，不会把 Btrfs 方法强行套到其他格式。
