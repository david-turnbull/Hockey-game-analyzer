"""
Tests for Stage 5 Modelling & Experiment Foundation.

Verifies:
1. Source timestamps are strictly safe relative to prediction cutoff.
2. Unknown/unverifiable temporal provenance fails closed with TemporalLeakageError.
3. Target labels occurring post-cutoff do not trigger leakage errors.
4. Chronological and group-aware splits are enforced.
5. Injected future data raises TemporalLeakageError.
6. Identical configs produce identical config_hash (excluding runtime values).
7. Deterministic baselines reproduce bit-for-bit identical results with fixed seeds.
8. Provenance completeness in ExperimentResult.
9. Frozen production artifacts & manifests remain 100% unchanged (verified by SHA-256).
10. Existing production prediction behavior remains completely unaffected.
"""

import os
import json
import hashlib
import pytest
from datetime import datetime, timezone, timedelta
from app.models import db, Game, Team
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
    evaluate_predictions
)
from app.analytics.experiments.runner import (
    ExperimentRunner
)
from app.analytics.forecasting.model_registry import ForecastModelRegistry

EXPECTED_WIN_MODEL_SHA = "63cf3cec7d11b38004c590503c89b0a686ae4a9a350fd497bc93087e71bf58f9"
EXPECTED_SCORE_PARAMS_SHA = "a6c6c20e7bdbe8f11a518ac8d7832ce65947ccba7ba0b2d15d6db87a5efbd701"


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


def test_point_in_time_source_timestamp_safety():
    """Verifies that source_time < cutoff passes and source_time >= cutoff raises TemporalLeakageError."""
    cutoff_time = datetime(2022, 1, 15, 19, 0, 0, tzinfo=timezone.utc)
    cutoff = PointInTimeCutoff(prediction_cutoff_time=cutoff_time)

    safe_time = datetime(2022, 1, 14, 20, 0, 0, tzinfo=timezone.utc)
    cutoff.audit_source_timestamp(safe_time, source_id="game_100")

    unsafe_time = datetime(2022, 1, 15, 19, 0, 0, tzinfo=timezone.utc)
    with pytest.raises(TemporalLeakageError, match="not strictly prior"):
        cutoff.audit_source_timestamp(unsafe_time, source_id="game_101")

    future_time = datetime(2022, 1, 16, 12, 0, 0, tzinfo=timezone.utc)
    with pytest.raises(TemporalLeakageError, match="not strictly prior"):
        cutoff.audit_source_timestamp(future_time, source_id="game_102")


def test_unverifiable_temporal_provenance_fails_closed():
    """Verifies that missing or None timestamps cause fail-closed TemporalLeakageError."""
    cutoff_time = datetime(2022, 1, 15, 19, 0, 0, tzinfo=timezone.utc)
    cutoff = PointInTimeCutoff(prediction_cutoff_time=cutoff_time)

    with pytest.raises(TemporalLeakageError, match="UNVERIFIABLE_PROVENANCE"):
        cutoff.audit_source_timestamp(None, source_id="missing_time_game")

    rec_missing = {
        "instance_id": 1,
        "features": {"f1": 1.0}
    }
    with pytest.raises(TemporalLeakageError, match="UNVERIFIABLE_PROVENANCE"):
        assert_point_in_time_safety([rec_missing])


def test_target_label_post_cutoff_allowed():
    """Verifies target observation time occurring AFTER prediction cutoff time is valid and does not raise an error."""
    cutoff_time = datetime(2022, 1, 15, 19, 0, 0, tzinfo=timezone.utc)
    target_obs_time = datetime(2022, 1, 15, 22, 30, 0, tzinfo=timezone.utc)

    cutoff = PointInTimeCutoff(
        prediction_cutoff_time=cutoff_time,
        feature_availability_time=datetime(2022, 1, 14, 23, 0, 0, tzinfo=timezone.utc),
        target_observation_time=target_obs_time,
        source_game_ids=[1001, 1002]
    )

    d = cutoff.to_dict()
    assert d["safety_passed"] is True
    assert d["prediction_cutoff_time"] == cutoff_time.isoformat()
    assert d["target_observation_time"] == target_obs_time.isoformat()


def test_chronological_and_group_aware_split_enforcement():
    """Verifies chronological ordering and group-aware non-overlapping splits."""
    t1 = datetime(2021, 10, 15, tzinfo=timezone.utc)
    t2 = datetime(2021, 11, 15, tzinfo=timezone.utc)
    t3 = datetime(2022, 10, 15, tzinfo=timezone.utc)
    t4 = datetime(2022, 11, 15, tzinfo=timezone.utc)

    records = [
        {"game_id": 1, "season": "20212022", "timestamp": t1, "target": 1, "features": {"f": 1.0}},
        {"game_id": 2, "season": "20212022", "timestamp": t2, "target": 0, "features": {"f": 2.0}},
        {"game_id": 3, "season": "20222023", "timestamp": t3, "target": 1, "features": {"f": 3.0}},
        {"game_id": 4, "season": "20222023", "timestamp": t4, "target": 0, "features": {"f": 4.0}},
    ]

    train, val, test = ChronologicalSplitter.split(
        records,
        train_window={"seasons": ["20212022"]},
        validation_window={"seasons": ["20222023"]},
        time_key="timestamp",
        group_key="game_id"
    )

    assert len(train) == 2
    assert len(val) == 2

    # Group overlap test
    train_overlap = [
        {"game_id": 100, "season": "20212022", "timestamp": t1},
    ]
    val_overlap = [
        {"game_id": 100, "season": "20222023", "timestamp": t3},
    ]

    with pytest.raises(TemporalLeakageError, match="GROUP_LEAKAGE"):
        ChronologicalSplitter.audit_split_leakage(train_overlap, val_overlap, group_key="game_id")


def test_injected_future_data_raises_temporal_leakage_error():
    """Verifies that injecting future feature data triggers TemporalLeakageError."""
    t_train = datetime(2021, 10, 15, tzinfo=timezone.utc)
    t_val = datetime(2022, 10, 15, tzinfo=timezone.utc)

    rec_future = {
        "instance_id": 99,
        "features": {"f": 1.0},
        "point_in_time_cutoff": {
            "prediction_cutoff_time": t_train.isoformat(),
            "feature_availability_time": t_val.isoformat()  # Unsafe: avail after cutoff
        }
    }

    with pytest.raises(TemporalLeakageError, match="TEMPORAL_LEAKAGE"):
        assert_point_in_time_safety([rec_future])


def test_deterministic_config_hash_invariance():
    """Verifies that identical ExperimentConfigs produce identical config_hash and exclude runtime values."""
    config1 = ExperimentConfig(
        experiment_id="exp_test_1",
        name="Test Experiment",
        task_type=TASK_CLASSIFICATION,
        target="home_win",
        feature_set=["f2", "f1"],  # Unsorted
        train_window={"seasons": ["20212022"]},
        validation_window={"seasons": ["20222023"]},
        model_type="simple_logistic",
        hyperparameters={"C": 1.0},
        seed=42
    )

    config2 = ExperimentConfig(
        experiment_id="exp_test_1",
        name="Test Experiment",
        task_type=TASK_CLASSIFICATION,
        target="home_win",
        feature_set=["f1", "f2"],  # Sorted
        train_window={"seasons": ["20212022"]},
        validation_window={"seasons": ["20222023"]},
        model_type="simple_logistic",
        hyperparameters={"C": 1.0},
        seed=42
    )

    hash1 = config1.compute_config_hash()
    hash2 = config2.compute_config_hash()

    assert hash1 == hash2
    assert len(hash1) == 64


def test_deterministic_baselines_and_reproducibility():
    """Verifies that deterministic baselines reproduce identical metric results across runs."""
    t1 = datetime(2021, 10, 15, tzinfo=timezone.utc)
    t2 = datetime(2021, 11, 15, tzinfo=timezone.utc)
    t3 = datetime(2022, 10, 15, tzinfo=timezone.utc)
    t4 = datetime(2022, 11, 15, tzinfo=timezone.utc)

    dataset = [
        {"game_id": 1, "season": "20212022", "timestamp": t1, "target": 1, "features": {"f1": 1.0, "f2": 2.0}, "point_in_time_cutoff": {"prediction_cutoff_time": t1.isoformat(), "feature_availability_time": (t1 - timedelta(days=1)).isoformat()}},
        {"game_id": 2, "season": "20212022", "timestamp": t2, "target": 0, "features": {"f1": 2.0, "f2": 1.0}, "point_in_time_cutoff": {"prediction_cutoff_time": t2.isoformat(), "feature_availability_time": (t2 - timedelta(days=1)).isoformat()}},
        {"game_id": 3, "season": "20222023", "timestamp": t3, "target": 1, "features": {"f1": 1.5, "f2": 1.8}, "point_in_time_cutoff": {"prediction_cutoff_time": t3.isoformat(), "feature_availability_time": (t3 - timedelta(days=1)).isoformat()}},
        {"game_id": 4, "season": "20222023", "timestamp": t4, "target": 0, "features": {"f1": 2.5, "f2": 0.9}, "point_in_time_cutoff": {"prediction_cutoff_time": t4.isoformat(), "feature_availability_time": (t4 - timedelta(days=1)).isoformat()}},
    ]

    config = ExperimentConfig(
        experiment_id="exp_repro_test",
        name="Reproducibility Test",
        task_type=TASK_CLASSIFICATION,
        target="home_win",
        feature_set=["f1", "f2"],
        train_window={"seasons": ["20212022"]},
        validation_window={"seasons": ["20222023"]},
        model_type="simple_logistic",
        hyperparameters={"C": 1.0},
        seed=42
    )

    res1 = ExperimentRunner.run_experiment(config, dataset)
    res2 = ExperimentRunner.run_experiment(config, dataset)

    assert res1.config_hash == res2.config_hash
    assert res1.metrics == res2.metrics
    assert res1.provenance["git_commit_sha"] == res2.provenance["git_commit_sha"]


def test_provenance_completeness():
    """Verifies that ExperimentResult contains all required provenance metadata fields."""
    config = ExperimentConfig(
        experiment_id="exp_prov_test",
        name="Provenance Test",
        task_type=TASK_REGRESSION,
        target="total_goals",
        feature_set=["f1"],
        train_window={"seasons": ["20212022"]},
        validation_window={"seasons": ["20222023"]},
        model_type="simple_linear",
        hyperparameters={"alpha": 1.0},
        seed=42
    )

    t1 = datetime(2021, 10, 15, tzinfo=timezone.utc)
    t2 = datetime(2022, 10, 15, tzinfo=timezone.utc)

    dataset = [
        {"game_id": 1, "season": "20212022", "timestamp": t1, "target": 6.0, "features": {"f1": 3.0}, "point_in_time_cutoff": {"prediction_cutoff_time": t1.isoformat(), "feature_availability_time": (t1 - timedelta(days=1)).isoformat()}},
        {"game_id": 2, "season": "20222023", "timestamp": t2, "target": 5.0, "features": {"f1": 2.5}, "point_in_time_cutoff": {"prediction_cutoff_time": t2.isoformat(), "feature_availability_time": (t2 - timedelta(days=1)).isoformat()}},
    ]

    res = ExperimentRunner.run_experiment(config, dataset)
    d = res.to_dict()

    assert "config_hash" in d
    assert "provenance" in d
    assert "git_commit_sha" in d["provenance"]
    assert "python_version" in d["provenance"]
    assert "library_versions" in d["provenance"]
    assert "scikit_learn" in d["provenance"]["library_versions"]
    assert "temporal_audit_summary" in d
    assert d["temporal_audit_summary"]["passed"] is True


def test_existing_production_forecasting_pipeline_unaffected(app):
    """Verifies that loading active production model via ForecastModelRegistry remains 100% operational."""
    with app.app_context():
        model, manifest = ForecastModelRegistry.load_active_model()
        assert model is not None
        assert manifest["model_version"] == "v1.4.0"
        assert manifest["artifact_sha256"] == EXPECTED_WIN_MODEL_SHA
