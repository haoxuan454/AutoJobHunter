[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$RuntimeDir = Join-Path $RepoRoot "data\runtime"
$StateFile = Join-Path $RuntimeDir "bosshunter-processes.json"
$OutputLog = Join-Path $RuntimeDir "web.out.log"
$ErrorLog = Join-Path $RuntimeDir "web.err.log"
$env:PYTHONUTF8 = "1"

New-Item -ItemType Directory -Force -Path $RuntimeDir | Out-Null

function Get-LocalExecutable([string]$RelativePath) {
    $path = Join-Path $RepoRoot $RelativePath
    if (-not (Test-Path -LiteralPath $path)) { throw "Missing project file: $path" }
    return (Resolve-Path -LiteralPath $path).Path
}

function Test-WebReady {
    try { $null = Invoke-WebRequest -Uri "http://127.0.0.1:8686/" -UseBasicParsing -TimeoutSec 2; return $true }
    catch { return $false }
}

function Test-ChromeReady {
    try { $null = Invoke-RestMethod -Uri "http://127.0.0.1:9222/json/version" -TimeoutSec 2; return $true }
    catch { return $false }
}

$Bosshunter = Get-LocalExecutable ".venv\Scripts\bosshunter.exe"
$ChromeCandidates = @(
    (Join-Path ${env:ProgramFiles} "Google\Chrome\Application\chrome.exe"),
    (Join-Path ${env:ProgramFiles(x86)} "Google\Chrome\Application\chrome.exe"),
    (Join-Path $env:LOCALAPPDATA "Google\Chrome\Application\chrome.exe")
) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
if (-not $ChromeCandidates) { throw "Google Chrome was not found." }

$Chrome = $ChromeCandidates | Select-Object -First 1
$ChromeProfile = Join-Path $RepoRoot ".chrome-profile"
$ChromePid = $null
$WebPid = $null

if (-not (Test-ChromeReady)) {
    Write-Host "Starting the project Chrome profile..."
    $chromeProcess = Start-Process -FilePath $Chrome -ArgumentList @(
        "--remote-debugging-port=9222",
        "--user-data-dir=$ChromeProfile",
        "https://www.zhipin.com/"
    ) -PassThru
    $ChromePid = $chromeProcess.Id
    $ready = $false
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Milliseconds 500
        if (Test-ChromeReady) { $ready = $true; break }
    }
    if (-not $ready) { throw "Chrome CDP port 9222 did not become ready." }
} else {
    Write-Host "Project Chrome is already running; reusing it."
}

if (Test-WebReady) {
    Write-Host "BossHunter Web is already running."
} else {
    Write-Host "Starting BossHunter Web..."
    $webProcess = Start-Process -FilePath $Bosshunter -ArgumentList @("web", "--no-open") -WorkingDirectory $RepoRoot -RedirectStandardOutput $OutputLog -RedirectStandardError $ErrorLog -PassThru
    $WebPid = $webProcess.Id
    $ready = $false
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Milliseconds 500
        if (Test-WebReady) { $ready = $true; break }
    }
    if (-not $ready) { throw "Web did not start. Check $OutputLog and $ErrorLog" }
}

Write-Host "Checking the local browser runtime..."
& $Bosshunter connect
if ($LASTEXITCODE -ne 0) { Write-Warning "Browser check failed, but Web is running." }

$state = [ordered]@{ repo_root = $RepoRoot; chrome_pid = $ChromePid; web_pid = $WebPid; chrome_profile = $ChromeProfile; started_at = (Get-Date).ToString("o") }
$state | ConvertTo-Json | Set-Content -LiteralPath $StateFile -Encoding UTF8

Start-Process "http://127.0.0.1:8686/"
Write-Host "BossHunter started: http://127.0.0.1:8686/" -ForegroundColor Green
Write-Host "Logs: data\runtime\web.out.log and data\runtime\web.err.log"
Write-Host "Log in manually in the project Chrome profile. Stop if a captcha appears."
