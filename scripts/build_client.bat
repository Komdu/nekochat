@echo off
REM Сборка Windows-клиента (PySide6 + PyInstaller) в один exe.
REM Чат — нативные QWidgets (client_ui.*), БЕЗ QtWebEngine:
REM сборка заметно легче (~60-90MB вместо 199MB).
REM Требуется Python 3.12 x64. Запуск:  scripts\build_client.bat
setlocal
cd /d "%~dp0.."

set PY=python
if not "%PYTHON%"=="" set PY=%PYTHON%

REM venv предпочтительно из текущего окружения (venv-dev уже настроен):
if exist "venv-dev\Scripts\python.exe" (
  set PY=%CD%\venv-dev\Scripts\python.exe
)

%PY% -m pip install -q -r requirements-client.txt

del /q Nekochat.spec 2>nul

%PY% -m PyInstaller --noconfirm --onefile --name Nekochat ^
  --add-data "icon.png;." ^
  --hidden-import PySide6.QtWebSockets ^
  client_app.py
if errorlevel 1 goto :fail

echo.
echo ===== BUILD-OK =====
echo Готово: dist\Nekochat.exe
dir dist\Nekochat.exe
exit /b 0

:fail
echo Сборка упала, смотри вывод выше.
echo ===== BUILD-FAIL =====
exit /b 1