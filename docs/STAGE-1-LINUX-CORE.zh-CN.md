# 第一阶段：Linux 恢复核心

## 目标

把已经验证过的 FNOS/Btrfs 辅助脚本收进统一的安全状态机，使 Linux 用户可以通过
`rescuectl` 创建案例、只读扫描、列举目录、选择恢复、验证结果并安全清理，不再手写底层命令。

## 工作包与状态

- [x] 设备识别、序列号确认和递归只读保护
- [x] 持久任务、JSONL 进度、失败清单、后台 worker 和断点状态
- [x] 目标盘识别、同盘拒绝、安全复制和内容验证
- [x] Debian/Ubuntu 安装包及 Ubuntu 26.04 实机验收
- [x] Btrfs 超级块探测 Job
- [x] Btrfs 历史根扫描 Job
- [x] 持久 chunk cache Job
- [x] Btrfs 目录列举 Job
- [x] 单 inode 提取 Job
- [x] 选定目录批量提取 Job
- [x] QCOW2、loop、NBD 生命周期与异常清理
- [x] 长任务运行中暂停、取消和续作
- [x] ext4/NTFS 只读诊断插件
- [x] Ubuntu 26.04 实机验收
- [ ] Debian 12/13、Ubuntu 22.04/24.04 兼容矩阵（发布 CI）

## 安全验收

1. 原盘、分区、MD 和 loop 每一层都必须为只读。
2. 任何元数据写入只能发生在明确确认的 QCOW2 overlay。
3. 恢复目标不得位于源物理设备树。
4. 路径选择和输出均拒绝绝对路径、`..` 和符号链接逃逸。
5. 所有后台任务必须可审计、可重试并具有明确清理状态。

## 本轮检查点

已交付 `btrfs-probe` 和 `btrfs-root-scan` 两种 Job。二者只允许读取 Linux 只读块设备，
并把证据写入案例任务目录；不挂载、不修复、不改写超级块。下一检查点是持久 chunk
第一阶段核心实现已完成。Ubuntu 26.04 已验证单元测试、`.deb` 构建、QCOW2 创建、只读
loop backing、NBD 连接/断开和环境清理。Debian 12/13、Ubuntu 22.04/24.04 留给远端发布
矩阵，不阻塞 Linux 核心进入飞牛原生适配阶段。
