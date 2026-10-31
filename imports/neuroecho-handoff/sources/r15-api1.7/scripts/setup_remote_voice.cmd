@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_remote_voice.ps1" %*
