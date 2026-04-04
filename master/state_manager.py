"""
SQLite-based state management for cluster persistence
"""

import sqlite3
import json
from datetime import datetime
from typing import Optional, List, Dict, Any
from pathlib import Path
from shared.config import settings


class StateManager:
    """Manages cluster state persistence using SQLite"""
    
    def __init__(self, db_path: str = None):
        self.db_path = db_path or settings.DATABASE_PATH
        self.conn = None
        self.init_db()
    
    def init_db(self):
        """Initialize database and create tables if they don't exist"""
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row  # Return rows as dictionaries
        
        cursor = self.conn.cursor()
        
        # Nodes table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS nodes (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                ip TEXT NOT NULL,
                status TEXT DEFAULT 'HEALTHY',
                last_heartbeat TIMESTAMP,
                cpu REAL DEFAULT 0,
                ram REAL DEFAULT 0,
                thermal REAL DEFAULT 0,
                gpu_available INTEGER DEFAULT 0,
                gpu_utilization REAL DEFAULT 0,
                gpu_memory_used_mb INTEGER DEFAULT 0,
                gpu_temperature REAL DEFAULT 0,
                active_tasks INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Tasks table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                status TEXT DEFAULT 'PENDING',
                assigned_node TEXT,
                progress REAL DEFAULT 0,
                input_size INTEGER,
                requires_gpu INTEGER DEFAULT 0,
                priority TEXT DEFAULT 'medium',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                started_at TIMESTAMP,
                completed_at TIMESTAMP,
                FOREIGN KEY (assigned_node) REFERENCES nodes(id)
            )
        """)
        
        # Metrics table (for ML training)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS task_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                task_type TEXT NOT NULL,
                input_size INTEGER,
                assigned_node TEXT,
                cpu_at_submit REAL,
                ram_at_submit REAL,
                gpu_available INTEGER DEFAULT 0,
                active_tasks INTEGER,
                predicted_duration REAL,
                actual_duration REAL,
                was_migrated INTEGER DEFAULT 0,
                checkpoint_count INTEGER DEFAULT 0,
                recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (task_id) REFERENCES tasks(id)
            )
        """)
        
        self.conn.commit()
    
    # ---------- NODE OPERATIONS ----------
    
    def register_node(self, node_data: Dict[str, Any]) -> bool:
        """Add or update a node in the database"""
        cursor = self.conn.cursor()
        
        cursor.execute("""
            INSERT INTO nodes (id, name, ip, status, last_heartbeat, cpu, ram, thermal,
                             gpu_available, gpu_utilization, gpu_memory_used_mb, gpu_temperature, active_tasks)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name,
                ip=excluded.ip,
                status=excluded.status,
                last_heartbeat=excluded.last_heartbeat,
                cpu=excluded.cpu,
                ram=excluded.ram,
                thermal=excluded.thermal,
                gpu_available=excluded.gpu_available,
                gpu_utilization=excluded.gpu_utilization,
                gpu_memory_used_mb=excluded.gpu_memory_used_mb,
                gpu_temperature=excluded.gpu_temperature,
                active_tasks=excluded.active_tasks
        """, (
            node_data['id'],
            node_data['name'],
            node_data['ip'],
            node_data.get('status', 'HEALTHY'),
            datetime.now().isoformat(),
            node_data.get('cpu', 0),
            node_data.get('ram', 0),
            node_data.get('thermal', 0),
            1 if node_data.get('gpu_available') else 0,
            node_data.get('gpu_utilization', 0),
            node_data.get('gpu_memory_used_mb', 0),
            node_data.get('gpu_temperature', 0),
            node_data.get('active_tasks', 0)
        ))
        
        self.conn.commit()
        return True
    
    def get_active_nodes(self) -> List[Dict[str, Any]]:
        """Get all healthy nodes"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM nodes 
            WHERE status IN ('HEALTHY', 'DRAINING')
            ORDER BY name
        """)
        
        return [dict(row) for row in cursor.fetchall()]
    
    def get_node(self, node_id: str) -> Optional[Dict[str, Any]]:
        """Get specific node by ID"""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM nodes WHERE id = ?", (node_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
    
    def update_node_status(self, node_id: str, status: str):
        """Update node status"""
        cursor = self.conn.cursor()
        cursor.execute("""
            UPDATE nodes SET status = ?, last_heartbeat = ?
            WHERE id = ?
        """, (status, datetime.now().isoformat(), node_id))
        self.conn.commit()
    
    def update_node_metrics(self, node_id: str, metrics: Dict[str, Any]):
        """Update node metrics (CPU, RAM, etc.)"""
        cursor = self.conn.cursor()
        cursor.execute("""
            UPDATE nodes SET
                cpu = ?,
                ram = ?,
                thermal = ?,
                gpu_utilization = ?,
                gpu_temperature = ?,
                active_tasks = ?,
                last_heartbeat = ?
            WHERE id = ?
        """, (
            metrics.get('cpu', 0),
            metrics.get('ram', 0),
            metrics.get('thermal', 0),
            metrics.get('gpu_utilization', 0),
            metrics.get('gpu_temperature', 0),
            metrics.get('active_tasks', 0),
            datetime.now().isoformat(),
            node_id
        ))
        self.conn.commit()
    
    # ---------- TASK OPERATIONS ----------
    
    def create_task(self, task_data: Dict[str, Any]) -> str:
        """Create a new task"""
        cursor = self.conn.cursor()
        
        task_id = task_data['id']
        cursor.execute("""
            INSERT INTO tasks (id, type, status, assigned_node, input_size, requires_gpu, priority)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            task_id,
            task_data['type'],
            task_data.get('status', 'PENDING'),
            task_data.get('assigned_node'),
            task_data.get('input_size', 0),
            1 if task_data.get('requires_gpu') else 0,
            task_data.get('priority', 'medium')
        ))
        
        self.conn.commit()
        return task_id
    
    def update_task_status(self, task_id: str, status: str, progress: float = None):
        """Update task status and optionally progress"""
        cursor = self.conn.cursor()
        
        if status == 'RUNNING' and progress is None:
            cursor.execute("""
                UPDATE tasks SET status = ?, started_at = ?
                WHERE id = ?
            """, (status, datetime.now().isoformat(), task_id))
        elif status == 'COMPLETED':
            cursor.execute("""
                UPDATE tasks SET status = ?, completed_at = ?, progress = 100
                WHERE id = ?
            """, (status, datetime.now().isoformat(), task_id))
        else:
            update_fields = ["status = ?"]
            params = [status]
            
            if progress is not None:
                update_fields.append("progress = ?")
                params.append(progress)
            
            params.append(task_id)
            cursor.execute(f"""
                UPDATE tasks SET {', '.join(update_fields)}
                WHERE id = ?
            """, params)
        
        self.conn.commit()
    
    def get_pending_tasks(self) -> List[Dict[str, Any]]:
        """Get all tasks waiting for assignment"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM tasks 
            WHERE status = 'PENDING'
            ORDER BY 
                CASE priority
                    WHEN 'high' THEN 1
                    WHEN 'medium' THEN 2
                    WHEN 'low' THEN 3
                END,
                created_at
        """)
        return [dict(row) for row in cursor.fetchall()]
    
    def assign_pending_task(self, node_id: str) -> Optional[Dict[str, Any]]:
        """
        Atomically find exactly 1 pending task and assign it to the given node,
        but ONLY if this node is the absolute best candidate based on heuristic load.
        """
        # ==========================================================
        # 1. HEURISTIC LEAST-LOAD EVALUATION
        # ==========================================================
        active_nodes = self.get_active_nodes()
        if not active_nodes:
            return None
            
        best_node_id = None
        lowest_score = float('inf')
        
        for n in active_nodes:
            if n.get("status", "").upper() == "DRAINING":
                continue
                
            cpu = n.get("cpu", 0)
            ram = n.get("ram", 0)
            active_tasks = n.get("active_tasks", 0)
            
            # Hardware Telemetry Stress Score Equation
            # Prioritizes free CPU, punishes active concurrent tasks heavily
            score = (cpu * 0.5) + (ram * 0.3) + (active_tasks * 20)
            
            if score < lowest_score:
                lowest_score = score
                best_node_id = n.get("id")
                
        # GATEKEEPER CHECK: 
        # Is the node asking for the task truly the least stressed?
        if best_node_id != node_id:
            return None  # Reject the pull request; force a better node to claim it.

        # ==========================================================
        # 2. ATOMIC ASSIGNMENT
        # ==========================================================
        cursor = self.conn.cursor()
        
        # We find the highest priority task
        cursor.execute("""
            SELECT id FROM tasks 
            WHERE status = 'PENDING'
            ORDER BY 
                CASE priority
                    WHEN 'high' THEN 1
                    WHEN 'medium' THEN 2
                    WHEN 'low' THEN 3
                END,
                created_at ASC
            LIMIT 1
        """)
        row = cursor.fetchone()
        
        if not row:
            return None
            
        task_id = row['id']
        now = datetime.now().isoformat()
        
        # Atomically try to claim it
        cursor.execute("""
            UPDATE tasks 
            SET status = 'ASSIGNED', assigned_node = ?, started_at = ?
            WHERE id = ? AND status = 'PENDING'
        """, (node_id, now, task_id))
        
        if cursor.rowcount == 0:
            return None
            
        self.conn.commit()
        
        # Return the newly assigned task
        cursor.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        task_row = cursor.fetchone()
        return dict(task_row) if task_row else None
        
    def get_node_tasks(self, node_id: str) -> List[Dict[str, Any]]:
        """Get all tasks assigned to a specific node"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM tasks 
            WHERE assigned_node = ? AND status IN ('RUNNING', 'PENDING')
        """, (node_id,))
        return [dict(row) for row in cursor.fetchall()]
    
    def get_all_tasks(self) -> List[Dict[str, Any]]:
        """Get all tasks"""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM tasks ORDER BY created_at DESC")
        return [dict(row) for row in cursor.fetchall()]
    
    def assign_task(self, task_id: str, node_id: str):
        """Assign task to a node"""
        cursor = self.conn.cursor()
        cursor.execute("""
            UPDATE tasks SET assigned_node = ?, status = 'ASSIGNED'
            WHERE id = ?
        """, (node_id, task_id))
        self.conn.commit()
    
    # ---------- METRICS OPERATIONS ----------
    
    def log_task_metrics(self, metrics: Dict[str, Any]):
        """Record task completion metrics for ML training"""
        cursor = self.conn.cursor()
        
        cursor.execute("""
            INSERT INTO task_metrics (
                task_id, task_type, input_size, assigned_node,
                cpu_at_submit, ram_at_submit, gpu_available, active_tasks,
                predicted_duration, actual_duration, was_migrated, checkpoint_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            metrics['task_id'],
            metrics['task_type'],
            metrics.get('input_size', 0),
            metrics.get('assigned_node'),
            metrics.get('cpu_at_submit', 0),
            metrics.get('ram_at_submit', 0),
            1 if metrics.get('gpu_available') else 0,
            metrics.get('active_tasks', 0),
            metrics.get('predicted_duration'),
            metrics.get('actual_duration'),
            1 if metrics.get('was_migrated') else 0,
            metrics.get('checkpoint_count', 0)
        ))
        
        self.conn.commit()
    
    def get_training_data(self, limit: int = 1000) -> List[Dict[str, Any]]:
        """Get metrics for ML training"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM task_metrics
            WHERE actual_duration IS NOT NULL
            ORDER BY recorded_at DESC
            LIMIT ?
        """, (limit,))
        return [dict(row) for row in cursor.fetchall()]
    
    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()


# Singleton instance
state_manager = StateManager()
