@echo off
REM Сборка нативного клиента на React + Tauri (v2) в один exe.
REM Требуется: Node.js LTS (npm), Rust (rustup), Visual Studio Build Tools
REM (C++ workload) и WebView2 (обычно уже в Windows 11).
REM Запуск:  scripts\build_tauri.bat
setlocal
cd /d "%~dp0..\desktop" || goto :fail

where node >nul 2>nul || (echo [ERR] Node.js не найден в PATH && goto :fail)
where npm >nul 2>nul || (echo [ERR] npm не найден в PATH && goto :fail)

echo ==== npm install ====
call npm install
if errorlevel 1 goto :fail

echo ==== tauri build (release, nsis) ====
call npm run tauri -- build --bundles nsis
if errorlevel 1 (
  echo [warn] NSIS-бандл не собрался, пробую без бандла...
  call npm run tauri -- build --no-bundle
  if errorlevel 1 goto :fail
)

echo.
echo ===== BUILD-OK =====
echo exe: %CD%\src-tauri\target\release\nekochat.exe
dir /b "src-tauri\target\release\nekochat.exe" 2>nul
dir /b "src-tauri\target\release\bundle\nsis\*.exe" 2>nul
exit /b 0

:fail
echo Сборка упала, смотри вывод выше.
echo ===== BUILD-FAIL =====
exit /b 1