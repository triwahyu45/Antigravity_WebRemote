Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "%~dp0"
WshShell.Run "cmd /c python server.py", 0, False
