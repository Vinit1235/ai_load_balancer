"""
Random Forest Model Training for AI Scheduler

Trains a duration predictor that the scheduler uses to decide
which node will complete a task fastest.

Pipeline:
  1. Load CSV data (or generate synthetic)
  2. One-hot encode task_type
  3. Scale numeric features
  4. 80/20 train/test split
  5. Train RandomForestRegressor (100 trees)
  6. Evaluate RMSE
  7. Save model only if RMSE < threshold (quality gate)
"""

import os
import sys
import argparse
import logging
import joblib
import numpy as np
import pandas as pd
from datetime import datetime
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler, OneHotEncoder
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score

logger = logging.getLogger(__name__)

# Feature columns
CATEGORICAL_FEATURES = ["task_type"]
NUMERIC_FEATURES = ["input_size", "cpu_at_submit", "ram_at_submit", "active_tasks", "gpu_available"]
TARGET = "actual_duration"

# Default paths
DEFAULT_INPUT = os.path.join(os.path.dirname(__file__), "models", "execution_logs.csv")
DEFAULT_OUTPUT = os.path.join(os.path.dirname(__file__), "models", "random_forest.pkl")


class DurationPredictor:
    """Wraps the trained pipeline with metadata and prediction helpers."""

    def __init__(self, pipeline, rmse, mae, r2, feature_names, training_info):
        self.pipeline = pipeline
        self.rmse = rmse
        self.mae = mae
        self.r2 = r2
        self.feature_names = feature_names
        self.training_info = training_info

    def predict(self, features_df: pd.DataFrame) -> np.ndarray:
        """Predict duration for a DataFrame of features."""
        return self.pipeline.predict(features_df)

    def predict_single(
        self,
        task_type: str,
        input_size: int,
        cpu_at_submit: float,
        ram_at_submit: float,
        active_tasks: int,
        gpu_available: int = 0,
    ) -> float:
        """Predict duration for a single task."""
        df = pd.DataFrame([{
            "task_type": task_type,
            "input_size": input_size,
            "cpu_at_submit": cpu_at_submit,
            "ram_at_submit": ram_at_submit,
            "active_tasks": active_tasks,
            "gpu_available": gpu_available,
        }])
        prediction = self.pipeline.predict(df)
        return float(prediction[0])

    def get_feature_importances(self) -> dict:
        """Get feature importance rankings from the RandomForest."""
        rf = self.pipeline.named_steps["regressor"]
        preprocessor = self.pipeline.named_steps["preprocessor"]

        # Get feature names after transformation
        cat_features = list(
            preprocessor.transformers_[0][1].get_feature_names_out(CATEGORICAL_FEATURES)
        )
        all_features = cat_features + NUMERIC_FEATURES
        importances = rf.feature_importances_

        return dict(sorted(
            zip(all_features, importances),
            key=lambda x: x[1],
            reverse=True,
        ))


def load_data(input_path: str) -> pd.DataFrame:
    """Load training data from CSV, generating synthetic if needed."""
    if os.path.exists(input_path):
        df = pd.read_csv(input_path)
        logger.info(f"Loaded {len(df)} records from {input_path}")
    else:
        logger.warning(f"{input_path} not found — generating synthetic data")
        from ai.synthetic_generator import generate_training_data
        records = generate_training_data(count=200, output_file=input_path)
        df = pd.DataFrame(records)

    # Validate required columns
    required = CATEGORICAL_FEATURES + NUMERIC_FEATURES + [TARGET]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing columns in training data: {missing}")

    # Drop rows with missing target
    df = df.dropna(subset=[TARGET])
    logger.info(f"Training data: {len(df)} records, {len(df.columns)} columns")
    return df


def train_model(
    input_path: str = DEFAULT_INPUT,
    output_path: str = DEFAULT_OUTPUT,
    min_rmse: float = 5.0,
    n_estimators: int = 100,
    test_size: float = 0.2,
    random_state: int = 42,
) -> DurationPredictor:
    """
    Train the RandomForest duration predictor.

    Args:
        input_path: Path to training CSV
        output_path: Path to save trained model
        min_rmse: Maximum acceptable RMSE (quality gate)
        n_estimators: Number of trees in the forest
        test_size: Fraction held out for testing
        random_state: Random seed

    Returns:
        Trained DurationPredictor instance
    """
    # 1. Load data
    df = load_data(input_path)

    X = df[CATEGORICAL_FEATURES + NUMERIC_FEATURES]
    y = df[TARGET]

    # 2. Build sklearn pipeline
    preprocessor = ColumnTransformer(
        transformers=[
            ("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False), CATEGORICAL_FEATURES),
            ("num", StandardScaler(), NUMERIC_FEATURES),
        ]
    )

    pipeline = Pipeline([
        ("preprocessor", preprocessor),
        ("regressor", RandomForestRegressor(
            n_estimators=n_estimators,
            max_depth=12,
            min_samples_split=5,
            min_samples_leaf=2,
            random_state=random_state,
            n_jobs=-1,
        )),
    ])

    # 3. Train/test split
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=test_size, random_state=random_state
    )

    logger.info(f"Training set: {len(X_train)} | Test set: {len(X_test)}")

    # 4. Fit
    pipeline.fit(X_train, y_train)

    # 5. Evaluate
    y_pred = pipeline.predict(X_test)
    rmse = float(np.sqrt(mean_squared_error(y_test, y_pred)))
    mae = float(mean_absolute_error(y_test, y_pred))
    r2 = float(r2_score(y_test, y_pred))

    logger.info(f"Model RMSE: {rmse:.3f}s | MAE: {mae:.3f}s | R²: {r2:.3f}")

    # 6. Quality gate
    if rmse > min_rmse:
        logger.error(f"RMSE {rmse:.3f} exceeds threshold {min_rmse}. Model NOT saved.")
        raise ValueError(f"Model quality too low: RMSE={rmse:.3f} > {min_rmse}")

    # 7. Package and save
    training_info = {
        "trained_at": datetime.now().isoformat(),
        "training_records": len(X_train),
        "test_records": len(X_test),
        "n_estimators": n_estimators,
        "input_path": input_path,
        "random_state": random_state,
    }

    model_data = {
        "pipeline": pipeline,
        "rmse": rmse,
        "mae": mae,
        "r2": r2,
        "feature_names": CATEGORICAL_FEATURES + NUMERIC_FEATURES,
        "training_info": training_info,
    }

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    joblib.dump(model_data, output_path)
    logger.info(f"✓ Model saved → {output_path}  (RMSE={rmse:.3f}, R²={r2:.3f})")

    return DurationPredictor(**model_data)


def load_model(model_path: str = DEFAULT_OUTPUT) -> DurationPredictor:
    """Load a trained model from disk."""
    if not os.path.exists(model_path):
        return None
    model_data = joblib.load(model_path)
    predictor = DurationPredictor(**model_data)
    logger.info(f"Loaded model: RMSE={predictor.rmse:.3f}, R²={predictor.r2:.3f}")
    return predictor


# ---- CLI ----
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train AI scheduler model")
    parser.add_argument("--input", default=DEFAULT_INPUT, help="Training CSV path")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="Output model path")
    parser.add_argument("--min-rmse", type=float, default=5.0, help="Max acceptable RMSE")
    parser.add_argument("--trees", type=int, default=100, help="Number of estimators")

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    try:
        predictor = train_model(
            input_path=args.input,
            output_path=args.output,
            min_rmse=args.min_rmse,
            n_estimators=args.trees,
        )
        print(f"\n✅ Model trained successfully!")
        print(f"   RMSE:  {predictor.rmse:.3f} seconds")
        print(f"   MAE:   {predictor.mae:.3f} seconds")
        print(f"   R²:    {predictor.r2:.3f}")
        print(f"\n   Feature importances:")
        for feat, imp in predictor.get_feature_importances().items():
            bar = "█" * int(imp * 50)
            print(f"     {feat:<25s} {imp:.3f}  {bar}")
    except ValueError as e:
        print(f"\n❌ {e}")
        sys.exit(1)
