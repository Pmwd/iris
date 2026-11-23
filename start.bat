@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [Iris] 未找到 .venv。
  echo 请先在仓库根目录运行：
  echo   py -3.12 -m venv .venv
  echo   .\.venv\Scripts\python.exe -m pip install -e "backend[dev]"
  pause
  exit /b 1
)

if not exist "frontend\dist\index.html" (
  echo [Iris] 未找到前端构建产物，正在构建...
  pushd frontend
  call npm install
  call npm run build
  popd
)

echo [Iris] 启动后端与已构建前端：http://127.0.0.1:8000
echo [Iris] 关闭此窗口或按 Ctrl+C 停止服务。
".venv\Scripts\python.exe" -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
pause
