# Webflow Bridge daemon — Windows uninstall (Phase 0.1).
#
#   powershell -ExecutionPolicy Bypass -File tools\uninstall_windows.ps1 [-Purge]
#
# Stops and unregisters the Scheduled Task, removes the installed files. The
# token/audit dir (%USERPROFILE%\.webflow_bridge) is KEPT unless -Purge.
# Idempotent: safe on a machine that was never installed.
#
# !! NOT VERIFIED ON THIS MACHINE !! (authored on macOS) — see docs/INSTALL.md
# "Windows verification checklist".

[CmdletBinding()]
param(
    [string]$TaskName = "WebflowBridgeDaemon",
    [switch]$Purge
)

$ErrorActionPreference = "Stop"
$AppDir = Join-Path $env:LOCALAPPDATA "WebflowBridge"
$TokenDir = Join-Path $env:USERPROFILE ".webflow_bridge"

Write-Host "[uninstall] task=$TaskName"
Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
if (Test-Path $AppDir) { Remove-Item -Recurse -Force $AppDir }

if ($Purge) {
    if (Test-Path $TokenDir) { Remove-Item -Recurse -Force $TokenDir }
    Write-Host "[ok] purged $TokenDir (token + audit)"
} else {
    Write-Host "[keep] $TokenDir (token + audit) - use -Purge to delete"
}
Write-Host "[ok] uninstalled"
