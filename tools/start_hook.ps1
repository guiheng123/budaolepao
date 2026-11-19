$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host 'Choose target: [1] QQ   [2] WeChat' -ForegroundColor Cyan
$sel = Read-Host 'Enter 1 or 2 (blank = 1 QQ)'
if ([string]::IsNullOrWhiteSpace($sel)) { $sel = '1' }
$sel = $sel.Trim()
if ($sel -eq '2') {
    $appName = 'WeChat'
    $hookPy = Join-Path $root 'tools\wait_wechat.py'
} else {
    $appName = 'QQ'
    $hookPy = Join-Path $root 'tools\wait_opensdk.py'
}

$adb = Join-Path $PSScriptRoot 'platform-tools\adb.exe'
if (-not (Test-Path $adb)) { throw "adb not found: $adb" }

$serial = $env:ANDROID_SERIAL
if (-not $serial) {
    $serial = (& $adb devices | Select-String -Pattern '^\S+\s+device$' | ForEach-Object { ($_ -split '\s+')[0] } | Select-Object -First 1)
}
if (-not $serial) { throw 'No online adb device. Start the emulator and adb connect first.' }
Write-Host "Device: $serial"

Write-Host '[0/3] Check python / frida' -ForegroundColor Cyan
python -c "import frida, sys; print('frida', frida.__version__)" 
if ($LASTEXITCODE -ne 0) { throw 'frida module missing, run: pip install -r requirements.txt' }

Write-Host "[1/3] adb connect $serial / root / forward" -ForegroundColor Cyan
& $adb connect $serial | Out-Null
& $adb -s $serial root | Out-Null
Start-Sleep -Seconds 2
& $adb -s $serial forward tcp:27042 tcp:27042 | Out-Null
& $adb -s $serial wait-for-device

Write-Host '[2/3] Push and start frida-server' -ForegroundColor Cyan
$running = (& $adb -s $serial shell "ps -A | grep frida-server" 2>$null)
if (-not $running) {
    & $adb -s $serial push (Join-Path $root 'tools\frida\frida-server') /data/local/tmp/frida-server | Out-Null
    & $adb -s $serial shell "chmod 755 /data/local/tmp/frida-server; nohup /data/local/tmp/frida-server >/dev/null 2>&1 &" | Out-Null
    Start-Sleep -Seconds 3
}
& $adb -s $serial shell "ps -A | grep frida-server"

Write-Host "[3/3] Hook $appName signature spoof (keep this window open, Ctrl-C to stop)" -ForegroundColor Cyan
$env:PYTHONIOENCODING = 'utf-8'
python $hookPy
#https://github.com/guiheng123/budaolepao禁止倒卖
