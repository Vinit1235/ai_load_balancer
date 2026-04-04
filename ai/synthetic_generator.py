"""
Synthetic Training Data Generator for AI Scheduler

Generates realistic task execution logs for training the RandomForest
duration predictor. Each record simulates a task that ran on a node
with specific resource conditions and records how long it took.

Duration formulas encode real-world relationships:
  - matrix_multiply is CPU-bound → sensitive to cpu_at_submit
  - compress_data is I/O + memory bound → sensitive to ram_at_submit
  - synthetic_load scales linearly with input_size
  - ml_training is GPU-sensitive when available
  - inference is batch-dependent
"""

import csv
import random
import argparse
import os
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

# Duration calculation functions per task type
TASK_DURATION_FORMULAS = {
    "matrix_multiply": lambda s, cpu, ram, tasks, gpu:
        (s * 0.1) + (cpu * 0.05) + (tasks * 1.5),

    "compress_data": lambda s, cpu, ram, tasks, gpu:
        (s * 0.05) + (ram * 0.03) + (tasks * 0.8),

    "synthetic_load": lambda s, cpu, ram, tasks, gpu:
        (s * 0.2) + (cpu * 0.02),

    "ml_training": lambda s, cpu, ram, tasks, gpu:
        (s * 0.15) + (cpu * 0.04) + (ram * 0.02) + (0 if gpu else s * 0.05),

    "inference": lambda s, cpu, ram, tasks, gpu:
        (s * 0.03) + (cpu * 0.01) + (0 if gpu else s * 0.02),
}

TASK_TYPES = list(TASK_DURATION_FORMULAS.keys())


def generate_single_record(task_type: str = None) -> Dict[str, Any]:
    """Generate a single synthetic execution record."""
    if task_type is None:
        task_type = random.choice(TASK_TYPES)

    input_size = random.randint(10, 1000)
    cpu_at_submit = round(random.uniform(5, 95), 1)
    ram_at_submit = round(random.uniform(10, 90), 1)
    active_tasks = random.randint(0, 15)
    gpu_available = random.choice([0, 1])

    # Calculate base duration from formula
    formula = TASK_DURATION_FORMULAS[task_type]
    base_duration = formula(input_size, cpu_at_submit, ram_at_submit, active_tasks, gpu_available)

    # Add realistic noise (±15%)
    noise_factor = random.uniform(0.85, 1.15)
    actual_duration = round(max(0.5, base_duration * noise_factor), 2)

    return {
        "task_type": task_type,
        "input_size": input_size,
        "cpu_at_submit": cpu_at_submit,
        "ram_at_submit": ram_at_submit,
        "active_tasks": active_tasks,
        "gpu_available": gpu_available,
        "actual_duration": actual_duration,
    }


def generate_training_data(
    count: int = 200,
    output_file: str = None,
    seed: int = 42,
) -> List[Dict[str, Any]]:
    """
    Generate synthetic training data.

    Args:
        count: Number of records to generate (default 200)
        output_file: CSV file path to write (optional)
        seed: Random seed for reproducibility

    Returns:
        List of record dictionaries
    """
    random.seed(seed)
    records = [generate_single_record() for _ in range(count)]

    if output_file:
        os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)
        fieldnames = [
            "task_type", "input_size", "cpu_at_submit",
            "ram_at_submit", "active_tasks", "gpu_available",
            "actual_duration",
        ]
        with open(output_file, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(records)

        logger.info(f"Generated {count} records → {output_file}")

    return records


def generate_from_db(state_manager, min_records: int = 50) -> List[Dict[str, Any]]:
    """
    Pull real execution metrics from the database.
    Falls back to synthetic data if not enough real data exists.

    Args:
        state_manager: StateManager instance
        min_records: Minimum records needed for training

    Returns:
        List of training records
    """
    real_data = state_manager.get_training_data(limit=1000)

    if len(real_data) >= min_records:
        logger.info(f"Using {len(real_data)} real execution records for training")
        return [
            {
                "task_type": r["task_type"],
                "input_size": r.get("input_size", 100),
                "cpu_at_submit": r.get("cpu_at_submit", 50),
                "ram_at_submit": r.get("ram_at_submit", 50),
                "active_tasks": r.get("active_tasks", 0),
                "gpu_available": r.get("gpu_available", 0),
                "actual_duration": r["actual_duration"],
            }
            for r in real_data
            if r.get("actual_duration") is not None
        ]

    # Not enough real data — generate synthetic
    synthetic_count = max(min_records, 200)
    logger.warning(
        f"Only {len(real_data)} real records (need {min_records}). "
        f"Generating {synthetic_count} synthetic records."
    )
    return generate_training_data(count=synthetic_count)


# ---- CLI entrypoint ----
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate synthetic training data")
    parser.add_argument("--count", type=int, default=200, help="Number of records")
    parser.add_argument("--output", default="ai/models/execution_logs.csv", help="Output CSV path")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)

    data = generate_training_data(count=args.count, output_file=args.output, seed=args.seed)
    print(f"✓ Generated {len(data)} synthetic records → {args.output}")
