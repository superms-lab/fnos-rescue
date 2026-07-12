# 第五阶段：跨平台 Live 恢复环境

状态：工程实现完成；ISO 二进制等待 Linux CI/发行构建。

## 已完成

- Debian Bookworm `amd64` hybrid ISO 的 Live Build 配置。
- Live 环境预装 Btrfs、MD RAID、QCOW2、ext4、NTFS、SMART、TestDisk 与 GNU ddrescue 工具。
- 启动后提供同一套 FNOS Rescue Web 控制台，服务仍只监听 `127.0.0.1:8790`。
- systemd 服务采用 `NoNewPrivileges`、只读系统保护和有限可写目录。
- 独立的 profile 校验脚本，拒绝在 Live 配置中出现修复、格式化或重建阵列命令。
- GitHub 手动/Tag 构建任务，生成 hybrid ISO 与 SHA-256，并在 Tag 构建时上传 prerelease。
- Windows WSL2 只读诊断脚本，不自动执行物理盘直通。
- Windows Live USB 与 macOS Intel/Apple Silicon VM/直通说明。

## 本机验证边界

macOS 不能运行 Debian `live-build`，所以当前本机已完成 profile 校验、51 项自动化测试和构建脚本审查，但没有伪造一个“已构建”的 ISO。实际 ISO 必须在 Debian/Ubuntu 或 GitHub Actions 上生成，然后在虚拟机中完成启动、浏览器自动打开、设备枚举和关机清理验收。

现有 Ubuntu 验证机没有可用的非交互 SSH 密钥，因此本阶段没有绕过认证或把密码写进命令日志。发布前的最后外部证据是：Linux 构建日志、ISO SHA-256、UEFI/BIOS 启动截图和一次无源盘写入的虚拟机烟测。
