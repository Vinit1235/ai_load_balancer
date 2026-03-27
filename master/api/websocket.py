import asyncio
import json
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from datetime import datetime

router = APIRouter()

clients = set()

async def broadcast_metrics():
    while True:
        if clients:
            data = {
                "type": "cluster_update",
                "timestamp": datetime.utcnow().isoformat(),
                "data": {"metrics": "example"}
            }
            message = json.dumps(data)
            to_remove = set()
            for ws in clients:
                try:
                    await ws.send_text(message)
                except Exception:
                    to_remove.add(ws)
            clients.difference_update(to_remove)
        await asyncio.sleep(0.5)

@router.websocket("/ws/metrics")
async def ws_metrics(websocket: WebSocket):
    await websocket.accept()
    clients.add(websocket)
    try:
        while True:
            await websocket.receive_text()  # Keep connection alive
    except WebSocketDisconnect:
        clients.remove(websocket)

@router.websocket("/ws/tasks/{id}")
async def ws_task(websocket: WebSocket, id: int):
    await websocket.accept()
    try:
        while True:
            data = {
                "type": "task_update",
                "timestamp": datetime.utcnow().isoformat(),
                "data": {"task_id": id, "progress": 0}
            }
            await websocket.send_text(json.dumps(data))
            await asyncio.sleep(0.5)
    except WebSocketDisconnect:
        pass

# To be started in FastAPI startup event
background_task = None

def start_background_task(app):
    global background_task
    if background_task is None:
        loop = asyncio.get_event_loop()
        background_task = loop.create_task(broadcast_metrics())
