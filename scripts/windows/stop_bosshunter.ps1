[CmdletBinding()]
param()

$ErrorActionPreference = "Continue"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$RuntimeDir = Join-Path $RepoRoot "data\runtime"
$StateFile = Join-Path $RuntimeDir "bosshunter-processes.json"
$ChromeProfile = Join-Path $RepoRoot ".chrome-profile"

function Stop-ProcessIfRunning([object]$PidValue, [string]$Label) {
    if ($PidValue -and ($PidValue -as [int])) {
        $process = Get-Process -Id ([int]$PidValue) -ErrorAction SilentlyContinue
        if ($process) {
            Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
            Write-Host "Stopped $Label (PID $($process.Id))."
        }
    }
}

$state = $null
if (Test-Path -LiteralPath $StateFile) {
    try { $state = Get-Content -LiteralPath $StateFile -Raw | ConvertFrom-Json } catch { }
}
Stop-ProcessIfRunning $state.web_pid "BossHunter Web"

# Only stop Chrome processes using this repository's dedicated profile.
$profileMarker = "--user-data-dir=$ChromeProfile"
Get-CimInstance Win32_Process -Filter "Name = 'chrome.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and $_.CommandLine.Contains($profileMarker) } |
    ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        Write-Host "Stopped project Chrome process (PID $($_.ProcessId))."
    }

if (Test-Path -LiteralPath $StateFile) { Remove-Item -LiteralPath $StateFile -Force -ErrorAction SilentlyContinue }
Write-Host "BossHunter stopped. Other Chrome windows were not touched." -ForegroundColor Green
