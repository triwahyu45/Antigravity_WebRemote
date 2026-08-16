Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "D:\Data_Lokal\Kuliah\Tri Wahyu (22518241023)\Local_AI_Mobile_Agent"
WshShell.Run "pythonw.exe runner.py", 0, False
