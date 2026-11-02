# Ownership checks work with both venv launchers and their base Python children.
function Test-AtlasOwnedProcess($ProcessInfo,[string]$Root,[string]$Module,[int]$Port) {
    if(-not $ProcessInfo -or -not $ProcessInfo.ExecutablePath -or -not $ProcessInfo.CommandLine){return $false}
    try {
        $taskAllowed=[IO.Path]::GetFullPath((Join-Path $Root 'runtime'))+[IO.Path]::DirectorySeparatorChar
        $taskExecutable=[IO.Path]::GetFullPath([string]$ProcessInfo.ExecutablePath)
    } catch {return $false}
    if(-not $taskExecutable.StartsWith($taskAllowed,[StringComparison]::OrdinalIgnoreCase)){return $false}
    if([IO.Path]::GetFileName($taskExecutable) -notin @('python.exe','pythonw.exe')){return $false}
    $taskModulePattern='(?i)(?:^|\s)-m\s+uvicorn\s+"?'+[regex]::Escape($Module)+'"?(?=\s|$)'
    $taskPortPattern='(?i)(?:^|\s)--port(?:\s+|=)'+$Port+'(?=\s|$)'
    return $ProcessInfo.CommandLine -match $taskModulePattern -and $ProcessInfo.CommandLine -match $taskPortPattern
}

function Assert-AtlasHealth($Health,[string]$Kind,[string]$Installation,[string]$Version) {
    if($Health.service -ne "atlas-$Kind" -or $Health.installation -ne $Installation){
        throw "Сервис $Kind принадлежит другому приложению или другой копии Атлас."
    }
    if($Health.version -ne $Version){
        throw "Сервис $Kind работает в версии $($Health.version), ожидается $Version. Выполните stop_all.bat, затем start_all.bat."
    }
    if($Kind -eq 'comparison'){
        if(-not $Health.converter -or -not $Health.converter.enabled){
            throw 'Ускоренный конвертер не включён в работающем сервере. Выполните stop_all.bat, затем start_all.bat.'
        }
        if($Health.converter.state -eq 'error'){
            throw 'Конвертер не завершил запуск. Перезапустите сервер сравнения и проверьте logs/comparison.err.log.'
        }
    }
}

function Get-AtlasServiceProcesses([string]$Root,[string]$Kind,[int]$Port,[string]$Module) {
    $taskFound=@{}
    # Discover manual instances too. Never stop a listener just because it owns a port.
    foreach($taskListener in @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)){
        if(-not $taskListener){continue}
        $taskOwner=Get-CimInstance Win32_Process -Filter "ProcessId=$($taskListener.OwningProcess)" -ErrorAction SilentlyContinue
        if(-not (Test-AtlasOwnedProcess $taskOwner $Root $Module $Port)){
            throw "Порт $Port занят процессом $($taskListener.OwningProcess), принадлежность этой копии Атлас не подтверждена. Он не остановлен."
        }
        $taskFound[[int]$taskOwner.ProcessId]=$taskOwner
    }
    $taskRecord=Join-Path $Root "runtime/$Kind.process.json"
    if(Test-Path -LiteralPath $taskRecord){
        try {
            $taskSaved=Get-Content -LiteralPath $taskRecord -Raw -Encoding UTF8 | ConvertFrom-Json
            $taskOwner=Get-CimInstance Win32_Process -Filter "ProcessId=$($taskSaved.pid)" -ErrorAction SilentlyContinue
            if(Test-AtlasOwnedProcess $taskOwner $Root $Module $Port){$taskFound[[int]$taskOwner.ProcessId]=$taskOwner}
        } catch {Write-Host "Запись процесса $Kind устарела; используется проверка порта $Port."}
    }
    return @($taskFound.Values)
}

function Stop-AtlasOwnedProcess([int]$ProcessId) {
    & taskkill /PID $ProcessId /T /F | Out-Host
    if($LASTEXITCODE -ne 0 -and (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue)){throw "Не удалось остановить процесс $ProcessId. Проверьте права и повторите запуск."}
}

function Stop-AtlasService([string]$Root,[string]$Kind,[int]$Port,[string]$Module) {
    $taskOwned=@(Get-AtlasServiceProcesses $Root $Kind $Port $Module)
    foreach($taskProcess in $taskOwned){
        # Recheck the PID immediately before stopping: stale/reused IDs are not trusted.
        $taskCurrent=Get-CimInstance Win32_Process -Filter "ProcessId=$($taskProcess.ProcessId)" -ErrorAction SilentlyContinue
        if(-not $taskCurrent){continue}
        if(-not (Test-AtlasOwnedProcess $taskCurrent $Root $Module $Port)){
            throw "Процесс $($taskProcess.ProcessId) изменился. Он не остановлен."
        }
        Write-Host "Остановка $Kind, PID $($taskProcess.ProcessId)..."
        Stop-AtlasOwnedProcess ([int]$taskProcess.ProcessId)
    }
    for($taskWait=0;$taskWait -lt 30;$taskWait++){
        if(-not (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)){break}
        Start-Sleep -Milliseconds 100
    }
    if(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue){throw "Порт $Port не освободился. Остановка $Kind не завершена."}
    $taskRecord=Join-Path $Root "runtime/$Kind.process.json"
    if(Test-Path -LiteralPath $taskRecord){Remove-Item -LiteralPath $taskRecord -Force}
    Write-Host "$Kind остановлен; порт $Port свободен."
}
