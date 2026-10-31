param(
  [Parameter(Mandatory = $true)] [string]$GatewayBaseUrl,
  [Parameter(Mandatory = $true)] [string]$GatewayToken,
  [string]$DataDir = "$env:LOCALAPPDATA\Nianxiang\data"
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$server = Join-Path $root 'server'

if ([string]::IsNullOrWhiteSpace($GatewayBaseUrl)) { throw 'GatewayBaseUrl is required.' }
if ([string]::IsNullOrWhiteSpace($GatewayToken)) { throw 'GatewayToken is required.' }
if ($GatewayBaseUrl -notmatch '^https://') { throw 'GatewayBaseUrl must use HTTPS.' }

$base = $GatewayBaseUrl.TrimEnd('/')
if ($base -notmatch '/v1$') { $base = "$base/v1" }
$uri = [Uri]$base
if ($uri.Host -in @('127.0.0.1', 'localhost', '::1')) { throw 'Use a reachable HTTPS gateway URL for remote mode.' }

$template = Join-Path $server 'voice-settings.example.json'
if (-not (Test-Path $template)) { throw "Missing template: $template" }
$configPath = Join-Path $DataDir 'voice-settings.json'
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
$config = [System.IO.File]::ReadAllText($template, [Text.UTF8Encoding]::new($false)) | ConvertFrom-Json
$config.tts.enabled = $true
$config.tts.provider = 'remote'
$config.tts.gateway_url = $base
$config.tts.gateway_token = $GatewayToken
$config.tts.persona_id = 'whale'
$config.tts.timeout_seconds = 120

$json = $config | ConvertTo-Json -Depth 8
[System.IO.File]::WriteAllText($configPath, $json, [Text.UTF8Encoding]::new($false))

Write-Host "Wrote remote voice config: $configPath"
Write-Host "Gateway: $base"
Write-Host 'The token is stored only in the ignored local voice-settings.json file.'
Write-Host "Start R15 with: $root\scripts\start_windows_web.cmd"
