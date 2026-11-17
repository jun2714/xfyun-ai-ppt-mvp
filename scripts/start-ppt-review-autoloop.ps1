#requires -Version 5.1
<#
.SYNOPSIS
    Run the local PPT review pilot through a dedicated Agent Autoloop instance.
.DESCRIPTION
    Setup creates project-local configuration for the fixed v1.9.0 runtime.
    Up stays in the foreground. Run submits one job; Status shows its result.
    Model calls use the existing PPT API, not a Codex or Claude login.
#>
[CmdletBinding()]
param(
    [ValidateSet('Setup', 'Up', 'Run', 'Status')]
    [string]$Mode = 'Setup',

    [string]$ProjectPath = (Split-Path -Parent $PSScriptRoot),
    [string]$AutoloopPath = '',

    [Parameter(Mandatory = $true)]
    [string]$InputPath,

    [string]$OutputPath = '',
    [string]$ApiBase = 'http://127.0.0.1:8000',
    [ValidateRange(0, 65535)]
    [int]$Port = 0,
    [string]$PythonPath = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$PinnedVersion = 'v1.9.0'
$RuleName = 'ppt-review'
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)

function Get-FullPath {
    param([string]$Value, [string]$BasePath)
    if ([System.IO.Path]::IsPathRooted($Value)) {
        return [System.IO.Path]::GetFullPath($Value)
    }
    return [System.IO.Path]::GetFullPath((Join-Path $BasePath $Value))
}

function Get-ApplicationPath {
    param([string]$Name)
    $application = Get-Command -Name $Name -CommandType Application -ErrorAction Stop |
        Select-Object -First 1
    return $application.Source
}

function Invoke-Checked {
    param([string]$Program, [string[]]$Arguments)
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "程序 $(Split-Path -Leaf $Program) 执行失败，退出码：$LASTEXITCODE。"
    }
}

function Write-JsonFile {
    param([string]$Path, $Value)
    $temporaryPath = "$Path.tmp"
    $jsonText = ConvertTo-Json -InputObject $Value -Depth 50
    [System.IO.File]::WriteAllText($temporaryPath, $jsonText + "`n", $Utf8NoBom)
    Move-Item -LiteralPath $temporaryPath -Destination $Path -Force
}

function Test-HubOnline {
    param([string]$Url)
    try {
        $health = Invoke-RestMethod -Uri ($Url.TrimEnd('/') + '/healthz') -TimeoutSec 2
        return ($health.ok -eq $true)
    }
    catch {
        return $false
    }
}

function Get-FreeLocalPort {
    $listener = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Loopback, 0)
    try {
        $listener.Start()
        return $listener.LocalEndpoint.Port
    }
    finally {
        $listener.Stop()
    }
}

function Find-PythonPath {
    param([string]$RequestedPath, [string]$RootPath)
    $candidates = @()
    if ($RequestedPath) {
        $candidates += Get-FullPath -Value $RequestedPath -BasePath $RootPath
    }
    else {
        $candidates += Join-Path $RootPath 'engine\api\.venv\Scripts\python.exe'
        $candidates += Join-Path $RootPath '.venv\Scripts\python.exe'
        foreach ($name in @('python', 'python3')) {
            $application = Get-Command -Name $name -CommandType Application -ErrorAction SilentlyContinue |
                Select-Object -First 1
            if ($application) { $candidates += $application.Source }
        }
    }
    foreach ($candidate in ($candidates | Select-Object -Unique)) {
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { continue }
        try {
            $versionText = & $candidate -c 'import sys; print(sys.version_info >= (3, 10))'
            if ($LASTEXITCODE -eq 0 -and $versionText -eq 'True') { return $candidate }
        }
        catch { }
    }
    throw '未找到 Python 3.10 或更新版本。请用 -PythonPath 指定 python.exe 的完整路径。'
}

$ProjectPath = (Resolve-Path -LiteralPath $ProjectPath).Path
$InputPath = Get-FullPath -Value $InputPath -BasePath $ProjectPath
$PilotRoot = Join-Path $ProjectPath '.runtime\ppt-review-autoloop'
$StatePath = Join-Path $PilotRoot 'state'
$SettingsFile = Join-Path $StatePath 'pilot.json'
$ConfigFile = Join-Path $StatePath 'config.json'
$RulesFile = Join-Path $StatePath 'rules.json'
$PilotScript = Join-Path $ProjectPath 'scripts\ppt-review-pilot.py'
$settings = $null
if (Test-Path -LiteralPath $SettingsFile) {
    $settings = Get-Content -LiteralPath $SettingsFile -Raw -Encoding UTF8 | ConvertFrom-Json
}
if (-not $AutoloopPath) {
    $AutoloopPath = if ($settings) { $settings.autoloop_path } else { Join-Path $PilotRoot 'runtime' }
}
$AutoloopPath = Get-FullPath -Value $AutoloopPath -BasePath $ProjectPath
if (-not $OutputPath) {
    $OutputPath = if ($settings) { $settings.output_path } else { Join-Path $ProjectPath '.data\ppt-review-autoloop' }
}
$OutputPath = Get-FullPath -Value $OutputPath -BasePath $ProjectPath
if ($settings -and $Mode -ne 'Setup' -and -not $PSBoundParameters.ContainsKey('ApiBase')) {
    $ApiBase = $settings.api_base
}
$ApiBase = $ApiBase.TrimEnd('/')
$apiUri = $null
if (-not [System.Uri]::TryCreate($ApiBase, [System.UriKind]::Absolute, [ref]$apiUri) -or
    $apiUri.Scheme -notin @('http', 'https') -or $apiUri.UserInfo -or $apiUri.Query -or $apiUri.Fragment) {
    throw '-ApiBase 必须是没有账号、查询参数或片段的 HTTP/HTTPS 服务根地址。'
}

$NodePath = Get-ApplicationPath -Name 'node'
$nodeVersion = & $NodePath --version
if ($LASTEXITCODE -ne 0 -or $nodeVersion -notmatch '^v(\d+)\.' -or [int]$Matches[1] -lt 24) {
    throw 'Agent Autoloop 需要 Node.js 24 或更新版本。'
}
$GitPath = Get-ApplicationPath -Name 'git'
$EntryPath = Join-Path $AutoloopPath 'bin\agent-autoloop.ts'
$previousHome = [Environment]::GetEnvironmentVariable('AGENT_AUTOLOOP_HOME', 'Process')
$previousRules = [Environment]::GetEnvironmentVariable('AGENT_AUTOLOOP_RULES', 'Process')

try {
    # Both variables are local to this process and its children. Never touch CODEX_HOME or PATH.
    $env:AGENT_AUTOLOOP_HOME = $StatePath
    $env:AGENT_AUTOLOOP_RULES = $RulesFile

    if (-not (Test-Path -LiteralPath $EntryPath -PathType Leaf)) {
        if ($Mode -ne 'Setup') { throw '尚未准备 Autoloop 源码，请先执行 -Mode Setup。' }
        if (Test-Path -LiteralPath $AutoloopPath) {
            throw "指定目录不是完整的 Autoloop 源码：$AutoloopPath。请选择已存在的 v1.9.0 仓库或一个新目录。"
        }
        New-Item -ItemType Directory -Path (Split-Path -Parent $AutoloopPath) -Force | Out-Null
        Invoke-Checked -Program $GitPath -Arguments @(
            'clone', '--branch', $PinnedVersion, '--depth', '1',
            'https://github.com/KKKKhazix/agent-autoloop.git', $AutoloopPath
        )
    }
    $headCommit = & $GitPath -C $AutoloopPath rev-parse HEAD
    if ($LASTEXITCODE -ne 0) { throw '无法读取 Autoloop 仓库提交。' }
    $tagCommit = & $GitPath -C $AutoloopPath rev-parse "$PinnedVersion^{commit}"
    if ($LASTEXITCODE -ne 0 -or $headCommit -ne $tagCommit) {
        throw "Autoloop 必须固定在 $PinnedVersion。请为该版本使用独立目录，脚本不会切换已有仓库。"
    }
    $trackedChanges = & $GitPath -C $AutoloopPath status --porcelain --untracked-files=no
    if ($LASTEXITCODE -ne 0 -or $trackedChanges) {
        throw 'Autoloop 源码存在修改或无法检查。请使用干净的固定版本目录。'
    }
    $entryArguments = @('--disable-warning=ExperimentalWarning', $EntryPath)

    if ($Mode -eq 'Setup') {
        if (-not (Test-Path -LiteralPath $PilotScript -PathType Leaf)) {
            throw "找不到项目审核脚本：$PilotScript。请先更新包含审核试验功能的代码。"
        }
        if (-not (Test-Path -LiteralPath $InputPath -PathType Leaf)) { throw "输入文件不存在：$InputPath" }
        $request = Get-Content -LiteralPath $InputPath -Raw -Encoding UTF8 | ConvertFrom-Json
        if (-not $request.PSObject.Properties['brief'] -or -not $request.PSObject.Properties['plan']) {
            throw '输入 JSON 需要 brief 和 plan，具体格式见 docs/ppt-review-autoloop.md。'
        }
        $PythonPath = Find-PythonPath -RequestedPath $PythonPath -RootPath $ProjectPath
        foreach ($value in @($PythonPath, $PilotScript, $InputPath, $OutputPath, $ApiBase)) {
            if ($value -match '\{(prompt|model|effort|cwd|context)\}') {
                throw '路径或服务地址不能包含 Autoloop 的命令占位符。'
            }
        }
        $config = $null
        if (Test-Path -LiteralPath $ConfigFile) {
            $config = Get-Content -LiteralPath $ConfigFile -Raw -Encoding UTF8 | ConvertFrom-Json
            if (Test-HubOnline -Url $config.url) {
                throw '此试验中台正在运行。请先完成或停止当前任务，再在 Up 终端按 Ctrl+C，随后重新 Setup。'
            }
            if ($Port -eq 0) { $Port = ([System.Uri]$config.url).Port }
        }
        if ($Port -eq 0) { $Port = Get-FreeLocalPort }
        if (-not $config) {
            # init's --command parser is not a JSON parser. Use one plain executable for
            # bootstrap, then replace it with the fixed Python argv array before Up.
            # This avoids nested native-command quoting in Windows PowerShell 5.1.
            Invoke-Checked -Program $NodePath -Arguments ($entryArguments + @(
                'init', '--command', 'node', '--no-service', '--port', [string]$Port
            ))
            $config = Get-Content -LiteralPath $ConfigFile -Raw -Encoding UTF8 | ConvertFrom-Json
        }
        $config.url = "http://127.0.0.1:$Port"
        $config.hub.listen = "127.0.0.1:$Port"
        $config.hub.publicUrl = $config.url
        $config.worker | Add-Member -NotePropertyName capacity -NotePropertyValue 1 -Force
        $config | Add-Member -NotePropertyName channels -NotePropertyValue ([pscustomobject]@{}) -Force
        Write-JsonFile -Path $ConfigFile -Value $config

        $commandArguments = @(
            $PythonPath, $PilotScript, '--input', $InputPath, '--output', $OutputPath,
            '--api-base', $ApiBase, '--autoloop'
        )
        $rules = [ordered]@{
            timezone = 'Asia/Shanghai'
            sources = @{ local = @{ name = '本机审核试验' } }
            agents = @{
                'ppt-review-api' = @{
                    name = 'PPT 本地 API 审核'
                    worker = $config.worker.name
                    use = 'command'
                    access = 'read'
                    maxActive = 1
                    timeout = 30
                    command = $commandArguments
                }
            }
            channels = @{}
            rules = @(@{
                name = $RuleName
                when = @{ source = 'local'; types = @('ppt.review.requested') }
                to = 'ppt-review-api'
                cwd = $ProjectPath
                group = 'ppt-review-pilot'
                parallel = 1
                maxActive = 1
                tell = 'needed'
            })
            elsewhere = @()
        }
        Write-JsonFile -Path $RulesFile -Value $rules
        Invoke-Checked -Program $NodePath -Arguments ($entryArguments + @('check'))
        New-Item -ItemType Directory -Path $OutputPath -Force | Out-Null
        Write-JsonFile -Path $SettingsFile -Value ([ordered]@{
            version = $PinnedVersion
            autoloop_path = $AutoloopPath
            project_path = $ProjectPath
            input_path = $InputPath
            output_path = $OutputPath
            api_base = $ApiBase
            python_path = $PythonPath
            port = $Port
        })
        Write-Host "配置完成：$RulesFile"
        Write-Host "审核接口根地址：$ApiBase"
        Write-Host "报告基目录：$OutputPath"
        Write-Host '下一步：在本终端执行相同参数的 -Mode Up，并在另一终端执行 -Mode Run。'
        Write-Host '尚未调用模型；API 的认证环境变量如有需要，应在 Up 终端设置。'
        return
    }

    if (-not $settings -or -not (Test-Path -LiteralPath $ConfigFile)) {
        throw '尚未完成此项目的审核试验配置，请先执行 -Mode Setup。'
    }
    if ($settings.project_path -ne $ProjectPath -or $settings.input_path -ne $InputPath -or
        $settings.output_path -ne $OutputPath -or $settings.api_base -ne $ApiBase -or
        $settings.autoloop_path -ne $AutoloopPath -or ($Port -ne 0 -and $Port -ne $settings.port)) {
        throw '当前参数与 Setup 时固定的任务不同。请停止 Up 后，用新参数重新 Setup。'
    }
    Invoke-Checked -Program $NodePath -Arguments ($entryArguments + @('check'))
    switch ($Mode) {
        'Up' {
            Write-Host "中台前台运行；审核输入：$InputPath"
            Write-Host "API：$ApiBase；请保留此终端，在另一终端运行 -Mode Run。"
            Invoke-Checked -Program $NodePath -Arguments ($entryArguments + @('up'))
        }
        'Run' {
            if (-not (Test-Path -LiteralPath $InputPath -PathType Leaf)) { throw "输入文件不存在：$InputPath" }
            $stateText = & $NodePath @entryArguments status --json
            if ($LASTEXITCODE -ne 0) { throw '无法读取中台状态，请先在另一终端执行 -Mode Up。' }
            $state = ($stateText -join "`n") | ConvertFrom-Json
            $activeRuns = @($state.runs | Where-Object {
                $_.rule -eq $RuleName -and $_.state -in @('queued', 'claimed', 'unknown')
            })
            if ($activeRuns.Count -gt 0) {
                throw "已有未结束的审核轮次：$(($activeRuns.id) -join ', ')。先查看 Status，不要重复提交。"
            }
            $subject = 'pilot-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0, 8)
            Invoke-Checked -Program $NodePath -Arguments ($entryArguments + @('run', $RuleName, '--subject', $subject))
            Write-Host '已提交审核试验。用 -Mode Status 查看进度，并打开本次报告目录中的 comparison.html。'
            Write-Host '中台显示本轮结束，不代表教学内容已通过审核；以 review.json 的结论为准。'
        }
        'Status' {
            Invoke-Checked -Program $NodePath -Arguments ($entryArguments + @('status'))
        }
    }
}
finally {
    [Environment]::SetEnvironmentVariable('AGENT_AUTOLOOP_HOME', $previousHome, 'Process')
    [Environment]::SetEnvironmentVariable('AGENT_AUTOLOOP_RULES', $previousRules, 'Process')
}
