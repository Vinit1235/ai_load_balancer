"""
AI + Heuristic Scheduler for Task Assignment

Supports two modes:
  HEURISTIC — weighted CPU/RAM/task-count scoring (always works)
  AI        — RandomForest duration prediction (needs trained model)

Automatic fallback: if AI predictions are poor (MAPE > 30% for 3
consecutive tasks), the scheduler switches itself back to HEURISTIC
and logs a warning.
"""

import os
import logging
from typing import Optional, Dict, Any, List
from collections import deque

logger = logging.getLogger(__name__)

# Path to the trained model
MODEL_PATH = os.path.join(os.path.dirname(__file__), "..", "ai", "models", "random_forest.pkl")


class Scheduler:
    def __init__(self, state_manager):
        self.state_manager = state_manager
        self.mode = "HEURISTIC"  # "HEURISTIC" | "AI"
        self._model = None
        self._model_loaded = False

        # Track prediction accuracy for automatic fallback
        self._prediction_history: deque = deque(maxlen=10)
        self._consecutive_bad = 0
        self._fallback_threshold = 0.30  # 30% MAPE
        self._fallback_count = 3  # consecutive bad predictions before fallback

        # Try to load AI model at startup
        self._try_load_model()

    # ============================================================
    # PUBLIC API
    # ============================================================

    def select_node(self, task: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Select the best node for a task using current scheduling mode."""
        if self.mode == "AI" and self._model is not None:
            result = self._ai_select(task)
            if result is not None:
                return result
            # AI failed — fall through to heuristic
            logger.warning("AI selection returned None, falling back to heuristic")

        return self._heuristic_select(task)

    def switch_mode(self, new_mode: str) -> Dict[str, Any]:
        """
        Toggle between AI and HEURISTIC mode.
        Returns status dict with current mode and model info.
        """
        new_mode = new_mode.upper()

        if new_mode == "AI":
            if not self._model_loaded:
                self._try_load_model()
            if self._model is None:
                return {
                    "mode": self.mode,
                    "changed": False,
                    "error": "No trained model found. Train with: python -m ai.train_model",
                }
            self.mode = "AI"
            self._consecutive_bad = 0
            logger.info("Scheduler switched to AI mode")
        else:
            self.mode = "HEURISTIC"
            logger.info("Scheduler switched to HEURISTIC mode")

        return {
            "mode": self.mode,
            "changed": True,
            "model_rmse": getattr(self._model, "rmse", None),
            "model_r2": getattr(self._model, "r2", None),
        }

    def record_actual_duration(self, task_type: str, predicted: float, actual: float):
        """
        Record prediction vs actual for fallback monitoring.
        Called when a task completes.
        """
        if predicted <= 0:
            return

        error_pct = abs(predicted - actual) / actual if actual > 0 else 1.0
        self._prediction_history.append({
            "task_type": task_type,
            "predicted": predicted,
            "actual": actual,
            "error_pct": error_pct,
        })

        if error_pct > self._fallback_threshold:
            self._consecutive_bad += 1
            logger.warning(
                f"AI prediction error {error_pct:.1%} exceeds {self._fallback_threshold:.0%} "
                f"({self._consecutive_bad}/{self._fallback_count} consecutive)"
            )
            if self._consecutive_bad >= self._fallback_count and self.mode == "AI":
                self.mode = "HEURISTIC"
                logger.error("AUTO-FALLBACK: Switched to HEURISTIC mode due to poor predictions")
        else:
            self._consecutive_bad = 0

    def get_status(self) -> Dict[str, Any]:
        """Return scheduler status for dashboard display."""
        return {
            "mode": self.mode,
            "model_loaded": self._model is not None,
            "model_rmse": getattr(self._model, "rmse", None) if self._model else None,
            "model_r2": getattr(self._model, "r2", None) if self._model else None,
            "consecutive_bad_predictions": self._consecutive_bad,
            "recent_predictions": list(self._prediction_history),
            "feature_importances": (
                self._model.get_feature_importances()
                if self._model is not None
                else None
            ),
        }

    def drain_node(self, node_id: str):
        """Mark node as DRAINING — no new tasks will be assigned."""
        self.state_manager.update_node_status(node_id, "DRAINING")
        logger.info(f"Node {node_id} set to DRAINING")

    def migrate_task(self, task_id: str, target_node: str):
        """Move a task to a different node."""
        self.state_manager.assign_task(task_id, target_node)
        logger.info(f"Task {task_id} migrated to node {target_node}")

    def rebalance(self):
        """Spread pending tasks evenly across healthy nodes."""
        tasks = self.state_manager.get_pending_tasks()
        nodes = [n for n in self.state_manager.get_active_nodes()
                 if n.get("status", "").upper() != "DRAINING"]
        if not nodes:
            return
        for i, task in enumerate(tasks):
            node = nodes[i % len(nodes)]
            self.state_manager.assign_task(task["id"], node["id"])
        logger.info(f"Rebalanced {len(tasks)} tasks across {len(nodes)} nodes")

    # ============================================================
    # HEURISTIC MODE
    # ============================================================

    def _heuristic_select(self, task: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Classic weighted-score selection.
        score = (cpu + ram) * (1 + active_tasks * 0.2)
        Lower score = better node.
        """
        nodes = self.state_manager.get_active_nodes()
        best_node = None
        best_score = float("inf")

        for node in nodes:
            if node.get("status", "").upper() == "DRAINING":
                continue

            cpu = node.get("cpu", 0)
            ram = node.get("ram", 0)
            active = node.get("active_tasks", 0)
            score = (cpu + ram) * (1 + active * 0.2)

            if score < best_score:
                best_score = score
                best_node = node

        return best_node

    # ============================================================
    # AI MODE
    # ============================================================

    def _try_load_model(self):
        """Attempt to load the trained RandomForest model."""
        try:
            from ai.train_model import load_model
            self._model = load_model(MODEL_PATH)
            if self._model is not None:
                self._model_loaded = True
                logger.info(
                    f"AI Model loaded: RMSE={self._model.rmse:.3f}, R²={self._model.r2:.3f}"
                )
            else:
                logger.info("No AI model found — staying in HEURISTIC mode")
        except Exception as e:
            logger.warning(f"Failed to load AI model: {e}")
            self._model = None

    def _ai_select(self, task: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        AI-powered selection: predict duration on each node, pick fastest.

        For each healthy node, creates a feature vector and asks the
        RandomForest to predict how long the task would take there.
        Selects the node with the lowest predicted duration.
        """
        nodes = self.state_manager.get_active_nodes()
        candidates = [n for n in nodes if n.get("status", "").upper() != "DRAINING"]

        if not candidates:
            return None

        task_type = task.get("type", "synthetic_load")
        input_size = task.get("input_size", 100)

        best_node = None
        best_duration = float("inf")

        for node in candidates:
            try:
                predicted = self._model.predict_single(
                    task_type=task_type,
                    input_size=input_size,
                    cpu_at_submit=node.get("cpu", 50),
                    ram_at_submit=node.get("ram", 50),
                    active_tasks=node.get("active_tasks", 0),
                    gpu_available=1 if node.get("gpu_available") else 0,
                )

                # Add penalty for active tasks (avoid overloading)
                penalty = node.get("active_tasks", 0) * 2.0
                total = predicted + penalty

                if total < best_duration:
                    best_duration = total
                    best_node = node
                    best_node["_predicted_duration"] = predicted

            except Exception as e:
                logger.warning(f"AI prediction failed for node {node.get('id')}: {e}")
                continue

        if best_node:
            logger.info(
                f"AI selected node {best_node.get('name')} "
                f"(predicted: {best_node.get('_predicted_duration', '?'):.1f}s) "
                f"for {task_type} task (size={input_size})"
            )

        return best_node
