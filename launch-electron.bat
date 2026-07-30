@echo off
rem Launch Electron HUD (brain must already be on :8765, or start it first).
cd /d "%~dp0"

if not exist "frontend\node_modules\" (
  echo Installing frontend deps...
  pushd frontend
  call npm install
  popd
)

start "N.E.U.R.O.N Brain" /min cmd /c "python backend\server.py"
timeout /t 2 /nobreak >nul
pushd frontend
call npm run dev
popd
