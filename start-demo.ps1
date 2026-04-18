param(
    [string]$CondaEnv = "ito",
    [switch]$WithFrontend,
    [switch]$SkipDocker
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$FrontendEnvPath = Join-Path $RootDir "frontend\.env.local"
$BackendDir = Join-Path $RootDir "backend"
$DigitalHumanDir = Join-Path $RootDir "digital-human"
$FrontendDir = Join-Path $RootDir "frontend"

function Read-EnvFile {
    param([string]$Path)

    if (-not (Test-Path $Path)) {
        throw "Environment file not found: $Path"
    }

    $map = @{}
    foreach ($line in Get-Content $Path) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#")) {
            continue
        }

        $parts = $trimmed -split "=", 2
        if ($parts.Count -ne 2) {
            continue
        }

        $key = $parts[0].Trim()
        $value = $parts[1].Trim()
        if ($value.Length -ge 2) {
            if (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'"))) {
                $value = $value.Substring(1, $value.Length - 2)
            }
        }
        $map[$key] = $value
    }

    return $map
}

function New-CondaBootstrap {
    param([string]$EnvName)

    return @"
`$condaHook = (& conda 'shell.powershell' 'hook') | Out-String
Invoke-Expression `$condaHook
conda activate '$EnvName'
"@
}

function Start-ServiceWindow {
    param(
        [string]$Title,
        [string]$WorkingDirectory,
        [string]$CommandBody
    )

    $command = @"
`$host.UI.RawUI.WindowTitle = '$Title'
$CommandBody
"@

    Start-Process powershell -WorkingDirectory $WorkingDirectory -ArgumentList @(
        "-NoExit",
        "-Command",
        $command
    ) | Out-Null
}

$envMap = Read-EnvFile -Path $FrontendEnvPath

$qwenApiKey = $envMap["QWEN_API_KEY"]
if (-not $qwenApiKey) {
    throw "QWEN_API_KEY is missing in $FrontendEnvPath"
}

$qwenBaseUrl = $envMap["QWEN_BASE_URL"]
if (-not $qwenBaseUrl) {
    $qwenBaseUrl = "https://dashscope.aliyuncs.com/compatible-mode/v1"
}

$ttsQwenApiKey = $envMap["TTS_QWEN_API_KEY"]
if (-not $ttsQwenApiKey) {
    $ttsQwenApiKey = $qwenApiKey
}

$ttsQwenBaseUrl = $envMap["TTS_QWEN_BASE_URL"]
if (-not $ttsQwenBaseUrl) {
    $ttsQwenBaseUrl = "https://dashscope.aliyuncs.com/api/v1"
}

$voiceProfileModel = "qwen-vl-plus-latest"
$condaBootstrap = New-CondaBootstrap -EnvName $CondaEnv

if (-not $SkipDocker) {
    Write-Host "Starting Milvus with docker-compose..." -ForegroundColor Cyan
    & docker-compose -f (Join-Path $BackendDir "docker-compose.yml") up -d
}

$backendBody = @"
$condaBootstrap
`$env:OPENAI_API_KEY = '$qwenApiKey'
`$env:OPENAI_BASE_URL = '$qwenBaseUrl'
Set-Location '$BackendDir'
uvicorn src.rag.bootstrap:create_app --factory --host 0.0.0.0 --port 9527
"@

$digitalHumanBody = @"
$condaBootstrap
`$env:OPENAI_API_KEY = '$qwenApiKey'
`$env:OPENAI_BASE_URL = '$qwenBaseUrl'
`$env:AVATAR_TTS_API_KEY = '$ttsQwenApiKey'
`$env:AVATAR_TTS_BASE_URL = '$ttsQwenBaseUrl'
`$env:AVATAR_VOICE_PROFILE_MODEL = '$voiceProfileModel'
Set-Location '$DigitalHumanDir'
uvicorn avatar_service.main:create_app --factory --host 0.0.0.0 --port 8000
"@

Start-ServiceWindow -Title "ITO Backend" -WorkingDirectory $BackendDir -CommandBody $backendBody
Start-ServiceWindow -Title "ITO Digital Human" -WorkingDirectory $DigitalHumanDir -CommandBody $digitalHumanBody

if ($WithFrontend) {
    $frontendBody = @"
Set-Location '$FrontendDir'
pnpm dev
"@
    Start-ServiceWindow -Title "ITO Frontend" -WorkingDirectory $FrontendDir -CommandBody $frontendBody
}

Write-Host ""
Write-Host "Started services:" -ForegroundColor Green
Write-Host "  backend        http://localhost:9527/v1/health"
Write-Host "  digital-human  http://localhost:8000/health"
if ($WithFrontend) {
    Write-Host "  frontend       http://localhost:3000"
} else {
    Write-Host "Frontend not started. Run 'pnpm dev' in $FrontendDir if needed."
}
