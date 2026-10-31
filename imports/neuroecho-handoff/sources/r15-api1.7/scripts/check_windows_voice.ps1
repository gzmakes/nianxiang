param([string]$DataDir = "$env:LOCALAPPDATA\Nianxiang\data")
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$config = Join-Path $DataDir 'voice-settings.json'
Write-Host "Config: $config $(if (Test-Path $config) {'present'} else {'missing'})"
$service = try { Invoke-RestMethod 'http://127.0.0.1:18787/api/voice/status' -TimeoutSec 5 } catch { $null }
if ($service) { $service | ConvertTo-Json } else { Write-Host 'Nianxiang service: unavailable' }
if (-not $service) { exit 2 }
$provider = if (Test-Path $config) { try { (Get-Content $config -Raw | ConvertFrom-Json).tts.provider } catch { '' } } else { '' }
if ($provider -eq 'remote') {
  Write-Host 'Remote voice mode configured; gateway readiness is reported by /api/voice/status.'
  if (-not $service.tts_enabled -or $service.tts_provider -ne 'remote' -or $service.tts_state -notin @('ready','service_not_running')) { exit 3 }
  exit 0
}
$tts = try { Test-NetConnection 127.0.0.1 -Port 9880 -InformationLevel Quiet } catch { $false }
Write-Host "GPT-SoVITS 9880: $(if ($tts) {'reachable'} else {'unavailable'})"
if (-not $service.tts_enabled -or -not $service.tts_reference_audio -or -not $tts) { exit 3 }
Write-Host 'Local voice prerequisites are ready.'
