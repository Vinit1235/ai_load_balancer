---
description: How to build the AI Load Balancer project step by step
---

# AI Load Balancer Build Workflow

This workflow guides smaller AI agents through building the Distributed Task Execution Engine with AI Load Balancer.

## Prerequisites
Read these files first:
1. `claude.md` - Technical architecture and design decisions
2. `SOP.md` - Standard operating procedures and recovery guides
3. `ORCHESTRATION_PLAN.md` - Detailed task breakdown for agents

## Quick Start

// turbo-all

### Step 1: Create Project Structure
```bash
cd c:\D-Drive\Ai_loadbalacer
mkdir -p master\api worker dashboard\components dashboard\utils ai\models shared tests
```

### Step 2: Create __init__.py Files
```bash
touch master/__init__.py master/api/__init__.py worker/__init__.py dashboard/__init__.py dashboard/components/__init__.py dashboard/utils/__init__.py ai/__init__.py ai/models/__init__.py shared/__init__.py tests/__init__.py
```

### Step 3: Install Dependencies
```bash
pip install fastapi uvicorn[standard] ray minio streamlit psutil scikit-learn joblib pandas numpy pydantic python-dotenv websockets httpx pytest
```

## Execution Order

Follow the ORCHESTRATION_PLAN.md waves:

1. **Wave 1**: Core Infrastructure (Tasks 1.1-1.5)
2. **Wave 2**: Worker Components (Tasks 2.1-2.3)
3. **Wave 3**: Master Node Logic (Tasks 3.1-3.4)
4. **Wave 4**: AI Enhancement (Tasks 4.1-4.3)
5. **Wave 5**: Dashboard & Integration (Tasks 5.1-5.5)

## Verification Commands

### Test Infrastructure
```bash
# Test config loading
python -c "from shared.config import settings; print(settings)"

# Test SQLite initialization
python -c "from master.state_manager import init_db; init_db()"
```

### Test Workers
```bash
# Test sentinel
python -c "from worker.sentinel import HealthSentinel; s = HealthSentinel(); print(s.get_cpu_percent())"
```

### Test Master
```bash
# Start API server
uvicorn master.main:app --host 0.0.0.0 --port 8000 --reload
```

### Test Dashboard
```bash
# Start Streamlit
streamlit run dashboard/app.py
```

## Important Files to Create

See ORCHESTRATION_PLAN.md for detailed specifications of each file:

| File | Purpose |
|------|---------|
| shared/config.py | Environment configuration |
| shared/minio_client.py | Checkpoint storage |
| master/state_manager.py | SQLite persistence |
| master/scheduler.py | Task assignment logic |
| master/main.py | FastAPI application |
| worker/sentinel.py | Health monitoring |
| worker/executor.py | Task execution |
| dashboard/app.py | Streamlit UI |

## Recovery Procedures

If something goes wrong, refer to SOP.md:
- SOP 4.1: AI Model Failure
- SOP 4.2: Thermal Throttling
- SOP 4.3: Corrupted Checkpoint
- SOP 4.4: Master Node Crash
