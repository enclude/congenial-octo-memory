# build.ps1 - builds PiroOverlay.exe on Windows.
# (ASCII-only on purpose: Windows PowerShell 5.1 reads .ps1 in the local codepage,
#  so non-ASCII characters would break parsing unless the file has a UTF-8 BOM.)
#
# Run (PowerShell, from the project directory):
#     .\build.ps1
#
# If you get "running scripts is disabled on this system" - that is the PowerShell
# execution policy, not a script error. Use one of:
#     powershell -ExecutionPolicy Bypass -File .\build.ps1        # one-off, cleanest
# or, for the current window:
#     Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#     .\build.ps1
#
# Parameters:
#     -Clean   remove build/, dist/ and the venv before building
#     -VenvDir venv directory name (default .venv-win)

param(
    [switch]$Clean,
    [switch]$WithFfmpeg,
    [switch]$ts,            # dopisz biezacy timestamp do nazwy .exe
    [string]$VenvDir = ".venv-win"
)

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

# Streaming download with percent / MB / speed / ETA (Invoke-WebRequest in newer
# PowerShell shows no progress; this gives a live Write-Progress bar).
function Get-FileWithProgress {
    param([string]$Url, [string]$Dest)
    Add-Type -AssemblyName System.Net.Http
    $client = [System.Net.Http.HttpClient]::new()
    $client.Timeout = [TimeSpan]::FromMinutes(30)
    try {
        $resp = $client.GetAsync($Url, [System.Net.Http.HttpCompletionOption]::ResponseHeadersRead).Result
        $resp.EnsureSuccessStatusCode() | Out-Null
        $total = $resp.Content.Headers.ContentLength
        $stream = $resp.Content.ReadAsStreamAsync().Result
        $fs = [System.IO.File]::Create($Dest)
        try {
            $buffer = New-Object byte[] (1MB)
            $totalRead = 0L
            $sw = [System.Diagnostics.Stopwatch]::StartNew()
            $lastMs = 0
            while (($read = $stream.Read($buffer, 0, $buffer.Length)) -gt 0) {
                $fs.Write($buffer, 0, $read)
                $totalRead += $read
                if ($sw.Elapsed.TotalMilliseconds - $lastMs -ge 200) {
                    $lastMs = $sw.Elapsed.TotalMilliseconds
                    $speed = $totalRead / [Math]::Max($sw.Elapsed.TotalSeconds, 0.001)  # B/s
                    if ($total) {
                        $pct = [int](($totalRead / $total) * 100)
                        $eta = if ($speed -gt 0) { [TimeSpan]::FromSeconds(($total - $totalRead) / $speed) } else { [TimeSpan]::Zero }
                        $status = "{0:N1} / {1:N1} MB   {2:N1} MB/s   ETA {3:mm\:ss}" -f `
                            ($totalRead / 1MB), ($total / 1MB), ($speed / 1MB), $eta
                        Write-Progress -Activity "Downloading FFmpeg (NVENC)" -Status $status -PercentComplete $pct
                    } else {
                        Write-Progress -Activity "Downloading FFmpeg (NVENC)" -Status ("{0:N1} MB" -f ($totalRead / 1MB))
                    }
                }
            }
        } finally {
            $fs.Close(); $stream.Close()
        }
    } finally {
        $client.Dispose()
        Write-Progress -Activity "Downloading FFmpeg (NVENC)" -Completed
    }
}

if ($Clean) {
    Write-Host "Cleaning build/, dist/, $VenvDir ..." -ForegroundColor Yellow
    foreach ($d in @("build", "dist", $VenvDir)) {
        if (Test-Path $d) { Remove-Item -Recurse -Force $d }
    }
}

# Optional: bundle a full FFmpeg (with NVENC) so the .exe has GPU acceleration
# without the user installing FFmpeg system-wide.
if ($WithFfmpeg) {
    $binDir = "assets\bin"
    $exe = Join-Path $binDir "ffmpeg.exe"
    New-Item -ItemType Directory -Force -Path $binDir | Out-Null
    if (-not (Test-Path $exe)) {
        $url = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
        $zip = Join-Path $env:TEMP "ffmpeg-piro.zip"
        $tmp = Join-Path $env:TEMP "ffmpeg-piro"
        Write-Host "Downloading full FFmpeg (NVENC) from BtbN ..." -ForegroundColor Cyan
        Get-FileWithProgress -Url $url -Dest $zip
        if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
        Expand-Archive -Path $zip -DestinationPath $tmp
        $found = Get-ChildItem -Path $tmp -Recurse -Filter ffmpeg.exe | Select-Object -First 1
        Copy-Item $found.FullName $exe -Force
        Write-Host "Bundled FFmpeg: $exe" -ForegroundColor Green
    } else {
        Write-Host "Full FFmpeg already present: $exe" -ForegroundColor Green
    }
}

# 1. Python
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) { $python = Get-Command py -ErrorAction SilentlyContinue }
if (-not $python) {
    throw "Python not found in PATH. Install from https://python.org (check 'Add to PATH')."
}

# 2. Windows venv (separate from any .venv created under WSL/Linux)
if (-not (Test-Path $VenvDir)) {
    Write-Host "Creating venv $VenvDir ..." -ForegroundColor Cyan
    & $python.Source -m venv $VenvDir
}
$venvPy = Join-Path $VenvDir "Scripts\python.exe"

# 3. Dependencies + PyInstaller
Write-Host "Installing dependencies ..." -ForegroundColor Cyan
& $venvPy -m pip install --upgrade pip
& $venvPy -m pip install -e .
& $venvPy -m pip install pyinstaller

# 4. Build
Write-Host "Building PiroOverlay.exe ..." -ForegroundColor Cyan
& $venvPy -m PyInstaller build_exe.spec --noconfirm

$exe = Join-Path "dist" "PiroOverlay.exe"
if (-not (Test-Path $exe)) {
    throw "Build finished, but $exe was not found."
}

if ($ts) {
    # Nazwa z biezacym timestampem, np. PiroOverlay_20260626_153012.exe
    $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $stampedExe = Join-Path "dist" ("PiroOverlay_{0}.exe" -f $stamp)
    Copy-Item $exe $stampedExe -Force
    Write-Host "`nDone: $((Resolve-Path $stampedExe).Path)" -ForegroundColor Green
} else {
    Write-Host "`nDone: $((Resolve-Path $exe).Path)" -ForegroundColor Green
}
