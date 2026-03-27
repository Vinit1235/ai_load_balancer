import asyncio
import json
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from datetime import datetime
from master.state_manager import state_manager

router = APIRouter()

clients = set()


def build_cluster_snapshot() -> dict:
    nodes = state_manager.get_active_nodes()
    tasks = state_manager.get_all_tasks()

    running = 0
    pending = 0
    completed = 0
    failed = 0

    for task in tasks:
        status = (task.get("status") or "").upper()
        if status in {"RUNNING", "ASSIGNED"}:
            running += 1
        elif status == "PENDING":
            pending += 1
        elif status == "COMPLETED":
            completed += 1
        elif status in {"FAILED", "CANCELLED"}:
            failed += 1

    return {
        "working": running,
        "pending": pending,
        "completed": completed,
        "failed": failed,
        "nodes_online": len(nodes),
        "nodes": nodes,
    }

async def broadcast_metrics():
    while True:
        if clients:
            data = {
                "type": "cluster_update",
                "timestamp": datetime.utcnow().isoformat(),
                "data": build_cluster_snapshot()
            }
            message = json.dumps(data)
            to_remove = set()
            for ws in clients:
                try:
                    await ws.send_text(message)
                except Exception:
                    to_remove.add(ws)
            clients.difference_update(to_remove)
        await asyncio.sleep(1)

@router.websocket("/ws/metrics")
async def ws_metrics(websocket: WebSocket):
    await websocket.accept()
    clients.add(websocket)
    try:
        while True:
            # Keep socket open; updates are sent by background broadcaster.
            await asyncio.sleep(10)
    except WebSocketDisconnect:
        clients.discard(websocket)

@router.websocket("/ws/tasks/{id}")
async def ws_task(websocket: WebSocket, id: int):
    await websocket.accept()
    try:
        while True:
            task_status = None
            for task in state_manager.get_all_tasks():
                if str(task.get("id")) == str(id):
                    task_status = task
                    break

            data = {
                "type": "task_update",
                "timestamp": datetime.utcnow().isoformat(),
                "data": task_status or {"task_id": id, "status": "not_found"}
            }
            await websocket.send_text(json.dumps(data))
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        pass

# To be started in FastAPI startup event
background_task = None

def start_background_task(app):
    global background_task
    if background_task is None:
        loop = asyncio.get_event_loop()
        background_task = loop.create_task(broadcast_metrics())
