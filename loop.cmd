@echo off
setlocal
set "LOOP_HOME=%~dp0"

if not exist "%LOOP_HOME%src\loop_cli.py" (
  echo [loop] ERROR: installation is incomplete. Missing: "%LOOP_HOME%src\loop_cli.py" 1>&2
  exit /b 2
)

where python >nul 2>nul
if errorlevel 1 (
  echo [loop] ERROR: python not found on PATH. 1>&2
  exit /b 2
)

python -u "%LOOP_HOME%src\loop_cli.py" %*
set "RC=%ERRORLEVEL%"
exit /b %RC%
