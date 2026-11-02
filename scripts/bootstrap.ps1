param([ValidateSet('web','comparison','models','all','stop','diagnose')][string]$Mode='all')
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new()
$taskRoot=Split-Path -Parent $PSScriptRoot
$taskHasher=[Security.Cryptography.SHA256]::Create()
$taskInstance=([BitConverter]::ToString($taskHasher.ComputeHash([Text.Encoding]::UTF8.GetBytes($taskRoot.ToLowerInvariant())))).Replace('-','').ToLower().Substring(0,12)
$taskHasher.Dispose()
Set-Location -LiteralPath $taskRoot
$env:PYTHONUTF8='1'
$env:UV_CACHE_DIR=Join-Path $taskRoot 'runtime/cache/uv'
$env:UV_PYTHON_INSTALL_DIR=Join-Path $taskRoot 'runtime/python'
$env:UV_LINK_MODE='copy'
$env:UV_HTTP_TIMEOUT='120'
$env:UV_HTTP_RETRIES='5'
$env:UV_NO_MODIFY_PATH='1'
$env:HF_HOME=Join-Path $taskRoot 'models/cache'
$env:HF_HUB_DISABLE_TELEMETRY='1'
$env:DO_NOT_TRACK='1'
$env:ATLAS_ROOT=$taskRoot
$taskConfig=Get-Content -LiteralPath (Join-Path $taskRoot 'config/settings.json') -Raw | ConvertFrom-Json
$taskLocal=Join-Path $taskRoot 'config/settings.local.json'
if(Test-Path -LiteralPath $taskLocal){
    $taskOverrides=Get-Content -LiteralPath $taskLocal -Raw | ConvertFrom-Json
    foreach($taskProperty in $taskOverrides.PSObject.Properties){$taskConfig | Add-Member -NotePropertyName $taskProperty.Name -NotePropertyValue $taskProperty.Value -Force}
}
if($env:ATLAS_DEVICE){$taskConfig.device=$env:ATLAS_DEVICE}
$taskRuntime=Join-Path $taskRoot 'runtime'
$taskRelease=Get-Content -LiteralPath (Join-Path $taskRoot 'config/release.json') -Raw | ConvertFrom-Json
. (Join-Path $PSScriptRoot 'service_processes.ps1')
New-Item -ItemType Directory -Force -Path $taskRuntime,(Join-Path $taskRoot 'logs') | Out-Null

function Invoke-Checked([string]$Program,[string[]]$Arguments) {
    & $Program @Arguments
    if($LASTEXITCODE -ne 0){throw "Команда завершилась с ошибкой $LASTEXITCODE. Повторите запуск; проверьте сообщения выше."}
}
function Get-AtlasHash([string]$Path){
    $taskHashStream=[IO.File]::OpenRead($Path)
    $taskSha=[Security.Cryptography.SHA256]::Create()
    try{return ([BitConverter]::ToString($taskSha.ComputeHash($taskHashStream))).Replace('-','')}
    finally{$taskHashStream.Dispose();$taskSha.Dispose()}
}
function Install-Cached([string]$Program,[string[]]$Arguments){
    $taskOffline=@('pip','install','--offline')+$Arguments[2..($Arguments.Count-1)]
    $taskOldError=$ErrorActionPreference
    $ErrorActionPreference='Continue'
    & $Program @taskOffline 2>$null | Out-Null
    $taskCode=$LASTEXITCODE
    $ErrorActionPreference=$taskOldError
    if($taskCode -eq 0){Write-Host 'Зависимости установлены из локального кэша.'}else{Invoke-Checked $Program $Arguments}
}
function Get-Uv {
    $taskUv=Join-Path $taskRuntime 'tools/uv.exe'
    if(Test-Path -LiteralPath $taskUv){return $taskUv}
    Write-Host '[1/6] Скачивание локального инструмента установки uv...'
    $taskZip=Join-Path $taskRuntime 'uv.zip'
    Invoke-WebRequest -UseBasicParsing -Uri 'https://github.com/astral-sh/uv/releases/download/0.13.6/uv-x86_64-pc-windows-msvc.zip' -OutFile $taskZip
    if((Get-AtlasHash $taskZip).ToLower() -ne 'a2a8820d5eea32f08ef467ef3b7f66883a9b076d5737a2fc2fbb5f458d1bb50f'){throw 'Контрольная сумма uv не совпала. Удалите runtime/uv.zip и повторите запуск.'}
    Expand-Archive -LiteralPath $taskZip -DestinationPath (Join-Path $taskRuntime 'tools') -Force
    return $taskUv
}
function Get-Python([string]$Kind){
    $taskUv=Get-Uv
    $taskProfile='cpu'
    if($Kind -eq 'models' -and $taskConfig.device -ne 'cpu'){
        $taskSmi=Get-Command nvidia-smi -ErrorAction SilentlyContinue
        if($taskSmi){
            try {$taskDriver=(& $taskSmi.Source --query-gpu=driver_version --format=csv,noheader | Select-Object -First 1).Trim();if([version]$taskDriver -ge [version]'570.0'){$taskProfile='cuda'}}catch{}
        }
    }
    $taskEnvName=if($Kind -eq 'models'){"models-$taskProfile"}else{'comparison'}
    $taskEnv=Join-Path $taskRuntime "envs/$taskEnvName"
    $taskPython=Join-Path $taskEnv 'Scripts/python.exe'
    $taskMarker=Join-Path $taskEnv '.atlas-environment.json'
    $taskLock=Join-Path $taskRoot $(if($Kind -eq 'models'){'requirements-models.lock'}else{'requirements-comparison.lock'})
    $taskHash=Get-AtlasHash $taskLock
    $taskValid=$false
    if((Test-Path -LiteralPath $taskPython) -and (Test-Path -LiteralPath $taskMarker)){
        $taskOld=Get-Content -LiteralPath $taskMarker -Raw | ConvertFrom-Json
        if($taskOld.root -eq $taskRoot -and $taskOld.hash -eq $taskHash -and $taskOld.computer -eq $env:COMPUTERNAME){
            & $taskPython -c 'import sys; assert sys.version_info[:2] == (3,11)' 2>$null
            $taskValid=$LASTEXITCODE -eq 0
        }
    }
    if(-not $taskValid){
        $taskDrive=[IO.DriveInfo]::new([IO.Path]::GetPathRoot($taskRoot))
        $taskNeeded=if($Kind -eq 'models'){8GB}else{3GB}
        if($taskProfile -eq 'cuda'){$taskNeeded=20GB}
        if($taskDrive.AvailableFreeSpace -lt $taskNeeded){throw 'Недостаточно свободного места для установки. Освободите место на диске проекта.'}
        Write-Host '[2/6] Подготовка локального Python 3.11 и окружения. Загрузка может занять несколько минут.'
        $taskBasePython=Join-Path $taskRuntime 'python/cpython-3.11.15-windows-x86_64-none/python.exe'
        # Explorer/copy tools may expand uv's minor-version junction into a real
        # directory. Reuse the versioned interpreter instead of repairing that link.
        if(-not (Test-Path -LiteralPath $taskBasePython)){
            Invoke-Checked $taskUv @('python','install','3.11.15','--no-registry','--no-bin')
        }
        if(Test-Path -LiteralPath $taskEnv){
            $taskResolved=[IO.Path]::GetFullPath($taskEnv)
            $taskAllowed=[IO.Path]::GetFullPath((Join-Path $taskRuntime 'envs'))+[IO.Path]::DirectorySeparatorChar
            if(-not $taskResolved.StartsWith($taskAllowed,[StringComparison]::OrdinalIgnoreCase)){throw 'Недопустимый путь окружения.'}
            Remove-Item -LiteralPath $taskResolved -Recurse -Force
        }
        Invoke-Checked $taskUv @('venv','--python',$taskBasePython,$taskEnv)
        if($Kind -eq 'models'){
            $taskIndex=if($taskProfile -eq 'cuda'){'https://download.pytorch.org/whl/cu128'}else{'https://download.pytorch.org/whl/cpu'}
            Write-Host "[3/6] Установка PyTorch ($taskProfile). После установки загрузка не повторяется."
            $taskWheel=if($taskProfile -eq 'cuda'){'https://download.pytorch.org/whl/cu128/torch-2.7.1%2Bcu128-cp311-cp311-win_amd64.whl'}else{'https://download.pytorch.org/whl/cpu/torch-2.7.1%2Bcpu-cp311-cp311-win_amd64.whl'}
            Install-Cached $taskUv @('pip','install','--python',$taskPython,'--no-deps',$taskWheel)
        }
        Write-Host '[3/6] Установка закреплённых зависимостей...'
        Install-Cached $taskUv @('pip','install','--python',$taskPython,'--no-deps','-r',$taskLock)
        @{root=$taskRoot;hash=$taskHash;computer=$env:COMPUTERNAME;profile=$taskProfile} | ConvertTo-Json | Set-Content -LiteralPath $taskMarker -Encoding UTF8
    }else{Write-Host "[2/6] Окружение $taskEnvName готово — повторная установка не требуется."}
    # Function output must only contain the executable path.
    return $taskPython
}
function Test-Service([string]$Kind){
    $taskPort=switch($Kind){'web'{$taskConfig.web_port}'comparison'{$taskConfig.comparison_port}'models'{$taskConfig.models_port}}
    try{$taskHealth=Invoke-RestMethod -Uri "http://127.0.0.1:$taskPort/health" -TimeoutSec 2}catch{
        if(Get-NetTCPConnection -LocalPort $taskPort -State Listen -ErrorAction SilentlyContinue){throw "Порт $taskPort занят. Освободите порт или измените config/settings.json."}
        return $false
    }
    Assert-AtlasHealth $taskHealth $Kind $taskInstance $taskRelease.version
    if($Kind -eq 'comparison' -and -not $taskHealth.converter.ready){
        Write-Host 'Сервер сравнения запущен; ожидается прогрев конвертера...'
        for($taskWarm=0;$taskWarm -lt 90;$taskWarm++){
            Start-Sleep -Milliseconds 500
            $taskHealth=Invoke-RestMethod -Uri "http://127.0.0.1:$taskPort/health" -TimeoutSec 2
            Assert-AtlasHealth $taskHealth $Kind $taskInstance $taskRelease.version
            if($taskHealth.converter.ready){return $true}
        }
        throw 'Конвертер не завершил прогрев. См. logs/comparison.err.log.'
    }
    return $true
}
function Start-Atlas([string]$Kind,[bool]$Background=$false){
    if(Test-Service $Kind){Write-Host "Сервис $Kind уже работает.";return}
    # Capture only final path; native command stdout is shown, not returned as function output.
    $taskOutput=@(Get-Python $Kind)
    $taskPython=[string]$taskOutput[-1]
    if($taskOutput.Count -gt 1){$taskOutput[0..($taskOutput.Count-2)] | ForEach-Object {Write-Host $_}}
    if($Kind -eq 'models'){
        Write-Host '[4/6] Проверка весов локальных моделей...'
        Invoke-Checked $taskPython @('scripts/download_models.py')
    }elseif($Kind -eq 'comparison'){
        Write-Host '[4/6] Проверка конвертера, PDF.js и шрифтов...'
        Invoke-Checked $taskPython @('scripts/install_assets.py','--converter')
        $taskModels=$taskConfig.models_url
        try {Invoke-RestMethod -Uri "$taskModels/health" -TimeoutSec 2 | Out-Null}catch{
            if(-not $Background){
                $taskAnswer=Read-Host 'Сервер моделей не найден. Введите IP/URL или нажмите Enter для работы без ИИ'
                if($taskAnswer){if($taskAnswer -notmatch '^https?://'){if($taskAnswer -notmatch ':\d+$'){$taskAnswer="${taskAnswer}:8001"};$taskAnswer="http://$taskAnswer"};$env:ATLAS_MODELS_URL=$taskAnswer}
            }
            Write-Host 'При недоступности ИИ сравнение продолжится кодом и правилами.'
        }
    }else{Invoke-Checked $taskPython @('scripts/install_assets.py')}
    Write-Host '[5/6] Проверка среды...'
    Invoke-Checked $taskPython @('scripts/diagnose.py','--component',$Kind,'--quick')
    $taskPort=switch($Kind){'web'{$taskConfig.web_port}'comparison'{$taskConfig.comparison_port}'models'{$taskConfig.models_port}}
    $taskModule=switch($Kind){'web'{'web.server:app'}'comparison'{'comparison_server.app:app'}'models'{'model_server.app:app'}}
    $taskArguments=@('-m','uvicorn',$taskModule,'--host',$taskConfig.host,'--port',"$taskPort",'--no-access-log')
    Write-Host "[6/6] Запуск $Kind. На этом ПК: http://localhost:$taskPort"
    Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object {$_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*'} | ForEach-Object {Write-Host "В локальной сети: http://$($_.IPAddress):$taskPort"}
    if($Background){
        $taskProcess=Start-Process -FilePath $taskPython -ArgumentList $taskArguments -WorkingDirectory $taskRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $taskRoot "logs/$Kind.out.log") -RedirectStandardError (Join-Path $taskRoot "logs/$Kind.err.log")
        @{pid=$taskProcess.Id;python=$taskPython;module=$taskModule} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $taskRuntime "$Kind.process.json") -Encoding UTF8
        $taskReady=$false
        for($taskAttempt=0;$taskAttempt -lt 60;$taskAttempt++){
            Start-Sleep -Seconds 1
            if($taskProcess.HasExited){throw "Сервис $Kind завершился. См. logs/$Kind.err.log"}
            try{$taskH=Invoke-RestMethod "http://127.0.0.1:$taskPort/health" -TimeoutSec 1;if($taskH.service -eq "atlas-$Kind"){Assert-AtlasHealth $taskH $Kind $taskInstance $taskRelease.version;if($Kind -eq 'comparison' -and $taskH.converter.enabled -and -not $taskH.converter.ready){continue};$taskReady=$true;break}}catch{}
        }
        if(-not $taskReady){throw "Сервис $Kind не готов. См. журнал."}
    }else{Invoke-Checked $taskPython $taskArguments}
}
try{
    if(-not [Environment]::Is64BitOperatingSystem){throw 'Нужна Windows x64.'}
    if($env:ATLAS_PREPARE_ONLY -eq '1'){
        $taskPrepareKind=if($Mode -eq 'models'){'models'}else{'comparison'}
        $taskPrepared=@(Get-Python $taskPrepareKind)
        $taskPrepared | ForEach-Object {Write-Host $_}
        Write-Host 'Окружение подготовлено. Сервер не запускался.'
        exit 0
    }
    if($Mode -eq 'stop'){
        foreach($taskKind in @('web','comparison','models')){
            $taskPort=switch($taskKind){'web'{$taskConfig.web_port}'comparison'{$taskConfig.comparison_port}'models'{$taskConfig.models_port}}
            $taskModule=switch($taskKind){'web'{'web.server:app'}'comparison'{'comparison_server.app:app'}'models'{'model_server.app:app'}}
            Stop-AtlasService $taskRoot $taskKind $taskPort $taskModule
        }
        Write-Host 'Все процессы этой копии Атлас остановлены. Порты свободны.'
    }elseif($Mode -eq 'diagnose'){
        $taskOut=@(Get-Python 'comparison');$taskPy=[string]$taskOut[-1];Invoke-Checked $taskPy @('scripts/diagnose.py')
    }elseif($Mode -eq 'all'){
        foreach($taskKind in @('models','comparison','web')){Start-Atlas $taskKind $true}
        if($env:ATLAS_NO_BROWSER -ne '1'){Start-Process "http://localhost:$($taskConfig.web_port)"}
        Write-Host 'Все приложения готовы. Журналы: logs. Для завершения используйте stop_all.bat.'
    }else{Start-Atlas $Mode}
}catch{Write-Host "ОШИБКА: $($_.Exception.Message)" -ForegroundColor Red;exit 1}
