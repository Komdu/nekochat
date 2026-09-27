@echo off
REM Пересборка офлайн-бандла Material Web Components -> app\static\vendor\md.js
REM Требуется переносной Node.js в tools\node (см. README, раздел "Темы").
setlocal
set PATH=%~dp0..\tools\node;%PATH%
cd /d "%~dp0..\tools\material-build"
if not exist node_modules (npm i --no-audit --no-fund)
call node_modules\.bin\esbuild.cmd entry.js --bundle --minify --format=iife --target=es2022 --outfile=..\..\app\static\vendor\md.js
if errorlevel 1 goto :fail
echo Готово: app\static\vendor\md.js
exit /b 0
:fail
echo Сборка бандла упала.
exit /b 1
