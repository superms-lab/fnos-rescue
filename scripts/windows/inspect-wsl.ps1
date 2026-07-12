$ErrorActionPreference = "Stop"

Write-Host "FNOS Rescue WSL2 readiness check" -ForegroundColor Cyan
$status = wsl.exe --status 2>&1
$status | Write-Host
$distributions = wsl.exe --list --verbose 2>&1
$distributions | Write-Host

Write-Host "`nPhysical disks visible to Windows:" -ForegroundColor Cyan
Get-Disk | Select-Object Number, FriendlyName, SerialNumber, OperationalStatus, IsReadOnly, Size | Format-Table

Write-Host "This script does not attach, mount, initialize, format, or change a disk." -ForegroundColor Yellow
Write-Host "Use a Live USB unless you fully understand WSL physical-disk pass-through." -ForegroundColor Yellow
