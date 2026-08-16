Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "%~dp0\run_daemon.cmd", 0, False
