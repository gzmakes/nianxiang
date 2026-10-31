param(
  [int]$Port = 18787,
  [string]$DataDir = "$env:LOCALAPPDATA\Nianxiang\data"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
  # The service supports Python 3.10+; do not require one exact minor release.
  $candidates = @()
  $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
  if ($pyLauncher) { $candidates += ,@($pyLauncher.Source, @('-3')) }
  foreach ($name in @('python', 'python3')) {
    $command = Get-Command $name -ErrorAction SilentlyContinue
    if ($command) { $candidates += ,@($command.Source, @()) }
  }
  $selected = $null
  foreach ($candidate in $candidates) {
    $exe, $prefix = $candidate
    try {
      $version = & $exe @prefix -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
      if ($LASTEXITCODE -eq 0) {
        $parts = $version -split '\.'
        if ($parts.Count -ge 2 -and ([int]$parts[0] -gt 3 -or ([int]$parts[0] -eq 3 -and [int]$parts[1] -ge 10))) {
          $selected = $candidate
          break
        }
      }
    } catch { }
  }
  if (-not $selected) { throw "Python 3.10+ was not found. Install Python 3.11, 3.12, or 3.13 and add it to PATH." }
  & $selected[0] @($selected[1] + @('-m', 'venv', (Join-Path $root '.venv')))
  if ($LASTEXITCODE -ne 0) { throw "Could not create .venv; check the Python installation." }
  $python = Join-Path $root ".venv\Scripts\python.exe"
  & $python -m pip install -r (Join-Path $root "requirements.txt")
  if ($LASTEXITCODE -ne 0) { throw "Could not install dependencies; check the network and retry." }
}
if (-not (Test-Path $python)) { throw "The virtual environment was not created; remove the broken .venv and retry." }
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
Write-Host "Nianxiang service directory: $root"
Write-Host "Browser URL: http://127.0.0.1:$Port"
Write-Host "Model and sticker checks: http://127.0.0.1:$Port/api/config and /api/plugins"
& $python (Join-Path $root "scripts\run_paired_service.py") --data-dir $DataDir --local-port $Port
