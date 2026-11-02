$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $root
$uv = Join-Path $root 'runtime/tools/uv.exe'
if (-not (Test-Path -LiteralPath $uv)) { throw 'Не найден runtime/tools/uv.exe. Установите uv или восстановите runtime проекта.' }
$python = Join-Path $root 'runtime/envs/xiaomi-ocr/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    & $uv venv (Join-Path $root 'runtime/envs/xiaomi-ocr') --python 3.13
    if ($LASTEXITCODE) { throw 'Не удалось создать окружение Python' }
}
& $uv pip install --python $python -r (Join-Path $PSScriptRoot 'requirements.lock')
if ($LASTEXITCODE) { throw 'Не удалось установить зависимости' }
& $python -m ocr_lab.download_model
if ($LASTEXITCODE) { throw 'Не удалось скачать модель; повторите setup_ocr.bat' }
Write-Host 'Готово. Запустите start_ocr.bat'
