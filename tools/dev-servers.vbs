' Запускает сторож dev-servers.ps1 без окна консоли.
'
' Зачем обёртка: планировщик Windows запускает консольную программу с
' видимым окном, и флаг -WindowStyle Hidden у PowerShell срабатывает уже
' после создания консоли. На секунду поверх экрана появляется чёрное окно
' и забирает фокус. wscript.exe — программа без консоли, а WScript.Shell.Run
' с кодом 0 создаёт дочерний процесс сразу скрытым, поэтому окна нет вовсе.
'
' Путь собирается от расположения самого файла: в пути к репозиторию есть
' кириллица, и литерал в .vbs зависел бы от кодовой страницы системы.

Dim fso, shell, base, command
Set fso = CreateObject("Scripting.FileSystemObject")
base = fso.GetParentFolderName(WScript.ScriptFullName)

Set shell = CreateObject("WScript.Shell")
command = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & base & "\dev-servers.ps1"""
shell.Run command, 0, False
