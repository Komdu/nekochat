# Windows-клиент: сборка exe

PyInstaller не умеет кросс-компилировать, поэтому Windows-exe собирается
на Windows (или в GitHub Actions).

## Способ 1 — собрать самому на Windows

Нужен Python 3.12 (x64) с сайта python.org. Затем в папке проекта:

```bat
scripts\build_client.bat
```

Результат: `dist\Nekochat.exe`.

## Способ 2 — GitHub Actions

Положи репозиторий на GitHub, файл `.github/workflows/build-windows.yml`
уже готов. В нём: Actions → build-windows-client → Run workflow.
Готовый `Nekochat-exe` скачается из артефактов (Actions → бранч → Artifacts).

## Запуск

```bat
Nekochat.exe                          :: адресник серверов (двойной клик — подключиться)
Nekochat.exe --url https://...        :: сразу к серверу, минуя адресник
```