from fastapi import FastAPI, APIRouter, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field
from uuid import uuid4
import logging
from master.state_manager import state_manager

app = FastAPI(title="AI Load Balancer Master Node", docs_url="/docs")

# Middleware: CORS (allow all for development)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Middleware: Request logging
@app.middleware("http")
async def log_requests(request: Request, call_next):
    logger = logging.getLogger("uvicorn.access")
    logger.info(f"Request: {request.method} {request.url}")
    response = await call_next(request)
    return response

# Middleware: Error handling
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors(), "body": exc.body},
    )

@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc)},
    )

# Routers
api_router = APIRouter(prefix="/api/v1")


class TaskCreateRequest(BaseModel):
    id: str | None = None
    type: str = Field(default="synthetic_load")
    input_size: int = Field(default=0, ge=0)
    requires_gpu: bool = False
    priority: str = Field(default="medium")


def build_cluster_snapshot() -> dict:
    """Return a compact real-time view for API and UI display."""
    nodes = state_manager.get_active_nodes()
    tasks = state_manager.get_all_tasks()

    status_counts = {
        "pending": 0,
        "assigned": 0,
        "running": 0,
        "completed": 0,
        "failed": 0,
        "other": 0,
    }

    for task in tasks:
        status = (task.get("status") or "").upper()
        if status == "PENDING":
            status_counts["pending"] += 1
        elif status == "ASSIGNED":
            status_counts["assigned"] += 1
        elif status == "RUNNING":
            status_counts["running"] += 1
        elif status == "COMPLETED":
            status_counts["completed"] += 1
        elif status in {"FAILED", "CANCELLED"}:
            status_counts["failed"] += 1
        else:
            status_counts["other"] += 1

    return {
        "working": status_counts["running"] + status_counts["assigned"],
        "nodes_online": len(nodes),
        "tasks_total": len(tasks),
        "task_status": status_counts,
        "nodes": nodes,
        "recent_tasks": tasks[:25],
    }

@api_router.post("/tasks")
async def submit_task(payload: TaskCreateRequest):
    task_id = payload.id or str(uuid4())
    state_manager.create_task(
        {
            "id": task_id,
            "type": payload.type,
            "status": "PENDING",
            "input_size": payload.input_size,
            "requires_gpu": payload.requires_gpu,
            "priority": payload.priority,
        }
    )
    return {"ok": True, "task_id": task_id, "status": "PENDING"}

@api_router.get("/tasks")
async def list_tasks():
    return {"tasks": state_manager.get_all_tasks()}

@api_router.get("/tasks/{id}")
async def get_task(id: int):
    tasks = state_manager.get_all_tasks()
    for task in tasks:
        if str(task.get("id")) == str(id):
            return task
    raise HTTPException(status_code=404, detail=f"Task {id} not found")

@api_router.delete("/tasks/{id}")
async def cancel_task(id: int):
    tasks = state_manager.get_all_tasks()
    for task in tasks:
        if str(task.get("id")) == str(id):
            state_manager.update_task_status(str(id), "FAILED")
            return {"ok": True, "task_id": id, "status": "FAILED"}
    raise HTTPException(status_code=404, detail=f"Task {id} not found")

@api_router.get("/nodes")
async def list_nodes():
    return {"nodes": state_manager.get_active_nodes()}


@api_router.post("/nodes/heartbeat")
async def node_heartbeat(payload: dict):
    node_id = payload.get("node_id")
    node_name = payload.get("name")
    node_ip = payload.get("ip")

    if not node_id or not node_name or not node_ip:
        raise HTTPException(status_code=400, detail="node_id, name, and ip are required")

    state_manager.register_node(
        {
            "id": node_id,
            "name": node_name,
            "ip": node_ip,
            "status": payload.get("status", "HEALTHY"),
            "cpu": payload.get("cpu", 0),
            "ram": payload.get("ram", 0),
            "thermal": payload.get("thermal", 0),
            "gpu_available": payload.get("gpu_available", False),
            "gpu_utilization": payload.get("gpu_utilization", 0),
            "gpu_memory_used_mb": payload.get("gpu_memory_used_mb", 0),
            "gpu_temperature": payload.get("gpu_temperature", 0),
            "active_tasks": payload.get("active_tasks", 0),
        }
    )

    return {"ok": True}

@api_router.get("/cluster/status")
async def cluster_status():
    return build_cluster_snapshot()


@api_router.get("/display/status")
async def display_status():
    """Simple endpoint for dashboards/UI display."""
    return build_cluster_snapshot()

@api_router.post("/control/drain/{node_id}")
async def drain_node(node_id: str):
    state_manager.update_node_status(node_id, "DRAINING")
    return {"ok": True, "node_id": node_id, "status": "DRAINING"}

@api_router.post("/control/migrate")
async def force_migration():
    return {"ok": True, "message": "Manual migration endpoint acknowledged"}

@api_router.post("/control/scheduler/mode")
async def toggle_scheduler_mode():
    return {"ok": True, "message": "Scheduler mode toggle stub"}


@api_router.get("/health")
async def health():
    return {"status": "ok"}

app.include_router(api_router)

# WebSocket router
from master.api import websocket as websocket_router

app.include_router(websocket_router.router)


@app.on_event("startup")
async def startup_event():
    websocket_router.start_background_task(app)
