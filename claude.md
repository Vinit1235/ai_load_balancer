# Distributed Task Execution Engine with AI Load Balancer
## Technical Implementation Roadmap (Expert Edition)

---

## 1. Critical Design Principles

> **Non-negotiables for success:**
> - **Idempotent Tasks**: Every task must resume from checkpoints (MinIO) after migration
> - **Progressive Complexity**: Start with heuristic scheduler → add AI later
> - **Zero Single Points of Failure**: Master must survive restarts (state persisted to disk)
> - **Demo-First Architecture**: All components must work with synthetic loads (no Blender dependency)

---

## 2. System Architecture (Optimized)

### A. Master Node (Simplified & Robust)

| Component | Technology | Critical Change |
|-----------|-----------|-----------------|
| **API Gateway** | FastAPI | **Single endpoint for ALL operations** (tasks, control, metrics) |
| **Scheduler Core** | Python + Ray | **Dual-mode**: `HEURISTIC` (default) / `AI` (fallback) |
| **State Manager** | SQLite + Disk | **REMOVED Redis** - State persisted to `cluster_state.db` |
| **AI Predictor** | Scikit-learn | Only activates after 50+ training samples |

### B. Worker Nodes (Reliable Sentinel)

| Component | Critical Enhancement |
|-----------|---------------------|
| **Health Sentinel** | Uses `psutil` + **thermal throttling detection** + **GPU monitoring** |
| **Task Executor** | **Writes checkpoints to MinIO every 30s** |
| **Overload Trigger** | Synthetic stress script (`stress-ng`) instead of user apps |
| **GPU Detector** | Uses `pynvml` for NVIDIA GPU detection and utilization |

#### 🖥️ Worker Node Execution

**File to run on each worker node:**
```bash
# On each worker machine (192.168.1.101, 192.168.1.102, etc.)
python worker/sentinel.py --master-url http://192.168.1.100:8000 --node-name worker-1
```

This script:
1. Connects to the master node via HTTP
2. Sends heartbeats with CPU/RAM/GPU/Thermal stats every 1 second
3. Detects overload conditions and requests drain
4. Listens for task assignments via Ray

#### 🎮 GPU Detection & Support

```python
# worker/gpu_detector.py
import subprocess
from dataclasses import dataclass

@dataclass
class GPUInfo:
    available: bool
    name: str = None
    memory_total_mb: int = 0
    memory_used_mb: int = 0
    utilization_percent: int = 0
    temperature: int = 0

def detect_gpu() -> GPUInfo:
    """Detect NVIDIA GPU using pynvml or nvidia-smi fallback"""
    try:
        import pynvml
        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        
        name = pynvml.nvmlDeviceGetName(handle)
        memory = pynvml.nvmlDeviceGetMemoryInfo(handle)
        util = pynvml.nvmlDeviceGetUtilizationRates(handle)
        temp = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
        
        return GPUInfo(
            available=True,
            name=name.decode() if isinstance(name, bytes) else name,
            memory_total_mb=memory.total // (1024**2),
            memory_used_mb=memory.used // (1024**2),
            utilization_percent=util.gpu,
            temperature=temp
        )
    except Exception:
        return GPUInfo(available=False)
```

**GPU-Aware Task Types:**
- `ml_training` - Requires GPU, assigned only to GPU nodes
- `inference` - Prefers GPU, falls back to CPU
- `matrix_multiply` - Uses GPU if available (CuPy)
- `compress_data` - CPU only

### C. Web Control Plane

| Component | Purpose |
|-----------|---------|
| **Streamlit UI** | Real-time monitoring + **manual override controls** |
| **Metrics Server** | Exposes `/metrics` endpoint for Prometheus |

---

## 3. Tech Stack & Dependencies (Streamlined)

| Component | Technology | Version | Why This? |
|-----------|-----------|---------|-----------|
| **Core** | Python | 3.10+ | Async support for real-time monitoring |
| **Orchestration** | Ray | 2.30.0 | **Only for task distribution** (no state mgmt) |
| **Storage** | MinIO | RELEASE.2024-01-01 | S3-compatible checkpoint storage |
| **Web UI** | Streamlit | 1.38.0 | **Zero-JS dashboard** with live controls |
| **Metrics** | SQLite | 3.45.0 | **REPLACED Redis** - simpler persistence |
| **Stress Test** | stress-ng | 0.15.00 | **REPLACED Blender** - predictable CPU load |

> **Critical Removals**:
> - ❌ Standalone Redis (state managed by SQLite + disk)
> - ❌ Direct Ray state queries (all data via FastAPI)

---

## 4. Implementation Phases (Battle-Tested)

### Phase 1: Task Checkpointing (Foundation for Migration)

```python
# task_executor.py (Worker)
def execute_task(task_id, task_type, input_data):
    # 1. Check for existing checkpoint in MinIO
    checkpoint = minio_client.get_object("checkpoints", f"{task_id}.ckpt")
    
    # 2. Resume from checkpoint if exists
    if checkpoint.exists():
        state = pickle.loads(checkpoint.read())
    else:
        state = {"progress": 0, "data": input_data}
    
    # 3. Process in chunks with checkpointing
    while state["progress"] < 100:
        state = process_chunk(state)  # Your logic here
        if time.time() - last_checkpoint > 30:  # Every 30s
            minio_client.put_object(
                "checkpoints", 
                f"{task_id}.ckpt", 
                data=pickle.dumps(state),
                length=len(pickle.dumps(state))
            )
        yield state  # For real-time progress reporting
```

### Phase 2: Overload Detection with Thermal Awareness

```python
# worker_sentinel.py
THRESHOLDS = {
    "cpu": 85,       # %
    "thermal": 80,   # °C (critical for laptops)
    "duration": 3    # seconds
}

async def detect_overload():
    thermal_zone = "/sys/class/thermal/thermal_zone0/temp"  # Linux only
    while True:
        cpu = psutil.cpu_percent(0.5)
        thermal = int(open(thermal_zone).read()) / 1000 if Path(thermal_zone).exists() else 0
        
        if cpu > THRESHOLDS["cpu"] and thermal > THRESHOLDS["thermal"]:
            if not overload_timer:
                overload_timer = time.time()
            elif time.time() - overload_timer > THRESHOLDS["duration"]:
                requests.post(f"{MASTER_URL}/emergency/drain", 
                             json={"node_id": MY_NODE_ID})
        else:
            overload_timer = None
```

### Phase 3: Dual-Mode Scheduler

```python
# scheduler.py
class Scheduler:
    def __init__(self):
        self.mode = "HEURISTIC"  # Default safe mode
        try:
            self.ai_model = joblib.load("random_forest.pkl")
            if self.ai_model.rmse > 2.0:  # Validation metric
                raise ValueError("Poor model quality")
            self.mode = "AI"
        except Exception as e:
            logging.warning(f"AI disabled: {str(e)}")
    
    def select_node(self, task):
        if self.mode == "AI":
            return self._ai_select(task)
        return self._heuristic_select(task)  # Least loaded node
    
    def _heuristic_select(self, task):
        # Simple but reliable: (CPU% + RAM%) * active_tasks
        scores = {node: (h["cpu"] + h["ram"]) * h["tasks"] 
                 for node, h in healthy_nodes.items()}
        return min(scores, key=scores.get)
```

---

## 🤖 AI Model: Random Forest Regressor

### Why Random Forest?

| Feature | Benefit |
|---------|---------|
| **Ensemble Method** | Combines 100 decision trees for robust predictions |
| **Handles Non-linearity** | Captures complex relationships (CPU × task_size) |
| **No Feature Scaling Required** | Works with raw metrics directly |
| **Feature Importance** | Shows which factors affect task duration most |
| **Fast Inference** | ~1ms prediction time, suitable for real-time scheduling |
| **Resistant to Overfitting** | Bagging reduces variance |

### How It Works

```
Input Features:                    Output:
┌─────────────────────┐           ┌──────────────────┐
│ task_type (one-hot) │           │                  │
│ input_size          │    ──►    │ predicted_       │
│ cpu_at_submit       │  Random   │ duration (secs)  │
│ ram_at_submit       │  Forest   │                  │
│ gpu_available       │           │                  │
│ active_task_count   │           └──────────────────┘
└─────────────────────┘
```

### Training Pipeline

```python
# ai/train_model.py
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_squared_error
import pandas as pd
import joblib
import numpy as np

def train_model(input_csv: str, output_path: str, min_rmse: float = 2.0):
    # Load training data
    df = pd.read_csv(input_csv)
    
    # Feature engineering
    X = pd.get_dummies(df[['task_type', 'input_size', 'cpu_at_submit', 
                           'ram_at_submit', 'gpu_available', 'active_tasks']])
    y = df['actual_duration']
    
    # Split data
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2)
    
    # Train Random Forest
    model = RandomForestRegressor(
        n_estimators=100,      # 100 trees
        max_depth=10,          # Prevent overfitting
        min_samples_leaf=5,    # Minimum samples per leaf
        n_jobs=-1,             # Use all CPU cores
        random_state=42
    )
    model.fit(X_train, y_train)
    
    # Evaluate
    predictions = model.predict(X_test)
    rmse = np.sqrt(mean_squared_error(y_test, predictions))
    
    if rmse > min_rmse:
        raise ValueError(f"Model RMSE {rmse:.2f} exceeds threshold {min_rmse}")
    
    # Save with metadata
    model.rmse = rmse
    model.feature_names = X.columns.tolist()
    model.trained_at = datetime.now().isoformat()
    joblib.dump(model, output_path)
    
    return model, rmse
```

### GPU-Aware AI Selection

```python
# In scheduler.py
def _ai_select(self, task):
    """Select best node using AI predictions with GPU awareness"""
    predictions = {}
    
    for node_id, node_info in self.healthy_nodes.items():
        # Check GPU requirement
        if task.requires_gpu and not node_info['gpu_available']:
            continue  # Skip non-GPU nodes for GPU tasks
        
        # Build feature vector
        features = {
            f"task_type_{task.type}": 1,
            "input_size": task.input_size,
            "cpu_at_submit": node_info['cpu'],
            "ram_at_submit": node_info['ram'],
            "gpu_available": 1 if node_info['gpu_available'] else 0,
            "active_tasks": node_info['task_count']
        }
        
        # Predict duration on this node
        feature_vector = [features.get(f, 0) for f in self.ai_model.feature_names]
        predicted_duration = self.ai_model.predict([feature_vector])[0]
        
        # Add GPU bonus (prefer GPU for ML tasks)
        if task.prefers_gpu and node_info['gpu_available']:
            predicted_duration *= 0.3  # GPU is ~3x faster
        
        predictions[node_id] = predicted_duration
    
    if not predictions:
        raise NoSuitableNodeError(f"No node available for task {task.id}")
    
    # Return node with shortest predicted duration
    return min(predictions, key=predictions.get)
```

### Model Performance Monitoring

```python
# Track prediction accuracy in real-time
class PredictionTracker:
    def __init__(self, window_size=10, mape_threshold=0.30):
        self.history = deque(maxlen=window_size)
        self.threshold = mape_threshold
    
    def record(self, predicted: float, actual: float):
        error = abs(predicted - actual) / actual if actual > 0 else 0
        self.history.append(error)
    
    def should_fallback(self) -> bool:
        """Trigger heuristic fallback if MAPE > 30% for 3+ consecutive"""
        if len(self.history) < 3:
            return False
        return all(e > self.threshold for e in list(self.history)[-3:])
```

---

## 5. Algorithm Analysis Metrics (Academic Rigor)

| Metric | Formula | Target Improvement |
|--------|---------|-------------------|
| **Makespan** | `max(completion_time) - min(submission_time)` | AI ≤ 0.85 × RR |
| **Migration Overhead** | `(restart_time - original_start_time) / original_duration` | ≤ 15% |
| **Load Imbalance** | `std([node_cpu for all nodes])` | AI ≤ 0.6 × RR |
| **Prediction Error** | `abs(actual - predicted)` | RMSE < 2.0s |

### Data Collection Schema

```sql
-- Every task logs to SQLite
CREATE TABLE task_metrics (
    task_id TEXT PRIMARY KEY,
    task_type TEXT NOT NULL,
    input_size INTEGER,
    assigned_node TEXT,
    start_time TIMESTAMP,
    end_time TIMESTAMP,
    actual_duration REAL,
    predicted_duration REAL,
    was_migrated BOOLEAN DEFAULT FALSE,
    checkpoint_count INTEGER DEFAULT 0
);
```

---

## 6. Failure Modes & Mitigations (Expert Insight)

| Failure Scenario | Mitigation Strategy | SOP Reference |
|-----------------|---------------------|---------------|
| Laptop thermal shutdown | Throttling detection + automatic draining | SOP 4.2 |
| MinIO checkpoint corruption | CRC32 validation on resume | SOP 4.3 |
| AI model divergence | Fallback to heuristic after 3 bad predictions | SOP 4.1 |
| Network partition | Master election via SQLite lease file | SOP 4.4 |

---

## 7. Project File Structure

```
Ai_loadbalacer/
├── master/
│   ├── main.py              # FastAPI entry point
│   ├── scheduler.py         # Dual-mode scheduler
│   ├── state_manager.py     # SQLite state persistence
│   └── api/
│       ├── routes.py        # REST endpoints
│       └── websocket.py     # Live metrics streaming
├── worker/
│   ├── sentinel.py          # Health monitoring
│   ├── executor.py          # Task execution with checkpointing
│   └── stress_test.py       # Synthetic load generator
├── dashboard/
│   ├── app.py               # Streamlit main app
│   ├── components/
│   │   ├── node_card.py     # Node status cards
│   │   ├── task_table.py    # Live task table
│   │   └── scheduler_panel.py # Control panel
│   └── utils/
│       └── auth.py          # Authentication helpers
├── ai/
│   ├── train_model.py       # ML training pipeline
│   ├── synthetic_generator.py # Training data generator
│   └── models/
│       └── random_forest.pkl # Trained model
├── shared/
│   ├── config.py            # Environment configuration
│   ├── minio_client.py      # MinIO integration
│   └── models.py            # Pydantic data models
├── tests/
│   ├── test_scheduler.py
│   ├── test_executor.py
│   └── test_migration.py
├── .env                     # Environment variables
├── requirements.txt         # Python dependencies
├── docker-compose.yml       # Local development setup
├── SOP.md                   # Standard Operating Procedures
└── README.md                # Project documentation
```

---

## 8. Execution Order for Implementation

### Wave 1: Core Infrastructure (Days 1-3)
1. Set up project structure
2. Implement SQLite state manager
3. Create MinIO client wrapper
4. Build basic FastAPI skeleton

### Wave 2: Worker Components (Days 4-6)
1. Implement task executor with checkpointing
2. Build health sentinel with thermal detection
3. Create synthetic stress generator
4. Test checkpoint/resume flow

### Wave 3: Master Logic (Days 7-9)
1. Build heuristic scheduler
2. Implement task assignment API
3. Add WebSocket metrics streaming
4. Create drain/migrate controls

### Wave 4: AI Enhancement (Days 10-12)
1. Generate synthetic training data
2. Train Random Forest model
3. Integrate AI into scheduler
4. Implement fallback logic

### Wave 5: Dashboard & Polish (Days 13-15)
1. Build Streamlit dashboard
2. Add real-time visualizations
3. Implement authentication
4. Performance testing & demos

### Wave 6: LLM Integration (Days 16-18)
1. Set up Gemini API integration
2. Build natural language task parser
3. Create dashboard chat assistant
4. Add log analysis and anomaly explanation

---

## 🧠 LLM Integration (Gemini/Grok API)

### Why Add LLM?

| Use Case | Benefit |
|----------|---------|
| **Natural Language Task Submission** | "Run a heavy matrix calculation on 1000x1000 data" → parsed to task |
| **Dashboard Chat Assistant** | Ask "Why is Worker-2 slow?" and get intelligent analysis |
| **Log Analysis** | LLM reads error logs and suggests fixes |
| **Anomaly Explanation** | "Migration triggered because CPU spiked due to thermal throttling" |

### Recommended LLM APIs

| Provider | Model | Cost | Best For |
|----------|-------|------|----------|
| **Google Gemini** | gemini-2.0-flash | Free tier: 60 RPM | Primary choice |
| **xAI Grok** | grok-beta | $5/million tokens | Alternative |
| **OpenAI** | gpt-4o-mini | $0.15/million tokens | Fallback |

### Configuration (.env)

```env
LLM_PROVIDER=gemini
GEMINI_API_KEY=your-gemini-api-key-here
LLM_MODEL=gemini-2.0-flash
```

### LLM Use Cases

**1. Natural Language Task Submission:**
```
User: "Train a ResNet model for 10 epochs on the GPU"
LLM → {"task_type": "ml_training", "params": {"model": "resnet", "epochs": 10}, "requires_gpu": true}
```

**2. Dashboard Chat Assistant:**
```
User: "Why is Worker-2 running slowly?"
LLM: "Worker-2 has 94% CPU utilization and thermal throttling at 82°C. 
      Recommend draining tasks to Worker-3 which has 34% CPU and healthy thermals."
```

**3. Log Analysis:**
```
LLM analyzes: "ConnectionError: MinIO timeout after 5s"
LLM suggests: "MinIO server may be overloaded. Check storage node at 192.168.1.100:9000"
```

**4. Anomaly Explanation:**
```
Migration event → LLM explains: "Task migrated from Worker-1 to Worker-3 because 
Worker-1 triggered thermal protection (CPU temp reached 85°C for 5+ seconds)"
```