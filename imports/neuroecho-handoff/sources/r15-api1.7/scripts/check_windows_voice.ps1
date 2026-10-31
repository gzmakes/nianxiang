$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$config = Join-Path $root 'server\voice-settings.json'
$credential = Join-Path $env:USERPROFILE '.tencentcloud\credentials'
Write-Host "Config: $config $(if (Test-Path $config) {'present'} else {'missing'})"
Write-Host "Tencent credentials: $credential $(if (Test-Path $credential) {'present'} else {'missing'})"
$service = try { Invoke-RestMethod 'http://127.0.0.1:18787/api/voice/status' -TimeoutSec 5 } catch { $null }
if ($service) { $service | ConvertTo-Json } else { Write-Host 'Nianxiang service: unavailable' }
$tts = try { Test-NetConnection 127.0.0.1 -Port 9880 -InformationLevel Quiet } catch { $false }
Write-Host "GPT-SoVITS 9880: $(if ($tts) {'reachable'} else {'unavailable'})"
if (-not (Test-Path $credential)) { exit 2 }
if (-not $service -or -not $service.asr_credentials_configured) { exit 3 }
if (-not $tts) { exit 4 }
Write-Host 'Local voice prerequisites are ready.'
