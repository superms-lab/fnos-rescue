# macOS 使用方式

恢复引擎需要 Linux。Intel Mac 可以优先尝试 Live USB；Apple Silicon Mac 建议使用 ARM Linux 虚拟机或把硬盘接到另一台 Linux/fnOS 主机。不同机型的外置启动、安全策略和 USB 直通差异较大，因此不承诺所有 Mac 都能直接从当前 amd64 ISO 启动。

使用虚拟机时，应把整块外置物理硬盘直通给 Linux 客体，不要先让 macOS 挂载源盘。进入 Linux 后先核对型号、容量与序列号，再运行 `fnos-rescue protect`。恢复结果必须写入另一块磁盘或 SMB/NFS 共享。

不要在源盘上运行“急救”、格式化、分区修复或任何写入式文件系统工具。Apple Silicon 的原生 arm64 Live 镜像属于后续发行目标；当前可使用 fnOS 原生包、Debian/Ubuntu arm64 安装或远程 Linux 主机。
