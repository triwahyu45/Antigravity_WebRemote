Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

baseDir = "D:\Data_Lokal\Kuliah\Tri Wahyu (22518241023)\Local_AI_Mobile_Agent"
WshShell.CurrentDirectory = baseDir

pyPath = WshShell.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Programs\Python\Python312\pythonw.exe"

If Not fso.FileExists(pyPath) Then
    pyPath = "pythonw.exe"
End If

WshShell.Run """" & pyPath & """ """ & baseDir & "\tray_app.py""", 0, False
