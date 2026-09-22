"""
Standardized Experiment Runner and Pipeline Executor.

Executes:
1. Configuration parsing & deterministic SHA-256 config hashing.
2. Dataset loading & PointInTimeAdapter temporal audit (fail-closed).
3. Chronological group-aware splitting.
4. Model fitting on training split & evaluation on validation and optional test splits.
5. Task metric computation (classification or regression).
6. Complete provenance packaging.
"""

import sys
import subprocess
import logging
import numpy as np
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional

import sklearn

from app.analytics.experiments.experiment_config import (
    ExperimentConfig,
    ExperimentResult,
    TASK_CLASSIFICATION,
    TASK_REGRESSION
)
from app.analytics.experiments.point_in_time import (
    PointInTimeAdapter,
    assert_point_in_time_safety,
    TemporalLeakageError
)
from app.analytics.experiments.chronological_splitter import (
    ChronologicalSplitter
)
from app.analytics.experiments.baselines import (
    HistoricalMeanBaseline,
    TrailingNMeanBaseline,
    SimpleLogisticBaseline,
    SimpleLinearBaseline,
    SimpleRidgeBaseline,
    evaluate_predictions
)

logger = logging.getLogger(__name__)


class ExperimentRunner:
    """
    Pipeline runner for PuckLens Stage 5 modelling experiments.
    """

    @classmethod
    def get_git_commit_sha(cls) -> str:
        """Retrieves active Git commit SHA or fallback string."""
        try:
            sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
            return sha
        except Exception:
            return "unknown_git_sha"

    @classmethod
    def run_experiment(
        cls,
        config: ExperimentConfig,
        dataset: List[Dict[str, Any]]
    ) -> ExperimentResult:
        """
        Runs a complete experiment pipeline using provided config and dataset.

        Args:
            config: ExperimentConfig specification
            dataset: List of dataset record dicts containing features, target, timestamp, point_in_time_cutoff
        """
        # 1. Deterministic Config Hash
        config_hash = config.compute_config_hash()
        logger.info(f"Executing experiment '{config.experiment_id}' (Config Hash: {config_hash[:8]}...)")

        # 2. Point-in-Time Temporal Audit (Fail-Closed)
        assert_point_in_time_safety(dataset)

        max_source_time = None
        for rec in dataset:
            cutoff_meta = rec.get("point_in_time_cutoff", {})
            source_str = (
                cutoff_meta.get("latest_source_game_start_time") or
                cutoff_meta.get("feature_availability_time")
            )
            if source_str:
                dt = datetime.fromisoformat(source_str)
                if max_source_time is None or dt > max_source_time:
                    max_source_time = dt

        temporal_audit_summary = {
            "passed": True,
            "records_checked": len(dataset),
            "max_latest_source_game_start_time": max_source_time.isoformat() if max_source_time else None,
            "max_feature_availability_time": max_source_time.isoformat() if max_source_time else None
        }

        # 3. Chronological and Group-Aware Splitting
        train_recs, val_recs, test_recs = ChronologicalSplitter.split(
            records=dataset,
            train_window=config.train_window,
            validation_window=config.validation_window,
            test_window=config.test_window,
            time_key="timestamp",
            group_key="game_id"
        )

        sample_counts = {
            "train_samples": len(train_recs),
            "val_samples": len(val_recs),
            "test_samples": len(test_recs) if test_recs else 0
        }

        if len(train_recs) == 0:
            raise ValueError(f"Train split is empty for experiment '{config.experiment_id}'. Check train_window criteria.")

        if len(val_recs) == 0:
            raise ValueError(f"Validation split is empty for experiment '{config.experiment_id}'. Check validation_window criteria.")

        # 4. Extract Feature Matrices & Targets
        X_train = np.array([[r["features"][f] for f in config.feature_set] for r in train_recs], dtype=np.float64)
        y_train = np.array([r["target"] for r in train_recs], dtype=np.float64)

        X_val = np.array([[r["features"][f] for f in config.feature_set] for r in val_recs], dtype=np.float64)
        y_val = np.array([r["target"] for r in val_recs], dtype=np.float64)

        X_test = np.array([[r["features"][f] for f in config.feature_set] for r in test_recs], dtype=np.float64) if test_recs else None
        y_test = np.array([r["target"] for r in test_recs], dtype=np.float64) if test_recs else None

        # 5. Model Instantiation & Training (Strictly on Train Split)
        model_type = config.model_type.lower()
        seed = config.seed
        task_type = config.task_type

        if model_type == "historical_mean":
            model = HistoricalMeanBaseline(task_type=task_type)
            model.fit(X_train, y_train)
            if task_type == TASK_CLASSIFICATION:
                y_pred_val = model.predict_proba(X_val)[:, 1]
                y_pred_test = model.predict_proba(X_test)[:, 1] if X_test is not None else None
            else:
                y_pred_val = model.predict(X_val)
                y_pred_test = model.predict(X_test) if X_test is not None else None

        elif model_type == "trailing_n_mean":
            n_games = config.hyperparameters.get("n_games", 5)
            model = TrailingNMeanBaseline(n_games=n_games, task_type=task_type)
            model.fit(X_train, y_train)
            y_hist = list(y_train)
            if task_type == TASK_CLASSIFICATION:
                y_pred_val = model.predict_proba(X_val, y_history=y_hist)[:, 1]
                y_pred_test = model.predict_proba(X_test, y_history=list(y_val))[:, 1] if X_test is not None else None
            else:
                y_pred_val = model.predict(X_val, y_history=y_hist)
                y_pred_test = model.predict(X_test, y_history=list(y_val)) if X_test is not None else None

        elif model_type == "simple_logistic":
            if task_type != TASK_CLASSIFICATION:
                raise ValueError("simple_logistic model_type requires task_type='classification'")
            C = config.hyperparameters.get("C", 1.0)
            model = SimpleLogisticBaseline(seed=seed, C=C)
            model.fit(X_train, y_train)
            y_pred_val = model.predict_proba(X_val)[:, 1]
            y_pred_test = model.predict_proba(X_test)[:, 1] if X_test is not None else None

        elif model_type == "simple_linear":
            if task_type != TASK_REGRESSION:
                raise ValueError("simple_linear model_type requires task_type='regression'")
            model = SimpleLinearBaseline()
            model.fit(X_train, y_train)
            y_pred_val = model.predict(X_val)
            y_pred_test = model.predict(X_test) if X_test is not None else None

        elif model_type == "simple_ridge":
            if task_type != TASK_REGRESSION:
                raise ValueError("simple_ridge model_type requires task_type='regression'")
            alpha = config.hyperparameters.get("alpha", 1.0)
            model = SimpleRidgeBaseline(seed=seed, alpha=alpha)
            model.fit(X_train, y_train)
            y_pred_val = model.predict(X_val)
            y_pred_test = model.predict(X_test) if X_test is not None else None

        else:
            raise ValueError(f"Unsupported model_type '{config.model_type}'.")

        # 6. Evaluation Metrics (Validation & Optional Test)
        val_metrics = evaluate_predictions(y_val, y_pred_val, task_type=task_type)
        test_metrics = evaluate_predictions(y_test, y_pred_test, task_type=task_type) if (y_test is not None and y_pred_test is not None) else None

        # 7. Complete Provenance Assembly
        git_sha = cls.get_git_commit_sha()
        provenance = {
            "git_commit_sha": git_sha,
            "config_hash": config_hash,
            "task_type": task_type,
            "feature_version": config.feature_version,
            "executed_at": datetime.now(timezone.utc).isoformat(),
            "python_version": sys.version,
            "library_versions": {
                "scikit_learn": sklearn.__version__,
                "numpy": np.__version__
            },
            "seed": seed
        }

        # Format predictions summary
        val_preds_list = []
        for r, p in zip(val_recs, y_pred_val):
            val_preds_list.append({
                "game_id": r.get("game_id"),
                "target": r.get("target"),
                "prediction": round(float(p), 4)
            })

        test_preds_list = None
        if test_recs and y_pred_test is not None:
            test_preds_list = []
            for r, p in zip(test_recs, y_pred_test):
                test_preds_list.append({
                    "game_id": r.get("game_id"),
                    "target": r.get("target"),
                    "prediction": round(float(p), 4)
                })

        return ExperimentResult(
            experiment_id=config.experiment_id,
            config_hash=config_hash,
            task_type=task_type,
            config=config,
            metrics=val_metrics,
            test_metrics=test_metrics,
            sample_counts=sample_counts,
            temporal_audit_summary=temporal_audit_summary,
            provenance=provenance,
            predictions=val_preds_list,
            test_predictions=test_preds_list
        )
