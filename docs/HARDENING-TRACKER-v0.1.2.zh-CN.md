# FNOS Rescue v0.1.2–v0.1.3 安全加固跟踪

本文件是审核后四阶段修复的唯一进度基线。任何阶段只有在实现、负向测试、完整测试和
构建全部通过后才能标记完成。唯一原盘不得用于阶段验收。

## 第一阶段：原盘与权限边界

状态：已完成（2026-07-13）

- 危险元数据辅助脚本必须验证案例所有的 QCOW2、当前 NBD PID、overlay inode、只读 backing。
- 每个源盘任务重新核对序列号、容量、kernel `major:minor` 设备图和所有层只读状态。
- 目标盘通过 kernel 设备身份比较，拒绝别名、分区、MD/LVM/loop 间的同盘关系。
- Web 全部敏感 API 使用主机私有令牌；仅允许 loopback 和本机 Host。
- Web 任务设备与 Chunk Cache 必须属于当前案例；目标只允许管理员批准的恢复根目录。
- fnOS 与 Live 服务把系统目录设为只读，同时为管理员批准的外置盘/网络挂载恢复根保留写权限。

验收证据：74 项 Python 测试通过；Web 生产构建和高危依赖审计通过；Python 编译、Shell
语法、敏感信息扫描、Live profile、非 loopback 监听拒绝及 `git diff --check` 全部通过。

## 第二阶段：恢复正确性与证据绑定

状态：已完成（2026-07-13）

- 校验历史 filesystem/subvolume root 的 FSID、owner、level、generation。
- Chunk Cache 绑定案例、源盘身份、工具版本和 SHA-256，并为 C 解析器增加边界检查。
- 引入按文件类型的完整结构验证；大小和输出自身 SHA-256 不再等同于内容有效。
- 明确区分真正空文件、失败占位、已验证文件和未验证文件。
- 精确路径复制在目标端重新读取并校验；任何失败产生非零退出状态。

验收证据：82 项 Python 测试通过，包含缓存篡改、历史根证据篡改、超界记录/条带数、
截断/尾随数据、结构损坏文件和真实空文件负向测试；Web 生产构建和高危依赖审计通过；
Python 编译、Shell 语法、`git diff --check` 通过。私有 btrfs C 补丁已有静态退化门，真实
Linux 编译与可丢弃磁盘运行验收归入第四阶段，不会在 macOS 上冒充实机结果。

## 第三阶段：端到端与任务可靠性

状态：已完成（2026-07-13）

- 修复 Btrfs 清单绝对路径与 Web 相对路径不一致以及特殊文件名编码。
- 子进程日志持续落盘并并发排空，避免 PIPE 死锁和内存聚集。
- `completed_with_errors` 和任何失败记录不得报告 `ready=true`。
- 消除复制路径 TOCTOU，批量任务使用稳定的 rootid/inode/path 唯一身份。
- 增加 Web 清单到提取、超大输出、ENOSPC、断电/重启和损坏缓存负向测试。

验收证据：91 项 Python 测试通过。新增 Web 清单→特殊文件名→批量提取闭环、4 MB
stdout + 4 MB stderr 并发输出、ENOSPC 临时文件清理、落盘后/步骤提交前断电重试、
过期 worker PID 恢复、源目录 TOCTOU 符号链接替换、损坏缓存/根证据等负向测试。
Web 生产构建、依赖审计、安全扫描、Live profile、Python/Shell 语法和差异检查全部通过。

## 第四阶段：发布与实机验收

状态：已完成（2026-07-13）

- 完整单元、集成、安全扫描、依赖审计、包生命周期与 BIOS/UEFI Live 验收。
- 在可丢弃 Linux 虚拟盘和可清理 fnOS 主机完成端到端验证，不接触旧恢复源盘。
- 启用 GitHub main 分支保护、CodeQL 和 Dependabot 安全更新。
- 重新构建并校验 Wheel、sdist、DEB、fnOS 包、SBOM、SHA256SUMS 和 Live ISO。
- 发布 `v0.1.3` prerelease，取代已发布但随后被深层 CodeQL 数据流继续发现问题的
  `v0.1.2`；旧版本保留 Alpha/已取代语义，不覆盖不可变标签。

最终验收证据：99 项 Python 测试在本地及 GitHub Python 3.11/3.12/3.13 通过；一次性
Btrfs 源镜像以 kernel 只读模式复制到独立 ext4 目标，复制后原镜像逐字节 SHA-256 不变；
DEB 与 fnOS 包安装、回滚、卸载生命周期和干净发布预检通过；Web 生产构建、npm 审计
（0 漏洞）和项目安全扫描通过。`main` 强制 7 项状态检查、管理员保护、线性历史、会话
解决，禁止强推和删除；CodeQL Python/JavaScript 主分支开放告警为 0，主分支记录的
#4–#12 全部以代码修复关闭，没有忽略或豁免。`v0.1.3` 注释标签指向受保护主分支提交；
prerelease 含 8 个
已上传资产（Wheel、sdist、DEB、fnOS 包、CycloneDX SBOM、SHA256SUMS、Live ISO 及其
校验文件）。Live ISO 结构检查与 QEMU BIOS/UEFI 两种启动验证通过；ISO 大小
1,037,041,664 字节，SHA-256 为
`bede855ffb98844c1adf076979fd1025600167735fae39c5fdbad1c9076262df`，与 GitHub 资产摘要
和独立 `.iso.sha256` 文件一致。

发布地址：<https://github.com/superms-lab/fnos-rescue/releases/tag/v0.1.3>
