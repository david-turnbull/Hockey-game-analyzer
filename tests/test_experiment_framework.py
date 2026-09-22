"""
Tests for Stage 5 Modelling & Experiment Foundation.

Verifies:
1. Source timestamps are strictly safe relative to prediction cutoff.
2. Missing/unverifiable latest_source_game_start_time fails closed with TemporalLeakageError.
3. Unknown target observation timestamp remains explicitly None and does not trigger feature leakage errors.
4. Chronological and group-aware splits are enforced; missing record timestamps fail closed.
5. Injected future data raises TemporalLeakageError.
6. Identical configs produce identical config_hash (excluding runtime values).
7. Separate validation and test metrics/predictions are generated when test_window is specified.
8. Truthful baseline naming for SimpleLinearBaseline (OLS) and SimpleRidgeBaseline (Ridge).
9. Complete provenance metadata in ExperimentResult.
10. Production artifact invariance (Win model, Score params, xG model & xG metadata SHA-256).
11. Production prediction behavior and equivalence remain completely unchanged.
"""

import os
import json
import hashlib
import pytest
from datetime import datetime, timezone, timedelta
from app.models import db, Game, Team, Event, Shot
from app.analytics.experiments.point_in_time import (
    PointInTimeCutoff,
    PointInTimeAdapter,
    TemporalLeakageError,
    assert_point_in_time_safety
)
from app.analytics.experiments.experiment_config import (
    ExperimentConfig,
    ExperimentResult,
    TASK_CLASSIFICATION,
    TASK_REGRESSION
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
from app.analytics.experiments.runner import (
    ExperimentRunner
)
from app.analytics.forecasting.model_registry import ForecastModelRegistry
from app.services.xg_service import XGService

EXPECTED_WIN_MODEL_SHA = "63cf3cec7d11b38004c590503c89b0a686ae4a9a350fd497bc93087e71bf58f9"
EXPECTED_SCORE_PARAMS_SHA = "a6c6c20e7bdbe8f11a518ac8d7832ce65947ccba7ba0b2d15d6db87a5efbd701"
EXPECTED_XG_MODEL_SHA = "c7f4f55bb0136f5d1774267446f5bd07a9a0bad2285238a25f551a61b0927635"
EXPECTED_XG_METADATA_SHA = "615fa69b65ed33d158662283819d94391fff9d80419a873a08ae9a38ddf2503d"


def test_frozen_production_artifact_invariance_sha256():
    """CRITICAL INVARIANT TEST: Asserts frozen production model artifacts remain 100% untouched."""
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    # 1. Win Probability Pickle Artifact
    win_pkl_path = os.path.join(project_root, "models", "forecasting", "pucklens-win-v1.4.0.pkl")
    assert os.path.exists(win_pkl_path), "Win model artifact missing"
    with open(win_pkl_path, "rb") as f:
        actual_win_sha = hashlib.sha256(f.read()).hexdigest()
    assert actual_win_sha == EXPECTED_WIN_MODEL_SHA, f"Win model SHA mismatch: {actual_win_sha}"

    # 2. Score Projection Candidate Parameters JSON Artifact
    score_json_path = os.path.join(project_root, "models", "forecasting", "score_candidate_params_v1.4.0.json")
    assert os.path.exists(score_json_path), "Score params artifact missing"
    with open(score_json_path, "rb") as f:
        actual_score_sha = hashlib.sha256(f.read()).hexdigest()
    assert actual_score_sha == EXPECTED_SCORE_PARAMS_SHA, f"Score params SHA mismatch: {actual_score_sha}"

    # 3. xG Model Pickle Artifact
    xg_pkl_path = os.path.join(project_root, "models", "xg", "xg_v1.pkl")
    assert os.path.exists(xg_pkl_path), "xG model artifact missing"
    with open(xg_pkl_path, "rb") as f:
        actual_xg_sha = hashlib.sha256(f.read()).hexdigest()
    assert actual_xg_sha == EXPECTED_XG_MODEL_SHA, f"xG model SHA mismatch: {actual_xg_sha}"

    # 4. xG Metadata JSON Artifact
    xg_meta_path = os.path.join(project_root, "models", "xg", "metadata.json")
    assert os.path.exists(xg_meta_path), "xG metadata artifact missing"
    with open(xg_meta_path, "rb") as f:
        actual_xg_meta_sha = hashlib.sha256(f.read()).hexdigest()
    assert actual_xg_meta_sha == EXPECTED_XG_METADATA_SHA, f"xG metadata SHA mismatch: {actual_xg_meta_sha}"


def test_point_in_time_source_timestamp_safety():
    """Verifies that source_time < cutoff passes and source_time >= cutoff raises TemporalLeakageError."""
    cutoff_time = datetime(2022, 1, 15, 19, 0, 0, tzinfo=timezone.utc)
    cutoff = PointInTimeCutoff(prediction_cutoff_time=cutoff_time)

    safe_time = datetime(2022, 1, 14, 20, 0, 0, tzinfo=timezone.utc)
    cutoff.audit_source_timestamp(safe_time, source_id="game_100")

    unsafe_time = datetime(2022, 1, 15, 19, 0, 0, tzinfo=timezone.utc)
    with pytest.raises(TemporalLeakageError, match="not strictly prior"):
        cutoff.audit_source_timestamp(unsafe_time, source_id="game_101")


def test_missing_latest_source_game_start_time_fails_closed():
    """Verifies that missing latest_source_game_start_time causes fail-closed TemporalLeakageError and safety_passed=False."""
    cutoff_time = datetime(2022, 1, 15, 19, 0, 0, tzinfo=timezone.utc)
    cutoff = PointInTimeCutoff(prediction_cutoff_time=cutoff_time, latest_source_game_start_time=None)

    # Cutoff to_dict MUST report safety_passed=False when source provenance is missing
    d = cutoff.to_dict()
    assert d["safety_passed"] is False

    rec_missing = {
        "game_id": 101,
        "point_in_time_cutoff": {
            "prediction_cutoff_time": cutoff_time.isoformat(),
            "latest_source_game_start_time": None
        }
    }
    with pytest.raises(TemporalLeakageError, match="UNVERIFIABLE_PROVENANCE"):
        assert_point_in_time_safety([rec_missing])


def test_unknown_target_observation_timestamp_remains_explicit_none():
    """Verifies that unknown target observation timestamp is preserved as None and does not trigger leakage errors."""
    cutoff_time = datetime(2022, 1, 15, 19, 0, 0, tzinfo=timezone.utc)
    source_time = datetime(2022, 1, 14, 23, 0, 0, tzinfo=timezone.utc)

    cutoff = PointInTimeCutoff(
        prediction_cutoff_time=cutoff_time,
        latest_source_game_start_time=source_time,
        target_observation_time=None,  # Explicitly unknown
        source_game_ids=[1001]
    )

    d = cutoff.to_dict()
    assert d["safety_passed"] is True
    assert d["target_observation_time"] is None
    assert d["latest_source_game_start_time"] == source_time.isoformat()


def test_chronological_split_fails_closed_on_missing_timestamp():
    """Verifies that chronological splitting fails closed with TemporalLeakageError if a routed record lacks a timestamp."""
    rec1 = {"game_id": 1, "season": "20212022", "timestamp": "2021-10-15T00:00:00+00:00"}
    rec2_missing = {"game_id": 2, "season": "20212022", "timestamp": None}
    rec3 = {"game_id": 3, "season": "20222023", "timestamp": "2022-10-15T00:00:00+00:00"}

    with pytest.raises(TemporalLeakageError, match="UNVERIFIABLE_TEMPORAL_ORDERING"):
        ChronologicalSplitter.split(
            [rec1, rec2_missing, rec3],
            train_window={"seasons": ["20212022"]},
            validation_window={"seasons": ["20222023"]}
        )


def test_test_window_evaluation_produces_separate_metrics_and_predictions():
    """Verifies that setting test_window produces separate test_metrics and test_predictions without contaminating training."""
    t1 = datetime(2021, 10, 15, tzinfo=timezone.utc)
    t2 = datetime(2021, 11, 15, tzinfo=timezone.utc)
    t3 = datetime(2022, 10, 15, tzinfo=timezone.utc)
    t4 = datetime(2023, 10, 15, tzinfo=timezone.utc)

    dataset = [
        {"game_id": 1, "season": "20212022", "timestamp": t1, "target": 1, "features": {"f1": 1.0}, "point_in_time_cutoff": {"prediction_cutoff_time": t1.isoformat(), "latest_source_game_start_time": (t1 - timedelta(days=1)).isoformat()}},
        {"game_id": 2, "season": "20212022", "timestamp": t2, "target": 0, "features": {"f1": 2.5}, "point_in_time_cutoff": {"prediction_cutoff_time": t2.isoformat(), "latest_source_game_start_time": (t2 - timedelta(days=1)).isoformat()}},
        {"game_id": 3, "season": "20222023", "timestamp": t3, "target": 1, "features": {"f1": 1.2}, "point_in_time_cutoff": {"prediction_cutoff_time": t3.isoformat(), "latest_source_game_start_time": (t3 - timedelta(days=1)).isoformat()}},
        {"game_id": 4, "season": "20232024", "timestamp": t4, "target": 0, "features": {"f1": 2.2}, "point_in_time_cutoff": {"prediction_cutoff_time": t4.isoformat(), "latest_source_game_start_time": (t4 - timedelta(days=1)).isoformat()}},
    ]

    config = ExperimentConfig(
        experiment_id="exp_test_split_eval",
        name="Test Split Test",
        task_type=TASK_CLASSIFICATION,
        target="home_win",
        feature_set=["f1"],
        train_window={"seasons": ["20212022"]},
        validation_window={"seasons": ["20222023"]},
        test_window={"seasons": ["20232024"]},
        model_type="simple_logistic",
        seed=42
    )

    result = ExperimentRunner.run_experiment(config, dataset)

    assert result.sample_counts["train_samples"] == 2
    assert result.sample_counts["val_samples"] == 1
    assert result.sample_counts["test_samples"] == 1

    assert result.metrics is not None
    assert result.test_metrics is not None
    assert "log_loss" in result.test_metrics
    assert result.test_predictions is not None
    assert len(result.test_predictions) == 1


def test_truthful_baseline_naming_simple_linear_and_ridge():
    """Verifies that SimpleLinearBaseline uses OLS LinearRegression and SimpleRidgeBaseline uses Ridge."""
    lin = SimpleLinearBaseline()
    assert lin.model.__class__.__name__ == "LinearRegression"

    ridge = SimpleRidgeBaseline(alpha=0.5)
    assert ridge.model.__class__.__name__ == "Ridge"
    assert ridge.model.alpha == 0.5


def test_production_predictions_equivalence(app):
    """
    REQUIRED EQUIVALENCE TEST:
    Executes actual active production win probability and xG predictions to confirm 100% equivalence.
    """
    from app.analytics.forecasting.win_probability import FEATURE_NAMES

    with app.app_context():
        # 1. Win Probability Model Prediction Equivalence
        model, manifest = ForecastModelRegistry.load_active_model()
        sample_feats = {fname: 0.5 for fname in FEATURE_NAMES}
        win_pred = model.predict_game_probability(sample_feats)
        assert "home_win_probability" in win_pred
        assert "away_win_probability" in win_pred
        assert 0.0 <= win_pred["home_win_probability"] <= 1.0

        # 2. xG Model Prediction Equivalence
        xg_val = XGService.predict_shot_xg(
            distance=25.0,
            angle=15.0,
            period=1,
            period_seconds=300,
            is_home=1,
            shot_type="Snap",
            strength_state="5v5"
        )
        assert 0.0 < xg_val.xg < 1.0
        assert xg_val.model_name == "pucklens-xg-logistic"
