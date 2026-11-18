$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$adb = Join-Path $PSScriptRoot 'platform-tools\adb.exe'
if (-not (Test-Path $adb)) { throw "找不到 adb: $adb" }

$serial = $env:ANDROID_SERIAL
if (-not $serial) {
    $serial = (& $adb devices | Select-String -Pattern '^\S+\s+device$' | ForEach-Object { ($_ -split '\s+')[0] } | Select-Object -First 1)
}
if (-not $serial) { throw '没有在线的 adb 设备，先启动模拟器并 adb connect' }
Write-Host "使用设备: $serial"

Write-Host '[0/3] 检查 python / frida 模块' -ForegroundColor Cyan
python -c "import frida, sys; print('frida', frida.__version__)" 
if ($LASTEXITCODE -ne 0) { throw 'python 里没有 frida 模块，先执行: pip install -r requirements.txt' }

Write-Host "[1/3] adb connect $serial / root / 端口转发" -ForegroundColor Cyan
& $adb connect $serial | Out-Null
& $adb -s $serial root | Out-Null
Start-Sleep -Seconds 2
& $adb -s $serial forward tcp:27042 tcp:27042 | Out-Null
& $adb -s $serial wait-for-device

Write-Host '[2/3] 推送并启动 frida-server' -ForegroundColor Cyan
$running = (& $adb -s $serial shell "ps -A | grep frida-server" 2>$null)
if (-not $running) {
    & $adb -s $serial push (Join-Path $root 'tools\frida\frida-server') /data/local/tmp/frida-server | Out-Null
    & $adb -s $serial shell "chmod 755 /data/local/tmp/frida-server; nohup /data/local/tmp/frida-server >/dev/null 2>&1 &" | Out-Null
    Start-Sleep -Seconds 3
}
& $adb -s $serial shell "ps -A | grep frida-server"

Write-Host '[3/3] 挂签名伪造 hook（保持本窗口开着，Ctrl-C 结束）' -ForegroundColor Cyan
$env:PYTHONIOENCODING = 'utf-8'
python (Join-Path $root 'tools\wait_opensdk.py')
#https://github.com/guiheng123/budaolepao禁止倒卖
