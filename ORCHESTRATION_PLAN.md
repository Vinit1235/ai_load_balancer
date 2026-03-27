# 🎯 Orchestration & Execution Plan
## AI Load Balancer - Distributed Task Execution Engine

---

## 📋 Overview

This document serves as the **directive orchestration plan** for coordinating smaller AI agents/models to build the Distributed Task Execution Engine with AI Load Balancer. Each task is atomic, clearly defined, and includes success criteria.

### 🔧 Self-Correction System (NEW)

All agents in this system have **built-in self-correction capabilities**:

| Component | Location | Purpose |
|-----------|----------|---------|
| `SelfCorrectionEngine` | `shared/self_correction.py` | Error parsing, retry logic, auto-fixes |
| `CodeValidator` | `ai/code_validator.py` | Multi-level code validation and repair |
| `AgentInstructionWrapper` | `ai/agent_wrapper.py` | Task management with correction context |

**Key Features:**
- ✅ **Error Detection & Categorization** - Automatically identifies syntax, import, runtime, type, network, and resource errors
- ✅ **Retry with Exponential Backoff** - Smart retry delays based on error type
- ✅ **Automatic Code Repair** - Fixes common syntax errors, missing imports, type issues
- ✅ **Validation Before Execution** - Catches errors before they happen
- ✅ **Feedback Loops** - Provides guidance for agents to fix complex issues
- ✅ **LLM-Powered Fixes** - Uses AI to repair code when automatic fixes fail

---


## 🏗️ Agent Task Breakdown

### Legend
- 🔵 **Priority**: High | Medium | Low
- ⏱️ **Estimated Time**: Time to complete
- 🔗 **Dependencies**: Tasks that must be completed first
- ✅ **Success Criteria**: How to verify task completion

---

## WAVE 1: Core Infrastructure Setup

### Task 1.1: Project Scaffolding
```yaml
Agent: File Structure Agent
Priority: 🔵 HIGH
Time: 15 minutes
Dependencies: None

Instructions:
  Create the following directory structure:
  - Ai_loadbalacer/master/
  - Ai_loadbalacer/master/api/
  - Ai_loadbalacer/worker/
  - Ai_loadbalacer/dashboard/
  - Ai_loadbalacer/dashboard/components/
  - Ai_loadbalacer/dashboard/utils/
  - Ai_loadbalacer/ai/
  - Ai_loadbalacer/ai/models/
  - Ai_loadbalacer/shared/
  - Ai_loadbalacer/tests/

  Create empty __init__.py in each Python package directory.

Success Criteria:
  - All directories exist
  - __init__.py files present in Python packages
```

### Task 1.2: Requirements File
```yaml
Agent: Dependency Agent
Priority: 🔵 HIGH
Time: 10 minutes
Dependencies: Task 1.1

Instructions:
  Create requirements.txt with:
  - fastapi>=0.109.0
  - uvicorn[standard]>=0.27.0
  - ray>=2.30.0
  - minio>=7.2.0
  - streamlit>=1.38.0
  - psutil>=5.9.0
  - scikit-learn>=1.4.0
  - joblib>=1.3.0
  - pandas>=2.2.0
  - numpy>=1.26.0
  - pydantic>=2.6.0
  - python-dotenv>=1.0.0
  - websockets>=12.0
  - httpx>=0.27.0
  - pytest>=8.0.0

Success Criteria:
  - requirements.txt exists
  - pip install -r requirements.txt succeeds without errors
```

### Task 1.3: Environment Configuration
```yaml
Agent: Config Agent
Priority: 🔵 HIGH
Time: 10 minutes
Dependencies: Task 1.1

Instructions:
  Create .env file with:
  - MASTER_HOST=192.168.1.100
  - MASTER_PORT=8000
  - RAY_HEAD_PORT=6379
  - MINIO_ENDPOINT=192.168.1.100:9000
  - MINIO_ACCESS_KEY=minioadmin
  - MINIO_SECRET_KEY=minioadmin
  - MINIO_BUCKET=checkpoints
  - DATABASE_PATH=cluster_state.db
  - DASHBOARD_PASSWORD=capstone2026
  - FORCE_HEURISTIC=0
  - AI_MIN_SAMPLES=50
  - CHECKPOINT_INTERVAL=30
  - OVERLOAD_CPU_THRESHOLD=85
  - OVERLOAD_THERMAL_THRESHOLD=80

  Create shared/config.py to load these variables using pydantic-settings.

Success Criteria:
  - .env file exists with all variables
  - config.py can load and validate all settings
  - Running `python -c "from shared.config import settings; print(settings)"` works
```

### Task 1.4: SQLite State Manager
```yaml
Agent: Database Agent
Priority: 🔵 HIGH
Time: 30 minutes
Dependencies: Task 1.3

Instructions:
  Create master/state_manager.py with:
  
  Tables:
    - nodes (id, name, ip, status, last_heartbeat, cpu, ram, thermal)
    - tasks (id, type, status, assigned_node, progress, created_at, started_at, completed_at)
    - metrics (id, task_id, predicted_duration, actual_duration, was_migrated)
  
  Functions:
    - init_db(): Create tables if not exist
    - register_node(node_data): Add/update node
    - get_active_nodes(): Return healthy nodes
    - update_node_metrics(node_id, metrics): Update CPU/RAM/thermal
    - create_task(task_data): Insert new task
    - update_task_status(task_id, status, progress): Update task state
    - get_pending_tasks(): Return tasks waiting for assignment
    - get_node_tasks(node_id): Return tasks on specific node
    - log_task_metrics(metrics): Record completion data for ML training

Success Criteria:
  - All tables created successfully
  - CRUD operations work correctly
  - State persists across restarts
  - Test: Create node, create task, query both succeed
```

### Task 1.5: MinIO Client Wrapper
```yaml
Agent: Storage Agent
Priority: 🔵 HIGH
Time: 25 minutes
Dependencies: Task 1.3

Instructions:
  Create shared/minio_client.py with:
  
  Functions:
    - init_minio(): Connect to MinIO, create bucket if needed
    - save_checkpoint(task_id, state_bytes): Upload checkpoint
    - get_checkpoint(task_id): Download checkpoint or None
    - delete_checkpoint(task_id): Remove checkpoint after completion
    - list_checkpoints(): Return all checkpoint objects
    - validate_checkpoint(task_id): CRC32 validation
    - get_checkpoint_size(task_id): Return size in bytes

  Error Handling:
    - Return None (not raise) if checkpoint doesn't exist
    - Log all errors but don't crash
    - Implement retry logic (3 attempts with 1s delay)

Success Criteria:
  - Can connect to MinIO
  - Can save/retrieve/delete checkpoints
  - Handles missing checkpoints gracefully
  - CRC32 validation catches corruption
```

---

## WAVE 2: Worker Components

### Task 2.1: Health Sentinel
```yaml
Agent: Monitoring Agent
Priority: 🔵 HIGH
Time: 30 minutes
Dependencies: Task 1.4, Task 1.5

Instructions:
  Create worker/sentinel.py with:
  
  Class HealthSentinel:
    - __init__(master_url, node_id): Initialize with config
    - get_cpu_percent(): Return CPU usage (0-100)
    - get_ram_percent(): Return RAM usage (0-100)
    - get_thermal(): Return temperature in °C (Windows: use wmi, Linux: read thermal_zone)
    - is_overloaded(): Return True if CPU > 85% AND thermal > 80°C for 3+ seconds
    - send_heartbeat(): POST metrics to master every 1 second
    - request_drain(): Call master's emergency drain endpoint
    - run(): Main async loop for monitoring

  Platform Handling:
    - Windows: Use psutil + wmi for thermal
    - Linux: Read /sys/class/thermal/thermal_zone0/temp
    - Default thermal to 0 if unavailable

Success Criteria:
  - Accurately reports CPU/RAM
  - Thermal reading works on current platform
  - Overload detection triggers after sustained high load
  - Heartbeats sent every second
```

### Task 2.2: Task Executor with Checkpointing
```yaml
Agent: Execution Agent
Priority: 🔵 HIGH
Time: 45 minutes
Dependencies: Task 1.5, Task 2.1

Instructions:
  Create worker/executor.py with:
  
  Supported Task Types:
    - matrix_multiply: CPU-intensive matrix operations
    - compress_data: I/O simulation
    - synthetic_load: stress-ng wrapper
  
  Class TaskExecutor:
    - __init__(minio_client): Initialize with storage
    - execute(task_id, task_type, input_data): Main execution
    - _load_checkpoint(task_id): Resume from MinIO if exists
    - _save_checkpoint(task_id, state): Persist to MinIO
    - _process_chunk(state): Do work, return updated state
    - _report_progress(task_id, progress): POST to master
  
  Checkpointing Logic:
    - Check for existing checkpoint on start
    - Save checkpoint every 30 seconds during execution
    - Delete checkpoint on successful completion
    - Progress reports every 5 seconds

  Ray Integration:
    - Decorate execute() with @ray.remote
    - Support cancellation via Ray's cancel()

Success Criteria:
  - Tasks can be interrupted and resumed
  - Checkpoints saved/loaded correctly
  - Progress reported to master
  - All task types execute successfully
```

### Task 2.3: Synthetic Stress Generator
```yaml
Agent: Load Generator Agent
Priority: 🔵 MEDIUM
Time: 20 minutes
Dependencies: Task 2.2

Instructions:
  Create worker/stress_test.py with:
  
  Functions:
    - generate_cpu_load(cores, duration_sec): Run stress-ng
    - generate_memory_pressure(mb, duration_sec): Allocate memory
    - generate_io_load(mb_per_sec, duration_sec): Disk I/O
    - generate_mixed_load(profile): Combined workload
  
  Profiles:
    - "light": 2 cores, 30% memory, 30 seconds
    - "medium": 4 cores, 50% memory, 60 seconds
    - "heavy": all cores, 70% memory, 90 seconds
  
  Fallback:
    - If stress-ng not available, use pure Python CPU burn

Success Criteria:
  - Can generate predictable CPU load
  - Load visible in sentinel metrics
  - Configurable intensity and duration
```

---

## WAVE 3: Master Node Logic

### Task 3.1: FastAPI Skeleton
```yaml
Agent: API Agent
Priority: 🔵 HIGH
Time: 30 minutes
Dependencies: Task 1.4

Instructions:
  Create master/main.py with:
  
  Routers:
    - /api/v1/tasks - Task CRUD
    - /api/v1/nodes - Node management
    - /api/v1/cluster - Cluster status
    - /api/v1/control - Admin controls
    - /ws/metrics - WebSocket streaming
  
  Endpoints:
    - POST /api/v1/tasks - Submit new task
    - GET /api/v1/tasks - List all tasks
    - GET /api/v1/tasks/{id} - Get task details
    - DELETE /api/v1/tasks/{id} - Cancel task
    - GET /api/v1/nodes - List nodes
    - GET /api/v1/cluster/status - Full status
    - POST /api/v1/control/drain/{node_id} - Drain node
    - POST /api/v1/control/migrate - Force migration
    - POST /api/v1/control/scheduler/mode - Toggle AI/Heuristic

  Middleware:
    - CORS (allow all for development)
    - Request logging
    - Error handling

Success Criteria:
  - Server starts on configured port
  - All endpoints return correct status codes
  - OpenAPI docs available at /docs
```

### Task 3.2: Heuristic Scheduler
```yaml
Agent: Scheduler Agent
Priority: 🔵 HIGH
Time: 35 minutes
Dependencies: Task 3.1, Task 1.4

Instructions:
  Create master/scheduler.py with:
  
  Class Scheduler:
    - __init__(state_manager): Load state
    - mode: "HEURISTIC" | "AI"
    - select_node(task): Choose best node for task
    - _heuristic_select(task): Weighted scoring
    - drain_node(node_id): Stop assigning, migrate tasks
    - migrate_task(task_id, target_node): Move task
    - rebalance(): Spread load evenly
  
  Heuristic Formula:
    score = (cpu_percent + ram_percent) * (1 + active_task_count * 0.2)
    Select node with LOWEST score
  
  Drain Logic:
    1. Set node status to "DRAINING"
    2. No new tasks assigned
    3. Existing tasks migrate when they hit checkpoint
    4. After all tasks gone, set status to "DRAINED"

Success Criteria:
  - Tasks assigned to least loaded node
  - Drain prevents new assignments
  - Migration triggers correctly
  - Rebalance distributes evenly
```

### Task 3.3: WebSocket Metrics Streaming
```yaml
Agent: Realtime Agent
Priority: 🔵 MEDIUM
Time: 25 minutes
Dependencies: Task 3.1

Instructions:
  Create master/api/websocket.py with:
  
  Endpoints:
    - /ws/metrics - Broadcast cluster metrics every 500ms
    - /ws/tasks/{id} - Stream specific task progress
  
  Message Format (JSON):
    {
      "type": "cluster_update" | "task_update",
      "timestamp": "ISO8601",
      "data": { ... }
    }
  
  Features:
    - Client connection management
    - Graceful disconnect handling
    - Backpressure (skip if client slow)

Success Criteria:
  - Clients receive updates every 500ms
  - Multiple clients supported
  - No memory leaks on disconnect
```

### Task 3.4: Task Distribution with Ray
```yaml
Agent: Distribution Agent
Priority: 🔵 HIGH
Time: 40 minutes
Dependencies: Task 3.2, Task 2.2

Instructions:
  Create master/task_distributor.py with:
  
  Functions:
    - init_ray(): Connect to Ray cluster
    - submit_task(task_data): Send to selected worker
    - cancel_task(task_id): Stop running task
    - get_task_status(task_id): Query Ray for status
    - migrate_task(task_id, new_node): Checkpoint + restart
  
  Ray Actor:
    - Create actor per worker node
    - Route tasks to correct actor
    - Handle actor failures

  Migration Flow:
    1. Signal current executor to checkpoint
    2. Wait for checkpoint confirmation
    3. Cancel current execution
    4. Submit to new node with checkpoint flag
    5. Update state manager

Success Criteria:
  - Tasks execute on Ray workers
  - Can query task status
  - Migration completes without data loss
  - Handles worker failures gracefully
```

---

## WAVE 4: AI Enhancement

### Task 4.1: Synthetic Training Data Generator
```yaml
Agent: Data Generation Agent
Priority: 🔵 MEDIUM
Time: 25 minutes
Dependencies: Task 2.2

Instructions:
  Create ai/synthetic_generator.py with:
  
  Function generate_training_data(count, output_file):
    Generate CSV with columns:
    - task_type: matrix_multiply | compress_data | synthetic_load
    - input_size: 10 - 1000 (random)
    - cpu_at_submit: 0 - 100 (random)
    - ram_at_submit: 0 - 100 (random)
    - active_tasks: 0 - 20 (random)
    - actual_duration: calculated based on type + size + noise
  
  Duration Formula:
    - matrix_multiply: (input_size * 0.1) + (cpu_at_submit * 0.05) + noise
    - compress_data: (input_size * 0.05) + (ram_at_submit * 0.03) + noise
    - synthetic_load: input_size * 0.2 + noise
    - noise: random ±15%

Success Criteria:
  - Generates realistic training data
  - CSV parseable by pandas
  - Duration correlates with inputs
```

### Task 4.2: Random Forest Model Training
```yaml
Agent: ML Training Agent
Priority: 🔵 MEDIUM
Time: 35 minutes
Dependencies: Task 4.1

Instructions:
  Create ai/train_model.py with:
  
  Training Pipeline:
    1. Load training CSV
    2. Feature engineering:
       - One-hot encode task_type
       - Scale numeric features
    3. Split 80/20 train/test
    4. Train RandomForestRegressor (100 trees)
    5. Evaluate RMSE on test set
    6. Save model if RMSE < 2.0
  
  Model Metadata:
    - Store RMSE as model attribute
    - Store feature names
    - Store training timestamp
  
  CLI:
    python train_model.py --input data.csv --output models/random_forest.pkl --min-rmse 2.0

Success Criteria:
  - Model trains without errors
  - RMSE calculated correctly
  - Model saves only if quality threshold met
  - Can load and predict with saved model
```

### Task 4.3: AI Scheduler Integration
```yaml
Agent: AI Integration Agent
Priority: 🔵 MEDIUM
Time: 30 minutes
Dependencies: Task 3.2, Task 4.2

Instructions:
  Update master/scheduler.py:
  
  Add Methods:
    - _load_ai_model(): Load pickle, validate RMSE
    - _ai_select(task): Predict duration per node, pick fastest
    - _should_fallback(): Check prediction accuracy history
    - switch_mode(new_mode): Toggle between AI/HEURISTIC
  
  AI Selection Logic:
    For each healthy node:
      1. Create feature vector (task_type, size, node stats)
      2. Predict duration
      3. Add penalty for active tasks
    Select node with lowest predicted duration
  
  Fallback Trigger:
    - Track last 10 predictions vs actual
    - If MAPE > 30% for 3 consecutive tasks, switch to HEURISTIC
    - Log warning when fallback triggered

Success Criteria:
  - AI mode activates when model available
  - Predictions influence node selection
  - Fallback triggers on poor predictions
  - Mode can be toggled via API
```

---

## WAVE 5: Dashboard & Integration

### Task 5.1: Streamlit Main App
```yaml
Agent: Dashboard Agent
Priority: 🔵 HIGH
Time: 45 minutes
Dependencies: Task 3.1, Task 3.3

Instructions:
  Create dashboard/app.py with:
  
  Layout:
    - Header with cluster name and status
    - 3-column grid for node cards
    - Task table with live updates
    - Scheduler control panel
    - Metrics charts
  
  Features:
    - Password authentication
    - Auto-refresh every 500ms
    - Session state for user context
  
  Styling:
    - Dark theme
    - Status color coding (green/yellow/red)
    - Pulsing animation for migrating tasks

Success Criteria:
  - Loads without errors
  - Shows real-time data
  - Authentication works
  - Responsive on different screens
```

### Task 5.2: Node Status Cards Component
```yaml
Agent: Component Agent
Priority: 🔵 MEDIUM
Time: 20 minutes
Dependencies: Task 5.1

Instructions:
  Create dashboard/components/node_card.py with:
  
  Function render_node_card(node_data):
    Display:
    - Status emoji (🟢 healthy, 🟠 draining, 🔴 offline)
    - Node name and IP
    - CPU gauge/progress bar
    - RAM gauge/progress bar
    - Temperature (if available)
    - Active task count
    - "Drain Node" button with confirmation

Success Criteria:
  - Card displays all node info
  - Gauges update in real-time
  - Drain button triggers API call
```

### Task 5.3: Live Task Table Component
```yaml
Agent: Table Agent
Priority: 🔵 MEDIUM
Time: 25 minutes
Dependencies: Task 5.1

Instructions:
  Create dashboard/components/task_table.py with:
  
  Function render_task_table(tasks):
    Columns:
    - Task ID (truncated)
    - Type
    - Status (with color)
    - Progress bar
    - Assigned Node
    - Duration
    - Actions (Cancel, Force Migrate)
  
  Features:
    - Yellow highlight for migrated tasks
    - Sorting by status/duration
    - Pagination for large task lists

Success Criteria:
  - Table shows all tasks
  - Migrated tasks highlighted
  - Actions trigger API calls
```

### Task 5.4: Scheduler Control Panel
```yaml
Agent: Control Panel Agent
Priority: 🔵 MEDIUM
Time: 25 minutes
Dependencies: Task 5.1, Task 4.3

Instructions:
  Create dashboard/components/scheduler_panel.py with:
  
  Controls:
    - Mode toggle (AI/Heuristic) with current mode display
    - Force migrate dropdown (select task + target node)
    - Synthetic load button (light/medium/heavy)
    - Emergency flush button (cancel all pending)
  
  Safety:
    - Password confirmation for dangerous actions
    - Impact preview before migration
    - Cooldown after actions (prevent spam)

Success Criteria:
  - Mode toggle works
  - Migration completes successfully
  - Synthetic load triggers on workers
  - Safety confirmations enforce
```

### Task 5.5: Authentication Helper
```yaml
Agent: Auth Agent
Priority: 🔵 MEDIUM
Time: 15 minutes
Dependencies: Task 5.1

Instructions:
  Create dashboard/utils/auth.py with:
  
  Functions:
    - check_password(): Return True if session authenticated
    - show_login(): Display login form
    - require_password(action_name): Show confirmation dialog
    - logout(): Clear session state
  
  Security:
    - Hash password comparison (don't compare plaintext)
    - Session timeout after 30 minutes
    - Rate limit login attempts (3 per minute)

Success Criteria:
  - Login required to access dashboard
  - Wrong password rejected
  - Session persists across navigation
```

---

## 🔄 Execution Flow

```mermaid
graph LR
    W1[Wave 1: Infrastructure] --> W2[Wave 2: Workers]
    W1 --> W3[Wave 3: Master]
    W2 --> W3
    W3 --> W4[Wave 4: AI]
    W3 --> W5[Wave 5: Dashboard]
    W4 --> W5
```

---

## 📋 Agent Assignment Summary

| Wave | Tasks | Primary Agent Type | Total Time |
|------|-------|-------------------|------------|
| 1 | 1.1-1.5 | Infrastructure | ~1.5 hours |
| 2 | 2.1-2.3 | Worker Systems | ~1.5 hours |
| 3 | 3.1-3.4 | Master Logic | ~2 hours |
| 4 | 4.1-4.3 | AI/ML | ~1.5 hours |
| 5 | 5.1-5.5 | Frontend/UI | ~2 hours |

**Total Estimated Time: ~8.5 hours**

---

## ✅ Verification Checklist

After all tasks complete, verify:

### Infrastructure
- [ ] All directories and files created
- [ ] Requirements install successfully
- [ ] Environment loads correctly
- [ ] SQLite database initializes
- [ ] MinIO connection works

### Workers
- [ ] Health metrics collecting
- [ ] Tasks execute and checkpoint
- [ ] Stress generator works

### Master
- [ ] API endpoints respond
- [ ] Scheduler assigns tasks
- [ ] WebSocket streams data
- [ ] Ray distribution works

### AI
- [ ] Training data generates
- [ ] Model trains and saves
- [ ] AI mode activates

### Dashboard
- [ ] UI renders completely
- [ ] Real-time updates work
- [ ] Controls function correctly

---

## 🚨 Emergency Contacts

If agents encounter blockers:
1. Check SOP.md for recovery procedures
2. Reference claude.md for architecture decisions
3. Fallback to HEURISTIC mode if AI fails
4. Use Emergency Flush if tasks stuck

---

*This orchestration plan is designed to be executed by AI coding agents. Each task is self-contained with clear inputs, outputs, and verification criteria.*
