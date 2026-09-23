"""
Task-Aware Baseline Models and Evaluation Metrics.

Provides simple, transparent baselines for framework validation:
- HistoricalMeanBaseline
- TrailingNMeanBaseline
- SimpleLogisticBaseline (classification)
- SimpleLinearBaseline (regression OLS)
- SimpleRidgeBaseline (regression Ridge)

Metrics depend strictly on task_type:
- Classification: Log Loss, Brier Score, Accuracy
- Regression: MAE, RMSE, R²
"""

import math
import numpy as np
from typing import Dict, List, Any, Union, Optional
from app.analytics.experiments.experiment_config import TASK_CLASSIFICATION, TASK_REGRESSION


class HistoricalMeanBaseline:
    """Predicts historical mean target from training data."""

    def __init__(self, task_type: str = TASK_CLASSIFICATION):
        self.task_type = task_type
        self.mean_val: float = 0.5 if task_type == TASK_CLASSIFICATION else 0.0

    def fit(self, X: Any, y: Union[List[float], np.ndarray]) -> "HistoricalMeanBaseline":
        arr = np.array(y, dtype=np.float64)
        if len(arr) > 0:
            self.mean_val = float(np.mean(arr))
            if self.task_type == TASK_CLASSIFICATION:
                self.mean_val = np.clip(self.mean_val, 1e-15, 1.0 - 1e-15)
        return self

    def predict(self, X: Any) -> np.ndarray:
        n = len(X) if hasattr(X, '__len__') else 1
        return np.full(n, self.mean_val, dtype=np.float64)

    def predict_proba(self, X: Any) -> np.ndarray:
        n = len(X) if hasattr(X, '__len__') else 1
        p = np.clip(self.mean_val, 1e-15, 1.0 - 1e-15)
        return np.column_stack([1.0 - p, p])


class TrailingNMeanBaseline:
    """Predicts trailing N-game moving average of target."""

    def __init__(self, n_games: int = 5, task_type: str = TASK_CLASSIFICATION):
        self.n_games = n_games
        self.task_type = task_type
        self.global_mean: float = 0.5 if task_type == TASK_CLASSIFICATION else 0.0

    def fit(self, X: Any, y: Union[List[float], np.ndarray]) -> "TrailingNMeanBaseline":
        arr = np.array(y, dtype=np.float64)
        if len(arr) > 0:
            self.global_mean = float(np.mean(arr))
            if self.task_type == TASK_CLASSIFICATION:
                self.global_mean = np.clip(self.global_mean, 1e-15, 1.0 - 1e-15)
        return self

    def predict(self, X: Any, y_history: Optional[List[float]] = None) -> np.ndarray:
        n = len(X) if hasattr(X, '__len__') else 1
        if y_history and len(y_history) > 0:
            trailing = y_history[-self.n_games:]
            pred_val = float(np.mean(trailing))
            if self.task_type == TASK_CLASSIFICATION:
                pred_val = np.clip(pred_val, 1e-15, 1.0 - 1e-15)
        else:
            pred_val = self.global_mean
        return np.full(n, pred_val, dtype=np.float64)

    def predict_proba(self, X: Any, y_history: Optional[List[float]] = None) -> np.ndarray:
        preds = self.predict(X, y_history=y_history)
        preds = np.clip(preds, 1e-15, 1.0 - 1e-15)
        return np.column_stack([1.0 - preds, preds])


class SimpleLogisticBaseline:
    """Wrapper for scikit-learn LogisticRegression baseline."""

    def __init__(self, seed: int = 42, C: float = 1.0):
        from sklearn.linear_model import LogisticRegression
        self.model = LogisticRegression(random_state=seed, C=C, max_iter=1000)

    def fit(self, X: np.ndarray, y: np.ndarray) -> "SimpleLogisticBaseline":
        self.model.fit(X, y)
        return self

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        return self.model.predict_proba(X)

    def predict(self, X: np.ndarray) -> np.ndarray:
        return self.model.predict(X)


class SimpleLinearBaseline:
    """Wrapper for scikit-learn LinearRegression (OLS) baseline."""

    def __init__(self):
        from sklearn.linear_model import LinearRegression
        self.model = LinearRegression()

    def fit(self, X: np.ndarray, y: np.ndarray) -> "SimpleLinearBaseline":
        self.model.fit(X, y)
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        return self.model.predict(X)


class SimpleRidgeBaseline:
    """Wrapper for scikit-learn Ridge regression baseline."""

    def __init__(self, seed: int = 42, alpha: float = 1.0):
        from sklearn.linear_model import Ridge
        self.model = Ridge(random_state=seed, alpha=alpha)

    def fit(self, X: np.ndarray, y: np.ndarray) -> "SimpleRidgeBaseline":
        self.model.fit(X, y)
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        return self.model.predict(X)


def evaluate_predictions(
    y_true: Union[List[float], np.ndarray],
    y_pred: Union[List[float], np.ndarray],
    task_type: str = TASK_CLASSIFICATION
) -> Dict[str, float]:
    """
    Computes task-specific metrics.

    Classification: Log Loss, Brier Score, Accuracy.
    Regression: MAE, RMSE, R².
    """
    yt = np.array(y_true, dtype=np.float64)
    yp = np.array(y_pred, dtype=np.float64)

    if len(yt) == 0 or len(yp) == 0:
        if task_type == TASK_CLASSIFICATION:
            return {"log_loss": 0.0, "brier_score": 0.0, "accuracy": 0.0}
        else:
            return {"mae": 0.0, "rmse": 0.0, "r2": 0.0}

    if task_type == TASK_CLASSIFICATION:
        eps = 1e-15
        yp_clip = np.clip(yp, eps, 1.0 - eps)
        
        # Log Loss
        log_loss = -float(np.mean(yt * np.log(yp_clip) + (1.0 - yt) * np.log(1.0 - yp_clip)))
        
        # Brier Score
        brier = float(np.mean((yp_clip - yt) ** 2))
        
        # Accuracy
        acc = float(np.mean((yp_clip >= 0.5).astype(int) == yt.astype(int)))

        return {
            "log_loss": round(log_loss, 4),
            "brier_score": round(brier, 4),
            "accuracy": round(acc, 4)
        }
    else:
        # MAE
        mae = float(np.mean(np.abs(yp - yt)))
        
        # RMSE
        rmse = float(np.sqrt(np.mean((yp - yt) ** 2)))
        
        # R²
        ss_res = np.sum((yt - yp) ** 2)
        ss_tot = np.sum((yt - np.mean(yt)) ** 2)
        r2 = float(1.0 - (ss_res / ss_tot)) if ss_tot > 0 else 0.0

        return {
            "mae": round(mae, 4),
            "rmse": round(rmse, 4),
            "r2": round(r2, 4)
        }
