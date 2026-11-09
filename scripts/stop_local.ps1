$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path -LiteralPath (Split-Path -Parent $PSScriptRoot)).Path
$Manifest = Join-Path $ProjectRoot 'data\logs\local-processes.json'
$ServiceScript = Join-Path $ProjectRoot 'src\run_service.py'
$AppScript = Join-Path $ProjectRoot 'src\streamlit_app.py'
$Marker = 'rag-customer-service-local-v1'

function Test-OwnedRecord($Record) {
    try {
        $process = Get-Process -Id ([int]$Record.pid) -ErrorAction Stop
        if ([string]$process.StartTime.ToUniversalTime().Ticks -ne [string]$Record.start_ticks) { return $false }
        $info = Get-CimInstance Win32_Process -Filter "ProcessId = $([int]$Record.pid)" -ErrorAction Stop
        if (-not $info.CommandLine) { return $false }
        if ($Record.name -eq 'service') { $expected = $ServiceScript }
        elseif ($Record.name -eq 'app') { $expected = $AppScript }
        else { return $false }
        return $info.CommandLine.IndexOf($expected, [StringComparison]::OrdinalIgnoreCase) -ge 0
    } catch { return $false }
}

function Stop-Descendants([int]$ParentId) {
    $children = @(Get-CimInstance Win32_Process -Filter "ParentProcessId = $ParentId" -ErrorAction SilentlyContinue)
    foreach ($child in $children) {
        Stop-Descendants -ParentId ([int]$child.ProcessId)
        $current = Get-CimInstance Win32_Process -Filter "ProcessId = $([int]$child.ProcessId)" -ErrorAction SilentlyContinue
        if ($current -and [int]$current.ParentProcessId -eq $ParentId) {
            Stop-Process -Id ([int]$child.ProcessId) -Force -ErrorAction SilentlyContinue
        }
    }
}

try {
    if (-not (Test-Path -LiteralPath $Manifest)) { Write-Host '没有本项目的启动记录，无需停止。'; exit 0 }
    $manifestData = Get-Content -LiteralPath $Manifest -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($manifestData.kind -ne $Marker -or $manifestData.root -ne $ProjectRoot) {
        throw "无法确认启动记录属于当前项目，请检查 $Manifest。"
    }
    foreach ($record in @($manifestData.processes)) {
        if (-not $record) { continue }
        if (Test-OwnedRecord $record) {
            Stop-Descendants -ParentId ([int]$record.pid)
            Stop-Process -Id ([int]$record.pid) -Force -ErrorAction SilentlyContinue
            Write-Host ("已停止本项目 {0} 进程。" -f $record.name)
        } else {
            Write-Host ("{0} 进程已结束或身份无法确认，未操作。" -f $record.name)
        }
    }
    Write-Host '本项目停止操作完成。'
} catch {
    Write-Host ("停止失败：" + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
