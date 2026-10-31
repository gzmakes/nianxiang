param(
  [string]$ReferenceAudio = '',
  [string]$FfmpegPath = '',
  [switch]$EnableTts
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$server = Join-Path $root 'server'
$configPath = Join-Path $server 'voice-settings.json'
$examplePath = Join-Path $server 'voice-settings.example.json'

if (-not (Test-Path $examplePath)) { throw "Missing template: $examplePath" }

if ([string]::IsNullOrWhiteSpace($FfmpegPath)) {
  $ffmpeg = Get-Command ffmpeg.exe -ErrorAction SilentlyContinue
  if ($ffmpeg) { $FfmpegPath = $ffmpeg.Source }
}
$ffmpegAvailable = -not [string]::IsNullOrWhiteSpace($FfmpegPath) -and ((Test-Path $FfmpegPath) -or $FfmpegPath -eq 'ffmpeg')
if ([string]::IsNullOrWhiteSpace($FfmpegPath) -or -not (Test-Path $FfmpegPath)) {
  Write-Warning 'FFmpeg was not found. ASR will remain disabled until you pass -FfmpegPath or add ffmpeg.exe to PATH.'
  $FfmpegPath = 'ffmpeg'
}

if ($EnableTts -and [string]::IsNullOrWhiteSpace($ReferenceAudio)) {
  throw 'TTS setup needs -ReferenceAudio with a local WAV reference file. ASR-only setup can omit -EnableTts.'
}
if ($EnableTts -and -not (Test-Path $ReferenceAudio)) { throw "Reference audio not found: $ReferenceAudio" }

$utf8 = [System.Text.UTF8Encoding]::new($false)
$config = [System.IO.File]::ReadAllText($examplePath, $utf8) | ConvertFrom-Json
$config.asr.enabled = $false
$config.asr.ffmpeg_path = $FfmpegPath
$config.tts.enabled = [bool]($EnableTts -and (Test-Path $ReferenceAudio))
if ($EnableTts) { $config.tts.ref_audio_path = $ReferenceAudio }
$json = $config | ConvertTo-Json -Depth 8
[System.IO.File]::WriteAllText($configPath, $json, [System.Text.UTF8Encoding]::new($false))

Write-Host "Wrote local voice config: $configPath"
Write-Host 'Speech input uses browser-local SpeechRecognition; Tencent Cloud credentials are not required.'
Write-Host 'This script never writes credentials or copies private audio into the repository.'
