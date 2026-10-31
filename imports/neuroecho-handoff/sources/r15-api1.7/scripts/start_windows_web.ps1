param(
  [int]$Port = 18787,
  [string]$DataDir = "$env:LOCALAPPDATA\Nianxiang\data"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
  py -3.11 -m venv (Join-Path $root ".venv")
  $python = Join-Path $root ".venv\Scripts\python.exe"
  & $python -m pip install -r (Join-Path $root "requirements.txt")
}
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
& $python (Join-Path $root "scripts\run_paired_service.py") --data-dir $DataDir --local-port $Port
