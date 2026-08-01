@echo off
rem Launches the N.E.U.R.O.N brain (backend) + the 4:3 app window.
cd /d "%~dp0"

set PORT=8765
set "APP_URL=http://127.0.0.1:%PORT%/index.html"

where python >nul 2>nul
if errorlevel 1 (
  echo Python is required to run the NEURON brain. Install it from python.org.
  pause
  exit /b
)

rem Install backend dependencies on first run.
python -c "import fastapi, uvicorn, pyautogui, psutil, openai, uiautomation, playwright, faster_whisper, numpy" >nul 2>nul
if errorlevel 1 (
  echo Installing NEURON brain dependencies, one-time setup...
  python -m pip install -r requirements.txt
)

rem Make sure the local AI (Ollama) is running for the reasoning brain.
where ollama >nul 2>nul
if %errorlevel%==0 (
  tasklist /FI "IMAGENAME eq ollama.exe" | find /I "ollama.exe" >nul || start "" /min ollama serve
)

rem Start the brain (serves the frontend too).
start "N.E.U.R.O.N Brain" /min cmd /c "python backend\server.py"
timeout /t 3 /nobreak >nul

rem Note: first launch will ask for microphone permission once — click Allow.
where msedge >nul 2>nul
if %errorlevel%==0 (
  start "" msedge --app="%APP_URL%" --window-size=640,480 --window-position=400,150 --autoplay-policy=no-user-gesture-required
  exit /b
)

start "" chrome --app="%APP_URL%" --window-size=640,480 --window-position=400,150 --autoplay-policy=no-user-gesture-required
