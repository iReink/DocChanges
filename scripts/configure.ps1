$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new()
$taskRoot=Split-Path -Parent $PSScriptRoot
$taskPath=Join-Path $taskRoot 'config/settings.local.json'
$taskLocal=@{}
if(Test-Path -LiteralPath $taskPath){
    $taskSaved=Get-Content -LiteralPath $taskPath -Raw | ConvertFrom-Json
    foreach($taskItem in $taskSaved.PSObject.Properties){$taskLocal[$taskItem.Name]=$taskItem.Value}
}
function Read-Address([string]$Label,[string]$Default,[int]$Port){
    $taskAnswer=Read-Host "$Label [$Default]; Enter — оставить"
    if(-not $taskAnswer){return $Default}
    $taskAnswer=$taskAnswer.Trim().TrimEnd('/')
    if($taskAnswer -notmatch '^https?://'){$taskAnswer='http://'+$taskAnswer}
    $taskUri=[Uri]$taskAnswer
    if($taskUri.Scheme -notin @('http','https') -or -not $taskUri.Host -or $taskUri.UserInfo -or $taskUri.AbsolutePath -ne '/' -or $taskUri.Query -or $taskUri.Fragment){throw 'Нужен адрес вида http://192.168.1.20:8000 без дополнительных путей.'}
    if($taskUri.Authority -notmatch ':\d+$'){$taskAnswer=$taskAnswer+':'+$Port}
    return $taskAnswer
}
try{
    Write-Host 'НАСТРОЙКА АТЛАСА'
    Write-Host 'На одном ПК оставьте оба адреса как есть. Для разных ПК введите адреса из окон запуска соответствующих серверов.'
    $taskApi=if($taskLocal.ContainsKey('api_url') -and $taskLocal.api_url){$taskLocal.api_url}else{'http://localhost:8000'}
    $taskModels=if($taskLocal.ContainsKey('models_url')){$taskLocal.models_url}else{'http://127.0.0.1:8001'}
    $taskLocal.api_url=Read-Address 'Адрес сервера сравнения (для веб-интерфейса)' $taskApi 8000
    $taskLocal.models_url=Read-Address 'Адрес сервера моделей (для сервера сравнения)' $taskModels 8001
    $taskDevice=if($taskLocal.ContainsKey('device')){$taskLocal.device}else{'auto'}
    $taskMode=Read-Host "Модели: 1 — автоматически, 2 — только процессор. Enter — оставить $taskDevice"
    if($taskMode -eq '1'){$taskDevice='auto'}elseif($taskMode -eq '2'){$taskDevice='cpu'}elseif($taskMode){throw 'Нужно выбрать 1, 2 или нажать Enter.'}
    $taskLocal.device=$taskDevice
    $taskJson=$taskLocal | ConvertTo-Json
    [IO.File]::WriteAllText($taskPath,$taskJson,[Text.UTF8Encoding]::new($false))
    Write-Host 'Настройки сохранены. Перезапустите запущенные компоненты: stop_all.bat, затем нужные start_*.bat.'
    Write-Host 'Ранее сохранённый адрес в браузере имеет приоритет: измените его кнопкой с шестерёнкой.'
}catch{Write-Host ('Ошибка: '+$_.Exception.Message) -ForegroundColor Red;exit 1}
