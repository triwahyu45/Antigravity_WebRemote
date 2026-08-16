import subprocess
import os
import sys

base_dir = r"D:\Data_Lokal\Kuliah\Tri Wahyu (22518241023)\Local_AI_Mobile_Agent"
python_exe = sys.executable
log_path = os.path.join(base_dir, "server.log")

log_f = open(log_path, "a", encoding="utf-8")

p = subprocess.Popen(
    [python_exe, "server.py"],
    cwd=base_dir,
    stdin=subprocess.DEVNULL,
    stdout=log_f,
    stderr=log_f,
    creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
)

print(f"[Runner] Permanent server launched with PID {p.pid}")
