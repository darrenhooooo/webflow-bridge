# Webflow Bridge daemon — one-command Windows install (Phase 0.1).
#
#   powershell -ExecutionPolicy Bypass -File tools\install_windows.ps1
#
# Copies the self-contained daemon into %LOCALAPPDATA%\WebflowBridge\, registers
# a per-user logon Scheduled Task, starts it, then probes GET /status.
#
# Scheduled Task (not a Windows Service) on purpose:
#   * runs as the interactive user with no administrator rights — same
#     user-level semantics as the macOS LaunchAgent and the Linux user unit;
#   * no service account, no SCM registration, no service-recovery config;
#   * starts at logon, where the browser profile and the user's token live.
#   A Windows Service would need admin install and a real service account for
#   no benefit at this stage. Revisit if Phase 2 needs pre-logon/always-on.
#
# Idempotent: an existing task with the same name is replaced in place.
#
# !! NOT VERIFIED ON THIS MACHINE !!  The Phase 0.1/0.2 author works on macOS;
# this script has never been executed on Windows. See docs/INSTALL.md
# ("Windows verification checklist") for exactly what to test before shipping.

[CmdletBinding()]
param(
    [string]$Binary = "",
    [string]$TaskName = "WebflowBridgeDaemon",
    [int]$HttpPort = 10086,
    [int]$WsPort = 10087
)

$ErrorActionPreference = "Stop"
$AppDir = Join-Path $env:LOCALAPPDATA "WebflowBridge"
$Dst = Join-Path $AppDir "webflow-bridge-daemon.exe"
$Repo = Split-Path -Parent $PSScriptRoot

if (-not $Binary) {
    $found = Get-ChildItem -Path (Join-Path $Repo "dist") `
        -Filter "webflow-bridge-daemon-*-windows.exe" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($found) { $Binary = $found.FullName }
}
if (-not $Binary -or -not (Test-Path $Binary)) {
    Write-Error "No daemon binary found. Build one on Windows first: " +
                "python tools\build_standalone.py"
    exit 1
}

Write-Host "[install] task=$TaskName ports=$HttpPort/$WsPort"
Write-Host "[install] binary=$Binary"
New-Item -ItemType Directory -Force -Path $AppDir | Out-Null
Copy-Item -Force $Binary $Dst

# Idempotent: drop any previous task before re-registering.
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
$action = New-ScheduledTaskAction -Execute $Dst `
    -Argument "--http-port $HttpPort --ws-port $WsPort" -WorkingDirectory $AppDir
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME `
    -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName

# Self-check: installed only once /status answers.
function Test-Daemon {
    try {
        $cfg = Invoke-RestMethod -Uri "http://127.0.0.1:$HttpPort/config" -TimeoutSec 2
        if (-not $cfg.token) { return $false }
        $null = Invoke-RestMethod -Uri "http://127.0.0.1:$HttpPort/status" `
            -Headers @{ Authorization = "Bearer $($cfg.token)" } -TimeoutSec 2
        return $true
    } catch { return $false }
}
for ($i = 0; $i -lt 30; $i++) {
    if (Test-Daemon) {
        Write-Host "[ok] daemon alive: http://127.0.0.1:$HttpPort/status"
        Write-Host "[ok] installed to $AppDir (auto-starts at logon)"
        exit 0
    }
    Start-Sleep -Seconds 1
}
Write-Error "daemon did not answer /status on port $HttpPort within 30s"
exit 1
