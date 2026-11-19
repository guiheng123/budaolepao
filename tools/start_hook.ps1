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
$runtimePy = Join-Path $PSScriptRoot 'runtime\python\python.exe'
$py = $null
$pyArgs = @()
if (Test-Path $runtimePy) {
    $py = $runtimePy
} else {
    Write-Host '  tools\runtime missing, falling back to system python' -ForegroundColor Yellow
    foreach ($c in @(@{ e = 'py'; a = @('-3') }, @{ e = 'python'; a = @() })) {
        $cmd = Get-Command $c.e -ErrorAction SilentlyContinue
        if (-not $cmd) { continue }
        if ($cmd.Source -like '*\WindowsApps\*') { continue }
        & $cmd.Source @($c.a) -c 'import sys' 2>$null
        if ($LASTEXITCODE -eq 0) { $py = $cmd.Source; $pyArgs = @($c.a); break }
    }
}
if (-not $py) {
    throw 'No usable Python: tools\runtime is missing and no system Python was found.'
}
Write-Host "  Python: $py"
& $py @pyArgs -c "import frida, sys; print('  frida', frida.__version__)"
if ($LASTEXITCODE -ne 0) {
    throw ('frida is not available for {0}. Either restore tools\runtime, or run: "{0}" -m pip install frida==16.7.19 -i https://pypi.tuna.tsinghua.edu.cn/simple' -f $py)
}

Write-Host "[1/3] adb connect $serial / root / forward" -ForegroundColor Cyan
& $adb connect $serial | Out-Null
& $adb -s $serial root | Out-Null
Start-Sleep -Seconds 2
& $adb -s $serial forward tcp:27042 tcp:27042 | Out-Null
& $adb -s $serial wait-for-device

Write-Host '[2/3] Push and start frida-server' -ForegroundColor Cyan
$serverBin = Join-Path $root 'tools\frida\frida-server'
$serverZip = Join-Path $root 'tools\frida\frida-server.zip'
if (-not (Test-Path $serverBin) -and (Test-Path $serverZip)) {
    Write-Host '  extracting frida-server.zip ...'
    Expand-Archive -Path $serverZip -DestinationPath (Split-Path -Parent $serverBin) -Force
}
if (-not (Test-Path $serverBin)) { throw "frida-server not found: $serverBin" }
$running = (& $adb -s $serial shell "ps -A | grep frida-server" 2>$null)
if (-not $running) {
    & $adb -s $serial push $serverBin /data/local/tmp/frida-server | Out-Null
    & $adb -s $serial shell "chmod 755 /data/local/tmp/frida-server; nohup /data/local/tmp/frida-server >/dev/null 2>&1 &" | Out-Null
    Start-Sleep -Seconds 3
}
& $adb -s $serial shell "ps -A | grep frida-server"

Write-Host "[3/3] Hook $appName signature spoof (keep this window open, Ctrl-C to stop)" -ForegroundColor Cyan
$env:PYTHONIOENCODING = 'utf-8'
& $py @pyArgs $hookPy
#https://github.com/guiheng123/budaolepao禁止倒卖
