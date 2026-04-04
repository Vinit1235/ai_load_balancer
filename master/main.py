from fastapi import FastAPI, APIRouter, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field
from uuid import uuid4
import logging
import hashlib
import os
import json
from datetime import datetime
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


class LoginRequest(BaseModel):
    email: str
    password: str


class RegisterRequest(BaseModel):
    name: str
    email: str
    password: str


class ContactRequest(BaseModel):
    name: str
    email: str
    subject: str = "General Inquiry"
    message: str


# Simple in-memory user store (for demo; production should use DB)
_users_file = os.path.join(os.path.dirname(__file__), "..", "users.json")

def _load_users():
    if os.path.exists(_users_file):
        with open(_users_file, "r") as f:
            return json.load(f)
    return {}

def _save_users(users):
    with open(_users_file, "w") as f:
        json.dump(users, f, indent=2)

def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


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
async def get_task(id: str):
    tasks = state_manager.get_all_tasks()
    for task in tasks:
        if str(task.get("id")) == str(id):
            return task
    raise HTTPException(status_code=404, detail=f"Task {id} not found")

@api_router.delete("/tasks/{id}")
async def cancel_task(id: str):
    tasks = state_manager.get_all_tasks()
    for task in tasks:
        if str(task.get("id")) == str(id):
            state_manager.update_task_status(str(id), "CANCELLED")
            return {"ok": True, "task_id": id, "status": "CANCELLED"}
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
async def toggle_scheduler_mode(payload: dict = {}):
    mode = payload.get("mode", "heuristic")
    return {"ok": True, "mode": mode, "message": f"Scheduler switched to {mode} mode"}


@api_router.get("/analytics")
async def analytics():
    """Rich analytics payload for the analytics dashboard page."""
    snap = build_cluster_snapshot()
    nodes = snap.get("nodes", [])
    tasks = state_manager.get_all_tasks()

    avg_cpu = round(sum(n.get("cpu", 0) for n in nodes) / len(nodes), 1) if nodes else 0
    avg_ram = round(sum(n.get("ram", 0) for n in nodes) / len(nodes), 1) if nodes else 0

    return {
        **snap,
        "avg_cpu": avg_cpu,
        "avg_ram": avg_ram,
        "node_count": len(nodes),
        "task_count": len(tasks),
        "success_rate": round(
            snap["task_status"]["completed"] / max(len(tasks), 1) * 100, 1
        ),
    }


@api_router.get("/nodes/{node_id}")
async def get_node_detail(node_id: str):
    """Get detailed information about a specific node."""
    node = state_manager.get_node(node_id)
    if not node:
        raise HTTPException(status_code=404, detail=f"Node {node_id} not found")
    return node


@api_router.get("/tasks/stats")
async def task_stats():
    """Quick task status counts."""
    snap = build_cluster_snapshot()
    return snap["task_status"]


@api_router.get("/health")
async def health():
    return {"status": "ok"}


# ===== AUTH ENDPOINTS =====

@api_router.post("/auth/register")
async def register(payload: RegisterRequest):
    users = _load_users()
    if payload.email in users:
        raise HTTPException(status_code=409, detail="Email already registered")
    users[payload.email] = {
        "name": payload.name,
        "email": payload.email,
        "password": _hash_password(payload.password),
        "created_at": datetime.now().isoformat(),
    }
    _save_users(users)
    return {"ok": True, "message": "Registration successful", "user": {"name": payload.name, "email": payload.email}}


@api_router.post("/auth/login")
async def login(payload: LoginRequest):
    users = _load_users()
    user = users.get(payload.email)
    if not user or user["password"] != _hash_password(payload.password):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    # Simple token (for demo; production should use JWT)
    token = hashlib.sha256(f"{payload.email}:{datetime.now().isoformat()}".encode()).hexdigest()
    return {
        "ok": True,
        "token": token,
        "user": {"name": user["name"], "email": user["email"]},
    }


# ===== CONTACT ENDPOINT =====

@api_router.post("/contact")
async def submit_contact(payload: ContactRequest):
    # In production, send email or store in DB
    logging.getLogger("uvicorn").info(
        f"Contact form: {payload.name} <{payload.email}> - {payload.subject}: {payload.message}"
    )
    return {"ok": True, "message": "Your message has been received. We will get back to you soon."}


app.include_router(api_router)

# WebSocket router
from master.api import websocket as websocket_router

app.include_router(websocket_router.router)

# Serve frontend static files
_frontend_dir = os.path.join(os.path.dirname(__file__), "..", "getconnect (3)", "getconnect")
if os.path.isdir(_frontend_dir):
    app.mount("/app", StaticFiles(directory=_frontend_dir, html=True), name="frontend")


@app.on_event("startup")
async def startup_event():
    websocket_router.start_background_task(app)
