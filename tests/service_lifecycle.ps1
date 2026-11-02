param([string]$CaseRoot)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new()
. (Join-Path (Split-Path -Parent $PSScriptRoot) 'scripts/service_processes.ps1')
New-Item -ItemType Directory -Force -Path (Join-Path $CaseRoot 'runtime') | Out-Null
$script:Processes=@{};$script:Listeners=@();$script:Stopped=@();$script:Swap=$false;$script:CimCalls=0
function Get-NetTCPConnection {param($LocalPort,$State,$ErrorAction);return @($script:Listeners | Where-Object {$_.LocalPort -eq $LocalPort})}
function Get-CimInstance {
    param($ClassName,$Filter,$ErrorAction)
    $taskMockId=[int]($Filter -replace '\D','');$script:CimCalls++
    if($script:Swap -and $script:CimCalls -gt 1){return [pscustomobject]@{ProcessId=$taskMockId;ExecutablePath='C:\Windows\python.exe';CommandLine='unrelated'}}
    return $script:Processes[$taskMockId]
}
# This test never calls taskkill or any real process-management API.
function Stop-AtlasOwnedProcess {
    param([int]$ProcessId)
    $script:Stopped+=@($ProcessId)
    $script:Listeners=@($script:Listeners | Where-Object {$_.OwningProcess -ne $ProcessId})
    $script:Processes.Remove($ProcessId)
}
function Assert($Condition,[string]$Message){if(-not $Condition){throw $Message}}
function Reset-Mocks {
    $script:Processes=@{};$script:Listeners=@();$script:Stopped=@();$script:Swap=$false;$script:CimCalls=0
}
function Owned([int]$Number){return [pscustomobject]@{ProcessId=$Number;ExecutablePath=(Join-Path $CaseRoot 'runtime/python/base/python.exe');CommandLine='python.exe -m uvicorn comparison_server.app:app --host 0.0.0.0 --port 8000'}}
function Listen([int]$Number){$script:Listeners=@([pscustomobject]@{LocalPort=8000;OwningProcess=$Number})}
$taskMarker=Join-Path $CaseRoot 'runtime/comparison.process.json'

# Missing PID marker: the manually started listener is still discovered.
$script:Processes[101]=(Owned 101);Listen 101
Stop-AtlasService $CaseRoot 'comparison' 8000 'comparison_server.app:app'
Assert ($script:Stopped.Count -eq 1 -and $script:Stopped[0] -eq 101) 'Manual listener was not stopped.'

# Windows venv child executable differs from the marker's launcher path.
Reset-Mocks;$script:Processes[102]=(Owned 102);Listen 102
@{pid=102;python=(Join-Path $CaseRoot 'runtime/envs/comparison/Scripts/python.exe');module='comparison_server.app:app'} | ConvertTo-Json | Set-Content $taskMarker -Encoding UTF8
Stop-AtlasService $CaseRoot 'comparison' 8000 'comparison_server.app:app'
Assert ($script:Stopped.Count -eq 1 -and $script:Stopped[0] -eq 102) 'Base Python child not recognised.'
Assert (-not (Test-Path $taskMarker)) 'Successful stop did not remove marker.'

# Reused PID outside this workspace must never be killed.
Reset-Mocks;$script:Processes[103]=[pscustomobject]@{ProcessId=103;ExecutablePath='C:\Windows\python.exe';CommandLine='python.exe -m uvicorn comparison_server.app:app --port 8000'}
@{pid=103;python='stale';module='comparison_server.app:app'} | ConvertTo-Json | Set-Content $taskMarker -Encoding UTF8
Stop-AtlasService $CaseRoot 'comparison' 8000 'comparison_server.app:app'
Assert ($script:Stopped.Count -eq 0) 'Reused foreign PID was stopped.'

# Foreign listener: fail without stopping anything.
Listen 103;$taskRejected=$false
try{Stop-AtlasService $CaseRoot 'comparison' 8000 'comparison_server.app:app'}catch{$taskRejected=$true}
Assert ($taskRejected -and $script:Stopped.Count -eq 0) 'Foreign listener accepted.'

# The process changed after discovery: recheck before mutation.
Reset-Mocks;$script:Processes[104]=(Owned 104);Listen 104;$script:Swap=$true;$taskRejected=$false
try{Stop-AtlasService $CaseRoot 'comparison' 8000 'comparison_server.app:app'}catch{$taskRejected=$true}
Assert ($taskRejected -and $script:Stopped.Count -eq 0) 'Changed PID accepted.'

# An old API or a missing prewarmed converter is not a ready current service.
$taskHealth=[pscustomobject]@{service='atlas-comparison';installation='test';version='0.2.0'}
$taskRejected=$false;try{Assert-AtlasHealth $taskHealth 'comparison' 'test' '0.2.1'}catch{$taskRejected=$true}
Assert $taskRejected 'Old version accepted.'
$taskHealth.version='0.2.1';$taskRejected=$false
try{Assert-AtlasHealth $taskHealth 'comparison' 'test' '0.2.1'}catch{$taskRejected=$true}
Assert $taskRejected 'Missing converter accepted.'
$taskHealth | Add-Member converter ([pscustomobject]@{enabled=$true;ready=$true;state='ready'})
Assert-AtlasHealth $taskHealth 'comparison' 'test' '0.2.1'
Write-Host 'PASS: process ownership, manual listeners, venv children, reused IDs, readiness.'
