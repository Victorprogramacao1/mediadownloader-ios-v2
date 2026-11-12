@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Execute INICIAR_WINDOWS.bat primeiro.
  pause
  exit /b 1
)
echo Atualizando dependencias do MediaDownloader...
".venv\Scripts\python.exe" -m pip install --upgrade -r requirements.txt
if errorlevel 1 (
  echo Falha na atualizacao. Confira a conexao com a internet.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m pip check
".venv\Scripts\python.exe" -m yt_dlp --version
pause
