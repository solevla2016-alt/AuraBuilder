# Запускает локальные серверы AuraBuilder, если их порты свободны.
#
# Скрипт рассчитан на повторный запуск: планировщик Windows вызывает его
# раз в минуту, и он поднимает только то, что действительно упало.
# API — Django на 8001, интерфейс — Vite на 5173.
#
# Планировщик запускает его не напрямую, а через dev-servers.vbs: прямой
# запуск консольной программы каждый раз на секунду показывал окно
# PowerShell поверх экрана и забирал фокус у активного окна.

$ErrorActionPreference = 'SilentlyContinue'

$root = Split-Path -Parent $PSScriptRoot
$logDir = Join-Path $env:TEMP 'aurabuilder'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

function Test-Port([int]$Port) {
    return [bool](Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}

if (-not (Test-Port 8001)) {
    Start-Process -FilePath 'C:\Windows\System32\cmd.exe' `
        -ArgumentList '/c', 'set USE_SQLITE=1&& "..\.venv\Scripts\python.exe" -X utf8 manage.py runserver 127.0.0.1:8001 --noreload' `
        -WorkingDirectory (Join-Path $root 'apps') `
        -RedirectStandardOutput (Join-Path $logDir 'api.out.log') `
        -RedirectStandardError (Join-Path $logDir 'api.err.log') `
        -WindowStyle Hidden
}

if (-not (Test-Port 5173)) {
    Start-Process -FilePath 'C:\Windows\System32\cmd.exe' `
        -ArgumentList '/c', 'npm run dev -- --host 127.0.0.1 --port 5173' `
        -WorkingDirectory (Join-Path $root 'apps\web') `
        -RedirectStandardOutput (Join-Path $logDir 'web.out.log') `
        -RedirectStandardError (Join-Path $logDir 'web.err.log') `
        -WindowStyle Hidden
}
