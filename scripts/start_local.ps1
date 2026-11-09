$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path -LiteralPath (Split-Path -Parent $PSScriptRoot)).Path
$PythonExe = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
$ServiceScript = Join-Path $ProjectRoot 'src\run_service.py'
$AppScript = Join-Path $ProjectRoot 'src\streamlit_app.py'
$LogDir = Join-Path $ProjectRoot 'data\logs'
$Manifest = Join-Path $LogDir 'local-processes.json'
$Marker = 'rag-customer-service-local-v1'
$Started = @()
Set-Location -LiteralPath $ProjectRoot

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

function Stop-OwnedRecord($Record) {
    if (Test-OwnedRecord $Record) {
        Stop-Descendants -ParentId ([int]$Record.pid)
        Stop-Process -Id ([int]$Record.pid) -Force -ErrorAction SilentlyContinue
    }
}

function Write-Manifest {
    @{ kind = $Marker; root = $ProjectRoot; processes = @($script:Started) } |
        ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $Manifest -Encoding UTF8
}

function Start-TrackedProcess([string]$Name, [string]$ArgumentLine) {
    $token = [DateTime]::Now.ToString('yyyyMMdd-HHmmss-fff') + '-' + [guid]::NewGuid().ToString('N').Substring(0, 8)
    $stdout = Join-Path $LogDir ("local-$Name-$token.out.log")
    $stderr = Join-Path $LogDir ("local-$Name-$token.err.log")
    $process = Start-Process -FilePath $PythonExe -ArgumentList $ArgumentLine `
        -WorkingDirectory $ProjectRoot -RedirectStandardOutput $stdout -RedirectStandardError $stderr `
        -WindowStyle Hidden -PassThru
    $record = @{ name = $Name; pid = $process.Id; start_ticks = [string]$process.StartTime.ToUniversalTime().Ticks; stdout = $stdout; stderr = $stderr }
    $script:Started += $record
    Write-Manifest
    return $record
}

function Test-Descendant([int]$ProcessId, [int]$RootId) {
    $current = $ProcessId
    for ($depth = 0; $depth -lt 32 -and $current -gt 0; $depth++) {
        if ($current -eq $RootId) { return $true }
        $info = Get-CimInstance Win32_Process -Filter "ProcessId = $current" -ErrorAction SilentlyContinue
        if (-not $info -or [int]$info.ParentProcessId -eq $current) { break }
        $current = [int]$info.ParentProcessId
    }
    return $false
}

function Wait-Ready([int]$Port, [string]$Url, $Record, [int]$Seconds = 60) {
    for ($i = 0; $i -lt $Seconds; $i++) {
        if (-not (Test-OwnedRecord $Record)) { throw "进程已退出，请检查日志：$($Record.stderr)" }
        $listeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
        foreach ($listener in $listeners) {
            if (Test-Descendant -ProcessId ([int]$listener.OwningProcess) -RootId ([int]$Record.pid)) {
                try {
                    Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 2 | Out-Null
                    return
                } catch { }
            }
        }
        Start-Sleep -Seconds 1
    }
    throw "服务未在预期时间内就绪，请检查日志：$($Record.stderr)"
}

try {
    if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) { throw '未找到本项目的 Python 环境 .venv，请先完成依赖安装。' }
    # Keep the configuration checker readable in both PowerShell and cmd.exe.
    [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
    $env:PYTHONIOENCODING = 'utf-8'
    & $PythonExe (Join-Path $PSScriptRoot 'check_local_config.py')
    if ($LASTEXITCODE -ne 0) { throw '请先完成本项目 .env 中的 Qwen 配置。' }

    New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
    if (Test-Path -LiteralPath $Manifest) {
        try { $old = Get-Content -LiteralPath $Manifest -Raw -Encoding UTF8 | ConvertFrom-Json }
        catch { throw "无法识别已有启动记录，请检查 $Manifest。" }
        if ($old.kind -ne $Marker -or $old.root -ne $ProjectRoot) { throw "已有启动记录不属于当前项目，请检查 $Manifest。" }
        foreach ($record in @($old.processes)) {
            if ($record -and (Test-OwnedRecord $record)) { throw '本项目已有后台进程，请先运行 scripts\stop_local.cmd。' }
        }
    }
    foreach ($port in @(8080, 8501)) {
        if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
            throw "端口 $port 已被占用。请先确认占用者；脚本不会停止其他程序。"
        }
    }

    # Child-only overrides ensure this launcher uses this project's Qwen config and ports.
    $env:CUSTOMER_SUPPORT_MODE = 'qwen'
    $env:HOST = '127.0.0.1'
    $env:PORT = '8080'
    $env:AGENT_URL = 'http://127.0.0.1:8080'
    # Preserve any existing proxy exemptions while ensuring app-to-API traffic stays local.
    $proxyExemptions = New-Object 'System.Collections.Generic.List[string]'
    foreach ($variable in @('NO_PROXY', 'no_proxy')) {
        $existingValue = [Environment]::GetEnvironmentVariable($variable, 'Process')
        if ($existingValue) {
            foreach ($entry in $existingValue.Split(',')) {
                $item = $entry.Trim()
                if ($item -and -not $proxyExemptions.Contains($item)) { $proxyExemptions.Add($item) }
            }
        }
    }
    foreach ($item in @('localhost', '127.0.0.1', '::1')) {
        if (-not $proxyExemptions.Contains($item)) { $proxyExemptions.Add($item) }
    }
    $env:NO_PROXY = $proxyExemptions -join ','
    $env:no_proxy = $env:NO_PROXY
    Remove-Item Env:DASHSCOPE_API_KEY -ErrorAction SilentlyContinue
    Remove-Item Env:DASHSCOPE_BASE_URL -ErrorAction SilentlyContinue
    Remove-Item Env:DASHSCOPE_MODEL -ErrorAction SilentlyContinue

    Write-Host '正在启动本项目的 FastAPI 服务……'
    $service = Start-TrackedProcess -Name 'service' -ArgumentLine ('"' + $ServiceScript + '"')
    Wait-Ready -Port 8080 -Url 'http://127.0.0.1:8080/health' -Record $service
    Write-Host '正在启动客服网页……'
    $arguments = '-m streamlit run "' + $AppScript + '" --server.address 127.0.0.1 --server.port 8501 --server.headless true --browser.gatherUsageStats false'
    $app = Start-TrackedProcess -Name 'app' -ArgumentLine $arguments
    Wait-Ready -Port 8501 -Url 'http://127.0.0.1:8501/_stcore/health' -Record $app
    Write-Host '启动完成： http://127.0.0.1:8501'
    Write-Host '停止本项目：双击 scripts\stop_local.cmd'
    try { Start-Process -FilePath 'http://127.0.0.1:8501' | Out-Null }
    catch { Write-Host '请手动在浏览器打开 http://127.0.0.1:8501' }
} catch {
    foreach ($record in @($Started)) { Stop-OwnedRecord $record }
    Write-Host ("启动失败：" + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
