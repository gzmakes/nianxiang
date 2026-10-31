@echo off
setlocal
set "PROJECT=%~dp0imports\neuroecho-handoff\sources\r15-api1.7"
if not exist "%PROJECT%\scripts\start_windows_web.cmd" (
  echo 找不到念响服务目录: "%PROJECT%"
  exit /b 1
)
call "%PROJECT%\scripts\start_windows_web.cmd" %*
