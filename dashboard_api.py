import asyncio
import json
import sqlite3
import os
from fastapi import FastAPI, BackgroundTasks, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from database import DatabaseManager
from config import Config

app = FastAPI(title="Bayse AMM Dashboard")

# Enable CORS for localhost frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

db = DatabaseManager()

class CommandInput(BaseModel):
    command: str  # support 'pause', 'resume', 'stop'

@app.get("/api/metrics")
async def get_metrics():
    """Retrieve fast metrics directly from SQLite database."""
    metrics = {
        "daily_pnl_ngn": 0,
        "active_windows": 0,
        "completed_windows": 0,
        "kill_switched_windows": 0,
        "total_capital_recovered": 0
    }
    try:
        metrics["daily_pnl_ngn"] = db.get_daily_pnl()
        
        # Read from DB for completed windows today
        with db._get_conn() as conn:
            cursor = conn.cursor()
            from datetime import datetime
            today_iso = datetime.utcnow().strftime("%Y-%m-%d")
            
            cursor.execute("SELECT COUNT(*), SUM(kill_switch_fired), SUM(burn_recovered_ngn) FROM windows WHERE opened_at LIKE ?", (f"{today_iso}%",))
            row = cursor.fetchone()
            if row and row[0]:
                metrics["completed_windows"] = row[0]
                metrics["kill_switched_windows"] = row[1] or 0
                metrics["total_capital_recovered"] = row[2] or 0
                
    except Exception as e:
        print(f"DB Error: {e}")
        
    # Read command state file if it exists to check if paused
    status = "Active"
    if os.path.exists("api_command.txt"):
        with open("api_command.txt", "r") as f:
            status = f.read().strip()
            
    metrics["bot_status"] = status
    
    return metrics

@app.post("/api/command")
async def issue_command(cmd: CommandInput):
    """Write command to signal file for main.py to detect."""
    valid_commands = ["pause", "resume", "stop", "emergency_stop"]
    if cmd.command.lower() in valid_commands:
        with open("api_command.txt", "w") as f:
            f.write(cmd.command.lower())
        return {"status": "success", "command": cmd.command}
    return {"status": "error", "message": "Invalid command"}

@app.websocket("/ws/logs")
async def websocket_logs(websocket: WebSocket):
    """Stream live bot.log JSONs directly to the frontend."""
    await websocket.accept()
    file_path = "bot.log"
    
    if not os.path.exists(file_path):
        # Create empty if missing
        with open(file_path, "a") as f:
             pass

    try:
        with open(file_path, "r") as f:
            # Seek to near end to avoid dumping whole history
            f.seek(0, 2)
            while True:
                line = f.readline()
                if not line:
                    await asyncio.sleep(0.5)
                    continue
                await websocket.send_text(line)
    except WebSocketDisconnect:
        print("Log WS Client Disconnected")
    except Exception as e:
        print(f"Log WS Error: {e}")
