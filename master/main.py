from fastapi import FastAPI, APIRouter, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
import logging

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

@api_router.post("/tasks")
async def submit_task():
    return {"message": "Submit new task"}

@api_router.get("/tasks")
async def list_tasks():
    return {"message": "List all tasks"}

@api_router.get("/tasks/{id}")
async def get_task(id: int):
    return {"message": f"Get task {id}"}

@api_router.delete("/tasks/{id}")
async def cancel_task(id: int):
    return {"message": f"Cancel task {id}"}

@api_router.get("/nodes")
async def list_nodes():
    return {"message": "List nodes"}

@api_router.get("/cluster/status")
async def cluster_status():
    return {"message": "Full cluster status"}

@api_router.post("/control/drain/{node_id}")
async def drain_node(node_id: int):
    return {"message": f"Drain node {node_id}"}

@api_router.post("/control/migrate")
async def force_migration():
    return {"message": "Force migration"}

@api_router.post("/control/scheduler/mode")
async def toggle_scheduler_mode():
    return {"message": "Toggle AI/Heuristic mode"}

app.include_router(api_router)

# WebSocket router
from master.api import websocket as websocket_router

app.include_router(websocket_router.router)
