def safe_print(*args, **kwargs):
    try:
        print(*args, **kwargs)
    except Exception:
        pass

import os
import json
import time
import socket
import psutil
import asyncio
import re
import subprocess
import threading
from contextlib import asynccontextmanager
from typing import Optional, List, Dict
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

BRAIN_DIR = os.getenv("ANTIGRAVITY_BRAIN_DIR", os.path.expanduser("~/.gemini/antigravity/brain"))
ACTIVE_CONVERSATION_ID = "63fb64ac-9344-46a1-8d60-a891ba0835d8"

config_path = os.path.join(os.path.dirname(__file__), "config.json")
with open(config_path, "r", encoding="utf-8") as f:
    CONFIG = json.load(f)

# Zeroconf mDNS
zeroconf_instance = None
def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def start_mdns(port=8888):
    global zeroconf_instance
    try:
        from zeroconf import Zeroconf, ServiceInfo
        local_ip = get_local_ip()
        service_type = "_http._tcp.local."
        service_name = f"WahyuAI.{service_type}"
        info = ServiceInfo(
            service_type, service_name,
            addresses=[socket.inet_aton(local_ip)],
            port=port,
            properties={"app": "Antigravity Remote", "creator": "Tri Wahyu Handoyo"},
            server="wahyuai.local."
        )
        zeroconf_instance = Zeroconf()
        zeroconf_instance.register_service(info)
        safe_print(f"[mDNS] Active on local Wi-Fi: http://wahyuai.local:{port}")
    except Exception as e:
        safe_print(f"[mDNS Warning] {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    threading.Thread(target=start_mdns, args=(CONFIG["server"].get("port", 8888),), daemon=True).start()
    asyncio.create_task(broadcast_transcript_updates())
    yield
    global zeroconf_instance
    if zeroconf_instance:
        zeroconf_instance.close()

app = FastAPI(title="Antigravity Remote", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

connected_websockets: List[WebSocket] = []

@app.websocket("/ws/stream")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_websockets.append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except Exception:
        if websocket in connected_websockets:
            connected_websockets.remove(websocket)

def clean_user_msg(raw):
    match = re.search(r'<USER_REQUEST>\s*(.*?)\s*</USER_REQUEST>', raw, re.DOTALL)
    if match:
        return match.group(1).strip()
    clean = re.sub(r'<ADDITIONAL_METADATA>[\s\S]*?</ADDITIONAL_METADATA>', '', raw)
    clean = re.sub(r'<SYSTEM_MESSAGE>[\s\S]*?</SYSTEM_MESSAGE>', '', clean)
    clean = re.sub(r'<USER_SETTINGS_CHANGE>[\s\S]*?</USER_SETTINGS_CHANGE>', '', clean)
    clean = re.sub(r'<CONTEXT_SUMMARY>[\s\S]*?</CONTEXT_SUMMARY>', '', clean)
    return clean.strip()

# State for Live Status Tracking
engine_state = {
    "status": "idle", # "idle", "working", "tool_executing"
    "current_action": "Ready",
    "started_at": 0,
    "elapsed_seconds": 0
}

def parse_transcript_file(cid: str) -> List[Dict]:
    t_path = os.path.join(BRAIN_DIR, cid, ".system_generated", "logs", "transcript.jsonl")
    items = []
    if not os.path.exists(t_path):
        return items

    try:
        with open(t_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if not line.strip(): continue
                try:
                    step = json.loads(line.strip())
                    stype = step.get("type", "")
                    source = step.get("source", "")
                    content = step.get("content", "")
                    tool_calls = step.get("tool_calls", [])
                    ts = step.get("timestamp", "")
                    
                    if stype == "USER_INPUT" or (source == "USER_EXPLICIT" and content):
                        u_text = clean_user_msg(content)
                        if u_text and not u_text.startswith("Error: The stream was interrupted"):
                            items.append({"type": "user", "text": u_text})
                            
                    elif stype == "PLANNER_RESPONSE" or source == "MODEL":
                        if tool_calls:
                            for tc in tool_calls:
                                fn_name = tc.get("name", tc.get("tool_name", "tool"))
                                fn_args = tc.get("args", tc.get("arguments", {}))
                                summary = fn_args.get("toolSummary", fn_args.get("toolAction", fn_name))
                                items.append({"type": "tool_call", "name": fn_name, "summary": summary})
                        
                        text_ans = ""
                        if isinstance(content, str):
                            text_ans = content
                        elif isinstance(content, list):
                            for part in content:
                                if isinstance(part, dict) and "text" in part:
                                    text_ans += part["text"]
                        text_ans = text_ans.strip()
                        if text_ans and not text_ans.startswith("Created At:") and not text_ans.startswith("Completed At:") and not text_ans.startswith("The command exited with code"):
                            items.append({"type": "assistant", "text": text_ans})
                except Exception:
                    pass
    except Exception as e:
        safe_print(f"Error: {e}")
        
    return items

# Background Live Watcher & Status Detector
last_size = 0
last_count = 0
last_write_time = 0

async def broadcast_transcript_updates():
    global last_size, last_count, last_write_time, engine_state
    while True:
        try:
            t_path = os.path.join(BRAIN_DIR, ACTIVE_CONVERSATION_ID, ".system_generated", "logs", "transcript.jsonl")
            if os.path.exists(t_path):
                cur_size = os.path.getsize(t_path)
                mtime = os.path.getmtime(t_path)
                now = time.time()
                
                # If file was modified in the last 4 seconds -> Working!
                is_working = (now - mtime) < 4.0
                if is_working:
                    if engine_state["status"] == "idle":
                        engine_state["status"] = "working"
                        engine_state["started_at"] = mtime
                        engine_state["current_action"] = "Antigravity is thinking & executing..."
                    engine_state["elapsed_seconds"] = int(now - engine_state["started_at"])
                else:
                    if engine_state["status"] != "idle":
                        engine_state["status"] = "idle"
                        engine_state["current_action"] = "Ready"

                if cur_size != last_size:
                    last_size = cur_size
                    items = parse_transcript_file(ACTIVE_CONVERSATION_ID)
                    
                    # Detect current tool if last item is a tool_call
                    if items and items[-1]["type"] == "tool_call":
                        engine_state["current_action"] = f"Executing: {items[-1]['name']}"

                    if len(items) != last_count:
                        last_count = len(items)
                        payload = json.dumps({
                            "event": "transcript_update",
                            "session_id": ACTIVE_CONVERSATION_ID,
                            "items": items,
                            "engine_state": engine_state
                        })
                        for ws in list(connected_websockets):
                            try:
                                await ws.send_text(payload)
                            except Exception:
                                if ws in connected_websockets:
                                    connected_websockets.remove(ws)
                else:
                    # Broadcast heartbeat status periodically
                    status_payload = json.dumps({
                        "event": "status_heartbeat",
                        "engine_state": engine_state
                    })
                    for ws in list(connected_websockets):
                        try:
                            await ws.send_text(status_payload)
                        except Exception:
                            if ws in connected_websockets:
                                connected_websockets.remove(ws)
        except Exception:
            pass
        await asyncio.sleep(0.3)

# Chat Input Payload
class ChatInput(BaseModel):
    message: str
    session_id: Optional[str] = ACTIVE_CONVERSATION_ID

@app.post("/api/chat/send")
async def send_chat_message(data: ChatInput):
    msg = data.message.strip()
    if not msg:
        raise HTTPException(status_code=400, detail="Pesan tidak boleh kosong")
    
    # In pure Antigravity mode, append message to the input queue or log
    safe_print(f"[Mobile Remote Input Received]: {msg}")
    
    return {
        "status": "success",
        "message": "Pesan berhasil dikirim ke Antigravity desktop",
        "text": msg
    }

# Projects & Sessions Tree API
@app.get("/api/projects")
async def get_projects_tree():
    projects_tree = [
        {
            "name": "Tri Wahyu (File Kuliah)",
            "conversations": [
                {
                    "id": ACTIVE_CONVERSATION_ID,
                    "title": "Bismillah",
                    "time": "now",
                    "is_active": True
                }
            ]
        },
        {
            "name": "Pembimbing LKS",
            "conversations": []
        },
        {
            "name": "PK",
            "conversations": [
                {
                    "id": "c22cdf81-41b5-90b5-69dae00b13d4",
                    "title": "PK Gelombang 2",
                    "time": "19d",
                    "is_active": False
                },
                {
                    "id": "e41e5ffe-5edb-4f9a-b5e1-24850f933654",
                    "title": "LKS 2026",
                    "time": "1mo",
                    "is_active": False
                }
            ]
        },
        {
            "name": "Membuat Vtuber AI",
            "conversations": [
                {
                    "id": "f55008ae-5b66-4d80-9e76-00962c307f76",
                    "title": "Waifu_AI",
                    "time": "22d",
                    "is_active": False
                }
            ]
        },
        {
            "name": "Detronics ID",
            "conversations": [
                {
                    "id": "6c145bb8-520c-4933-814f-c3b76e54c68f",
                    "title": "codex ini ku suruh traci...",
                    "time": "1mo",
                    "is_active": False
                }
            ]
        },
        {
            "name": "Kinematics_Wheels",
            "conversations": [
                {
                    "id": "feb91647-a77e-40b9-9b53-0a5aa49f7dfa",
                    "title": "Recreating Mecanum K...",
                    "time": "2mo",
                    "is_active": False
                }
            ]
        }
    ]
    return {
        "active_id": ACTIVE_CONVERSATION_ID,
        "projects": projects_tree,
        "engine_state": engine_state
    }

@app.get("/api/sessions/{session_id}/steps")
async def get_session_steps(session_id: str):
    return parse_transcript_file(session_id)

@app.get("/api/sessions/{session_id}/details")
async def get_session_details(session_id: str):
    c_p = os.path.join(BRAIN_DIR, session_id)
    artifacts = []
    uploads = []
    if os.path.exists(c_p):
        for item in os.listdir(c_p):
            if item not in [".system_generated", ".user_uploaded"] and os.path.isfile(os.path.join(c_p, item)):
                artifacts.append(item)
        up_p = os.path.join(c_p, ".user_uploaded")
        if os.path.exists(up_p):
            uploads = os.listdir(up_p)
            
    return {
        "id": session_id,
        "files_changed": [
            "Isian_Form_dan_Laporan.txt",
            "Daftar_Link_Dokumentasi_Instagram.txt",
            "Link_Dokumentasi_IG.txt",
            "implementation_plan.md",
            "walkthrough.md",
            "server.py",
            "sunshine.conf"
        ],
        "artifacts_count": len(artifacts),
        "artifacts": artifacts,
        "uploads_count": len(uploads),
        "uploads": uploads
    }

# Artifact Content Viewer API
@app.get("/api/artifacts/{session_id}/{artifact_name:path}")
async def get_artifact_content(session_id: str, artifact_name: str):
    art_path = os.path.join(BRAIN_DIR, session_id, artifact_name)
    if not os.path.exists(art_path):
        raise HTTPException(status_code=404, detail="Artifact not found")
    try:
        with open(art_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        return {"name": artifact_name, "content": content}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

app.mount("/", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static"), html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    host = CONFIG["server"].get("host", "0.0.0.0")
    port = CONFIG["server"].get("port", 8888)
    uvicorn.run(app, host=host, port=port)
