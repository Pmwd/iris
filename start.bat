@echo off
setlocal EnableExtensions
cd /d "%~dp0"

rem ------------------------------------------------------------------
rem Resolve a working Python 3.12+ runtime and a project-local .venv.
rem The Claude Code CLI is a separate Node tool; it does not provide
rem Python. Iris's backend is Python/FastAPI, so this is a real prerequisite.
rem ------------------------------------------------------------------
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -c "import sys" >nul 2>nul
  if not errorlevel 1 goto :deps_ready
  echo [Iris] Existing .venv cannot run its Python; recreating it...
  rmdir /s /q .venv
)

set "PY_CMD="
call :detect py -3.12
if defined PY_CMD goto :make_venv
call :detect py -3
if defined PY_CMD goto :make_venv
call :detect python
if defined PY_CMD goto :make_venv
call :detect python3
if defined PY_CMD goto :make_venv

echo [Iris] No Python 3.12+ was detected.
echo        Iris backend is Python/FastAPI; the Claude Code CLI does not provide Python.
echo        Install Python 3.12+ (check "Add python.exe to PATH"), then run start.bat again.
echo        Download: https://www.python.org/downloads/
pause
exit /b 1

:detect
rem %* is a candidate command, e.g. "py -3.12" or "python".
%* -c "import sys; raise SystemExit(0 if sys.version_info >= (3,12) else 1)" >nul 2>nul
if errorlevel 1 exit /b 0
set "PY_CMD=%*"
exit /b 0

:make_venv
echo [Iris] Creating .venv with %PY_CMD% ...
%PY_CMD% -m venv .venv
if errorlevel 1 goto :fail
call :install_backend
if errorlevel 1 goto :fail

:deps_ready
rem The SDK is only needed for the default execution backend, but installing
rem the declared dependency keeps fresh checkouts consistent.
".venv\Scripts\python.exe" -c "import claude_agent_sdk" >nul 2>nul
if errorlevel 1 (
  call :install_backend
  if errorlevel 1 goto :fail
)

if not exist "frontend\dist\index.html" (
  where npm >nul 2>nul
  if errorlevel 1 (
    echo [Iris] npm/Node.js was not found. Install Node.js 20+ and retry.
    echo        Download: https://nodejs.org/
    pause
    exit /b 1
  )
  echo [Iris] Building frontend ...
  pushd frontend
  call npm install
  if errorlevel 1 (popd & goto :fail)
  call npm run build
  if errorlevel 1 (popd & goto :fail)
  popd
)

set "PORT=%~1"
if "%PORT%"=="" set "PORT=8000"
echo [Iris] Starting http://127.0.0.1:%PORT%
echo [Iris] Close this window or press Ctrl+C to stop.
".venv\Scripts\python.exe" -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port %PORT%
pause
exit /b 0

:install_backend
echo [Iris] Installing backend dependencies ...
".venv\Scripts\python.exe" -m pip install -e "backend[dev]"
if not errorlevel 1 exit /b 0
echo [Iris] Default PyPI failed; retrying with Tsinghua mirror ...
".venv\Scripts\python.exe" -m pip install -e "backend[dev]" -i https://pypi.tuna.tsinghua.edu.cn/simple
exit /b %errorlevel%

:fail
echo [Iris] Startup failed. Copy the error above for diagnosis.
pause
exit /b 1
