param([switch]$Stop)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $root
$python = Join-Path $root 'runtime/envs/xiaomi-ocr/Scripts/python.exe'
$statePath = Join-Path $root 'runtime/ocr-lab.process.json'
function Get-OwnedProcess($entry) {
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$($entry.pid)" -ErrorAction SilentlyContinue
    if ($proc -and $proc.CommandLine.Contains($entry.module) -and $proc.CommandLine.Contains($root)) { return $proc }
}
if ($Stop) {
    if (Test-Path -LiteralPath $statePath) {
        $entries = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
        foreach ($entry in $entries) { if (Get-OwnedProcess $entry) { Stop-Process -Id $entry.pid -Force } }
        Remove-Item -LiteralPath $statePath
    }
    Write-Host 'OCR services stopped.'
    exit 0
}
if (-not (Test-Path -LiteralPath $python)) { throw 'Сначала запустите setup_ocr.bat' }
if (-not (Test-Path -LiteralPath (Join-Path $root 'models/xiaomi-ocr-0/config.json'))) { throw 'Модель не установлена. Запустите setup_ocr.bat' }
if (Test-Path -LiteralPath $statePath) {
    $entries = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
    $alive = @($entries | Where-Object { Get-OwnedProcess $_ })
    if ($alive.Count) { Write-Host 'OCR уже запущен. http://127.0.0.1:8020'; exit 0 }
}
foreach ($port in @(8020, 8021)) {
    if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) { throw "Порт $port занят другим процессом" }
}
New-Item -ItemType Directory -Force (Join-Path $root 'logs') | Out-Null
$entries = @()
try {
    foreach ($service in @(@{module='ocr_lab.api:app';port=8021;name='api'}, @{module='ocr_lab.web:app';port=8020;name='web'})) {
        $process = Start-Process -FilePath $python -ArgumentList @('-m','uvicorn',$service.module,'--host','127.0.0.1','--port',$service.port) -WorkingDirectory $root -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $root "logs/ocr-$($service.name).out.log") -RedirectStandardError (Join-Path $root "logs/ocr-$($service.name).err.log")
        $entries += @{pid=$process.Id; module=$service.module}
    }
    $entries | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding utf8
    $ready = $false
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        try { $null = Invoke-RestMethod 'http://127.0.0.1:8020/api/health' -TimeoutSec 2; $ready = $true; break } catch { Start-Sleep -Milliseconds 500 }
    }
    if (-not $ready) { throw 'OCR не запустился. Подробности: logs/ocr-*.err.log' }
    Write-Host 'OCR playground: http://127.0.0.1:8020'
} catch {
    foreach ($entry in $entries) { if (Get-OwnedProcess $entry) { Stop-Process -Id $entry.pid -Force } }
    Remove-Item -LiteralPath $statePath -ErrorAction SilentlyContinue
    throw
}
