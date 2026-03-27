"""
Task executor with checkpoint support for fault-tolerant execution

Enhanced with self-correction capabilities for automatic error handling
and recovery during task execution.
"""

import time
import numpy as np
import logging
import traceback
from typing import Dict, Any, Generator, Optional, List
from datetime import datetime
from dataclasses import dataclass, field
from shared.minio_client import minio_client
from shared.self_correction import (
    SelfCorrectionEngine, 
    RetryConfig, 
    ErrorContext,
    ErrorCategory,
    ErrorSeverity
)

logger = logging.getLogger(__name__)


@dataclass
class ExecutionContext:
    """Context for tracking execution with self-correction"""
    task_id: str
    task_type: str
    attempts: int = 0
    max_attempts: int = 3
    errors: List[ErrorContext] = field(default_factory=list)
    corrections: List[str] = field(default_factory=list)
    recovered: bool = False


class TaskExecutor:
    """
    Executes tasks with checkpointing for migration support.
    
    Enhanced with self-correction capabilities:
    - Automatic error detection and categorization
    - Retry logic with exponential backoff
    - Graceful degradation on failures
    - Execution context tracking
    """
    
    def __init__(self, max_retries: int = 3):
        self.checkpoint_interval = 30  # seconds
        self.last_checkpoint_time = 0
        self.max_retries = max_retries
        
        # Self-correction engine
        self.correction_engine = SelfCorrectionEngine()
        self.retry_config = RetryConfig(
            max_retries=max_retries,
            initial_delay=1.0,
            max_delay=30.0,
            exponential_backoff=True
        )
        
        # Track execution contexts
        self.active_contexts: Dict[str, ExecutionContext] = {}
    
    def execute(
        self, 
        task_id: str, 
        task_type: str, 
        params: Dict[str, Any]
    ) -> Generator[Dict[str, Any], None, None]:
        """
        Execute a task with checkpointing and self-correction.
        
        Args:
            task_id: Unique task identifier
            task_type: Type of task to execute
            params: Task parameters
        
        Yields:
            Progress updates with current state
        """
        logger.info(f"Starting task {task_id} (type: {task_type})")
        
        # Create execution context
        ctx = ExecutionContext(
            task_id=task_id,
            task_type=task_type,
            max_attempts=self.max_retries + 1
        )
        self.active_contexts[task_id] = ctx
        
        try:
            # Wrap execution with self-correction
            yield from self._execute_with_correction(task_id, task_type, params, ctx)
        finally:
            # Clean up context
            if task_id in self.active_contexts:
                del self.active_contexts[task_id]
    
    def _execute_with_correction(
        self,
        task_id: str,
        task_type: str,
        params: Dict[str, Any],
        ctx: ExecutionContext
    ) -> Generator[Dict[str, Any], None, None]:
        """Execute with automatic error correction and retry"""
        
        last_error: Optional[ErrorContext] = None
        
        while ctx.attempts < ctx.max_attempts:
            ctx.attempts += 1
            
            try:
                # Try to load existing checkpoint
                state = self._load_checkpoint(task_id)
                
                if state is None:
                    state = {
                        "progress": 0,
                        "data": None,
                        "start_time": datetime.now().isoformat(),
                        "checkpoint_count": 0,
                        "attempt": ctx.attempts,
                        "recovered_from_error": last_error is not None
                    }
                    logger.info(f"Task {task_id}: Starting from beginning (attempt {ctx.attempts})")
                else:
                    logger.info(
                        f"Task {task_id}: Resuming from checkpoint at {state['progress']}% "
                        f"(attempt {ctx.attempts})"
                    )
                    ctx.recovered = True
                
                # Execute based on task type
                task_generator = self._get_task_generator(task_id, task_type, params, state)
                if task_generator is None:
                    raise ValueError(f"Unknown task type: {task_type}")
                
                # Yield all progress updates
                for progress in task_generator:
                    # Add correction info to progress
                    progress["attempt"] = ctx.attempts
                    progress["errors_count"] = len(ctx.errors)
                    progress["recovered"] = ctx.recovered
                    yield progress
                
                # Success! Delete checkpoint
                minio_client.delete_checkpoint(task_id)
                logger.info(f"Task {task_id} completed successfully after {ctx.attempts} attempt(s)")
                
                # Yield final success with correction stats
                yield {
                    "task_id": task_id,
                    "status": "completed",
                    "progress": 100,
                    "attempts": ctx.attempts,
                    "errors_encountered": len(ctx.errors),
                    "corrections_applied": len(ctx.corrections),
                    "recovered": ctx.recovered
                }
                return
            
            except Exception as e:
                # Parse and record the error
                error_ctx = self.correction_engine.parse_error(e)
                ctx.errors.append(error_ctx)
                last_error = error_ctx
                
                logger.warning(
                    f"Task {task_id} failed on attempt {ctx.attempts}: "
                    f"{error_ctx.error_type}: {error_ctx.error_message}"
                )
                
                # Check if we should retry
                if ctx.attempts < ctx.max_attempts:
                    # Determine retry delay
                    delay = self._calculate_retry_delay(ctx.attempts, error_ctx)
                    
                    # Apply any automatic corrections for next attempt
                    correction = self._apply_correction(task_id, task_type, params, error_ctx)
                    if correction:
                        ctx.corrections.append(correction)
                        logger.info(f"Task {task_id}: Applied correction - {correction}")
                    
                    logger.info(f"Task {task_id}: Retrying in {delay:.1f}s...")
                    
                    # Yield error info
                    yield {
                        "task_id": task_id,
                        "status": "retrying",
                        "error": error_ctx.error_message,
                        "error_type": error_ctx.error_type,
                        "attempt": ctx.attempts,
                        "next_attempt_in": delay,
                        "correction_applied": correction
                    }
                    
                    time.sleep(delay)
                else:
                    # Max retries exceeded
                    logger.error(
                        f"Task {task_id} failed after {ctx.attempts} attempts. "
                        f"Errors: {[e.error_type for e in ctx.errors]}"
                    )
                    
                    yield {
                        "task_id": task_id,
                        "status": "failed",
                        "error": error_ctx.error_message,
                        "error_type": error_ctx.error_type,
                        "total_attempts": ctx.attempts,
                        "all_errors": [
                            {"type": e.error_type, "message": e.error_message[:200]}
                            for e in ctx.errors
                        ],
                        "suggestions": error_ctx.suggested_fixes
                    }
                    raise
    
    def _get_task_generator(
        self,
        task_id: str,
        task_type: str,
        params: Dict[str, Any],
        state: Dict[str, Any]
    ) -> Optional[Generator]:
        """Get the appropriate task generator based on type"""
        task_map = {
            "matrix_multiply": self._matrix_multiply,
            "compress_data": self._compress_data,
            "ml_training": self._ml_training,
            "inference": self._inference,
            "synthetic_load": self._synthetic_load,
        }
        
        handler = task_map.get(task_type)
        if handler:
            return handler(task_id, params, state)
        return None
    
    def _calculate_retry_delay(self, attempt: int, error: ErrorContext) -> float:
        """Calculate delay before retry based on error type and attempt"""
        base_delay = self.retry_config.initial_delay
        
        # Exponential backoff
        delay = base_delay * (self.retry_config.backoff_multiplier ** (attempt - 1))
        
        # Adjust based on error category
        if error.category == ErrorCategory.NETWORK:
            delay *= 2  # Network errors: wait longer
        elif error.category == ErrorCategory.RESOURCE:
            delay *= 3  # Resource errors: wait even longer
        elif error.category == ErrorCategory.RUNTIME:
            delay *= 0.5  # Runtime errors: quick retry might work
        
        return min(delay, self.retry_config.max_delay)
    
    def _apply_correction(
        self,
        task_id: str,
        task_type: str,
        params: Dict[str, Any],
        error: ErrorContext
    ) -> Optional[str]:
        """Apply corrections based on error type"""
        
        # Network errors: might need to refresh connections
        if error.category == ErrorCategory.NETWORK:
            try:
                # Try to reinitialize MinIO connection
                minio_client.init_minio()
                return "Reinitialized storage connection"
            except Exception:
                pass
        
        # Resource errors: might need to reduce workload
        if error.category == ErrorCategory.RESOURCE:
            if "memory" in error.error_message.lower():
                # Try to reduce batch size or chunk size
                if "batch_size" in params:
                    params["batch_size"] = max(1, params["batch_size"] // 2)
                    return f"Reduced batch_size to {params['batch_size']}"
                if "size" in params:
                    params["size"] = max(100, params["size"] // 2)
                    return f"Reduced size to {params['size']}"
        
        # Import errors: might need to install dependencies
        if error.category == ErrorCategory.IMPORT:
            # This is handled by self_correction.py's auto-fix
            return "Attempting to install missing module"
        
        return None
    
    def get_execution_stats(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Get execution statistics for a task"""
        ctx = self.active_contexts.get(task_id)
        if not ctx:
            return None
        
        return {
            "task_id": ctx.task_id,
            "task_type": ctx.task_type,
            "attempts": ctx.attempts,
            "max_attempts": ctx.max_attempts,
            "errors": len(ctx.errors),
            "corrections": len(ctx.corrections),
            "recovered": ctx.recovered,
            "correction_details": [
                {"type": e.error_type, "category": e.category.value}
                for e in ctx.errors
            ]
        }
    
    def get_correction_summary(self) -> Dict[str, Any]:
        """Get summary of all corrections made"""
        return self.correction_engine.get_correction_stats()
    
    def _load_checkpoint(self, task_id: str) -> Dict[str, Any]:
        """Load checkpoint from MinIO"""
        return minio_client.get_checkpoint(task_id)
    
    def _save_checkpoint(self, task_id: str, state: Dict[str, Any]):
        """Save checkpoint to MinIO"""
        current_time = time.time()
        if current_time - self.last_checkpoint_time >= self.checkpoint_interval:
            if minio_client.save_checkpoint(task_id, state):
                state["checkpoint_count"] += 1
                self.last_checkpoint_time = current_time
                logger.debug(f"Checkpoint saved for task {task_id} (count: {state['checkpoint_count']})")
    
    def _matrix_multiply(self, task_id: str, params: Dict[str, Any], state: Dict[str, Any]) -> Generator:
        """CPU-intensive matrix multiplication"""
        size = params.get("size", 500)
        iterations = params.get("iterations", 10)
        
        # Initialize matrices if starting fresh
        if state["data"] is None:
            state["data"] = {
                "A": np.random.rand(size, size),
                "B": np.random.rand(size, size),
                "result": None
            }
        
        start_iteration = int(state["progress"] / 100 * iterations)
        
        for i in range(start_iteration, iterations):
            # Perform matrix multiplication
            result = np.matmul(state["data"]["A"], state["data"]["B"])
            state["data"]["result"] = result
            
            # Update progress
            state["progress"] = ((i + 1) / iterations) * 100
            
            # Save checkpoint periodically
            self._save_checkpoint(task_id, state)
            
            # Yield progress
            yield {
                "task_id": task_id,
                "progress": state["progress"],
                "iteration": i + 1,
                "total_iterations": iterations
            }
            
            # Simulate work
            time.sleep(0.5)
    
    def _compress_data(self, task_id: str, params: Dict[str, Any], state: Dict[str, Any]) -> Generator:
        """I/O intensive data compression simulation"""
        import zlib
        
        data_size_mb = params.get("data_size_mb", 100)
        chunk_size = 1024 * 1024  # 1MB chunks
        total_chunks = data_size_mb
        
        start_chunk = int(state["progress"] / 100 * total_chunks)
        
        for i in range(start_chunk, total_chunks):
            # Generate and compress random data
            data = np.random.bytes(chunk_size)
            compressed = zlib.compress(data, level=6)
            
            # Update progress
            state["progress"] = ((i + 1) / total_chunks) * 100
            
            # Save checkpoint
            self._save_checkpoint(task_id, state)
            
            # Yield progress
            yield {
                "task_id": task_id,
                "progress": state["progress"],
                "chunk": i + 1,
                "total_chunks": total_chunks,
                "compression_ratio": len(data) / len(compressed)
            }
            
            time.sleep(0.2)
    
    def _ml_training(self, task_id: str, params: Dict[str, Any], state: Dict[str, Any]) -> Generator:
        """ML training simulation (requires GPU)"""
        epochs = params.get("epochs", 10)
        model_type = params.get("model_type", "resnet")
        
        start_epoch = int(state["progress"] / 100 * epochs)
        
        logger.info(f"Training {model_type} for {epochs} epochs (GPU-accelerated)")
        
        for epoch in range(start_epoch, epochs):
            # Simulate training
            loss = 1.0 / (epoch + 1)  # Decreasing loss
            accuracy = 1.0 - loss
            
            # Update progress
            state["progress"] = ((epoch + 1) / epochs) * 100
            
            # Save checkpoint
            self._save_checkpoint(task_id, state)
            
            # Yield progress
            yield {
                "task_id": task_id,
                "progress": state["progress"],
                "epoch": epoch + 1,
                "total_epochs": epochs,
                "loss": loss,
                "accuracy": accuracy
            }
            
            time.sleep(1.0)
    
    def _inference(self, task_id: str, params: Dict[str, Any], state: Dict[str, Any]) -> Generator:
        """ML inference simulation (prefers GPU)"""
        batch_size = params.get("batch_size", 32)
        total_batches = params.get("total_batches", 100)
        
        start_batch = int(state["progress"] / 100 * total_batches)
        
        for batch in range(start_batch, total_batches):
            # Simulate inference
            predictions = np.random.rand(batch_size, 10)  # 10 classes
            
            # Update progress
            state["progress"] = ((batch + 1) / total_batches) * 100
            
            # Save checkpoint
            self._save_checkpoint(task_id, state)
            
            # Yield progress
            yield {
                "task_id": task_id,
                "progress": state["progress"],
                "batch": batch + 1,
                "total_batches": total_batches
            }
            
            time.sleep(0.1)
    
    def _synthetic_load(self, task_id: str, params: Dict[str, Any], state: Dict[str, Any]) -> Generator:
        """Synthetic CPU load using stress-ng or pure Python"""
        import subprocess
        import platform
        
        cores = params.get("cores", 2)
        duration_sec = params.get("duration_sec", 60)
        
        # Try to use stress-ng if available
        try:
            if platform.system() == "Linux":
                cmd = f"stress-ng --cpu {cores} --timeout {duration_sec}s"
                logger.info(f"Running: {cmd}")
                
                process = subprocess.Popen(cmd.split(), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                
                start_time = time.time()
                while process.poll() is None and time.time() - start_time < duration_sec:
                    elapsed = time.time() - start_time
                    state["progress"] = (elapsed / duration_sec) * 100
                    
                    yield {
                        "task_id": task_id,
                        "progress": state["progress"],
                        "elapsed": elapsed,
                        "duration": duration_sec
                    }
                    
                    time.sleep(1)
                
                state["progress"] = 100
                yield {"task_id": task_id, "progress": 100}
            else:
                # Fallback: Pure Python CPU burn
                logger.info("stress-ng not available, using Python CPU burn")
                yield from self._python_cpu_burn(task_id, duration_sec, state)
        
        except FileNotFoundError:
            # stress-ng not installed, fallback to Python
            logger.warning("stress-ng not found, using Python CPU burn")
            yield from self._python_cpu_burn(task_id, duration_sec, state)
    
    def _python_cpu_burn(self, task_id: str, duration_sec: int, state: Dict[str, Any]) -> Generator:
        """Pure Python CPU burning (fallback)"""
        start_time = time.time()
        
        while time.time() - start_time < duration_sec:
            # Burn CPU with pointless calculations
            _ = sum([i**2 for i in range(10000)])
            
            elapsed = time.time() - start_time
            state["progress"] = (elapsed / duration_sec) * 100
            
            if int(elapsed) % 5 == 0:  # Report every 5 seconds
                yield {
                    "task_id": task_id,
                    "progress": state["progress"],
                    "elapsed": elapsed,
                    "duration": duration_sec
                }
        
        state["progress"] = 100
        yield {"task_id": task_id, "progress": 100}


# Singleton instance
executor = TaskExecutor()
