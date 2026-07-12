# Windows 使用方式

首选方式是把 FNOS Rescue ISO 写入 U 盘，从 U 盘启动电脑，进入统一 Linux 恢复环境。写盘会清空目标 U 盘，因此必须核对 U 盘容量与型号；恢复源盘和恢复目标盘都不能作为启动 U 盘。

WSL2 只作为有经验用户的备选。管理员 PowerShell 可先运行 `scripts/windows/inspect-wsl.ps1`，该脚本仅显示 WSL 状态和磁盘身份，不会附加、挂载、初始化或修改磁盘。不要对待恢复磁盘运行“初始化磁盘”、`chkdsk`、格式化或自动修复。

由于 Windows 版本、USB 桥接芯片和 WSL 直通能力差异很大，本项目不会自动执行 `wsl --mount`。必须确认物理磁盘编号、序列号，并确保 Windows 已离线该磁盘后，才可按微软官方文档手工直通。
