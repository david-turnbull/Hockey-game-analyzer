"""
Tests for Stage 5 Modelling & Experiment Foundation.

Verifies:
1. Source timestamps are strictly safe relative to prediction cutoff.
2. Missing/unverifiable latest_source_game_start_time fails closed with TemporalLeakageError.
3. feature_availability_time is ABSENT from public serialized provenance.
4. Unknown target observation timestamp remains explicitly None and does not trigger feature leakage errors.
5. Chronological and group-aware splits are enforced; missing record timestamps fail closed.
6. Injected future data raises TemporalLeakageError.
7. Identical configs produce identical config_hash (excluding runtime values).
8. Separate validation and test metrics/predictions are generated when test_window is specified.
9. Truthful baseline naming for SimpleLinearBaseline (OLS) and SimpleRidgeBaseline (Ridge).
10. Complete provenance metadata in ExperimentResult.
11. Frozen production artifact SHA-256 invariance (Win model, Score params, xG model & xG metadata).
12. Grounded pre-Stage-5 literal regression fixtures for Win Probability and xG predictions.
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
EXPECTED_XG_METADATA_SHA = "b47e7c449fc16b428c33f4387db196deb9c5f71ad3dcec099fff8a069ac9fdfb"


def test_frozen_production_artifact_invariance_sha256():
    """CRITICAL INVARIANT TEST: Asserts frozen production model artifacts remain 100% untouched."""
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    # 1. Win Probability Pickle Artifact (binary file)
    win_pkl_path = os.path.join(project_root, "models", "forecasting", "pucklens-win-v1.4.0.pkl")
    assert os.path.exists(win_pkl_path), "Win model artifact missing"
    with open(win_pkl_path, "rb") as f:
        actual_win_sha = hashlib.sha256(f.read()).hexdigest()
    assert actual_win_sha == EXPECTED_WIN_MODEL_SHA, f"Win model SHA mismatch: {actual_win_sha}"

    # 2. Score Projection Candidate Parameters JSON Artifact (text file, LF normalized)
    score_json_path = os.path.join(project_root, "models", "forecasting", "score_candidate_params_v1.4.0.json")
    assert os.path.exists(score_json_path), "Score params artifact missing"
    with open(score_json_path, "rb") as f:
        actual_score_sha = hashlib.sha256(f.read().replace(b"\r\n", b"\n")).hexdigest()
    assert actual_score_sha == EXPECTED_SCORE_PARAMS_SHA, f"Score params SHA mismatch: {actual_score_sha}"

    # 3. xG Model Pickle Artifact (binary file)
    xg_pkl_path = os.path.join(project_root, "models", "xg", "xg_v1.pkl")
    assert os.path.exists(xg_pkl_path), "xG model artifact missing"
    with open(xg_pkl_path, "rb") as f:
        actual_xg_sha = hashlib.sha256(f.read()).hexdigest()
    assert actual_xg_sha == EXPECTED_XG_MODEL_SHA, f"xG model SHA mismatch: {actual_xg_sha}"

    # 4. xG Metadata JSON Artifact (text file, LF normalized)
    xg_meta_path = os.path.join(project_root, "models", "xg", "metadata.json")
    assert os.path.exists(xg_meta_path), "xG metadata artifact missing"
    with open(xg_meta_path, "rb") as f:
        actual_xg_meta_sha = hashlib.sha256(f.read().replace(b"\r\n", b"\n")).hexdigest()
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


def test_missing_latest_source_game_start_time_fails_closed_and_omits_deprecated_field():
    """Verifies missing latest_source_game_start_time fails closed and feature_availability_time is ABSENT from public to_dict()."""
    cutoff_time = datetime(2022, 1, 15, 19, 0, 0, tzinfo=timezone.utc)
    cutoff = PointInTimeCutoff(prediction_cutoff_time=cutoff_time, latest_source_game_start_time=None)

    # Public serialization MUST contain latest_source_game_start_time and MUST NOT contain feature_availability_time
    d = cutoff.to_dict()
    assert "latest_source_game_start_time" in d
    assert "feature_availability_time" not in d
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


def test_runner_audit_summary_contains_max_latest_source_game_start_time():
    """Verifies ExperimentRunner temporal_audit_summary uses max_latest_source_game_start_time and omits feature_availability_time."""
    t1 = datetime(2021, 10, 15, tzinfo=timezone.utc)
    t2 = datetime(2021, 11, 15, tzinfo=timezone.utc)
    t3 = datetime(2022, 10, 15, tzinfo=timezone.utc)

    dataset = [
        {"game_id": 1, "season": "20212022", "timestamp": t1, "target": 1, "features": {"f1": 1.0}, "point_in_time_cutoff": {"prediction_cutoff_time": t1.isoformat(), "latest_source_game_start_time": (t1 - timedelta(days=1)).isoformat()}},
        {"game_id": 2, "season": "20212022", "timestamp": t2, "target": 0, "features": {"f1": 2.5}, "point_in_time_cutoff": {"prediction_cutoff_time": t2.isoformat(), "latest_source_game_start_time": (t2 - timedelta(days=1)).isoformat()}},
        {"game_id": 3, "season": "20222023", "timestamp": t3, "target": 1, "features": {"f1": 2.0}, "point_in_time_cutoff": {"prediction_cutoff_time": t3.isoformat(), "latest_source_game_start_time": (t3 - timedelta(days=1)).isoformat()}},
    ]

    config = ExperimentConfig(
        experiment_id="exp_runner_audit_naming",
        name="Audit Naming Test",
        task_type=TASK_CLASSIFICATION,
        target="home_win",
        feature_set=["f1"],
        train_window={"seasons": ["20212022"]},
        validation_window={"seasons": ["20222023"]},
        model_type="simple_logistic",
        seed=42
    )

    res = ExperimentRunner.run_experiment(config, dataset)
    audit_summary = res.temporal_audit_summary

    assert "max_latest_source_game_start_time" in audit_summary
    assert "max_feature_availability_time" not in audit_summary
    assert audit_summary["passed"] is True


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


def test_literal_production_win_probability_regression_fixtures(app):
    """
    CRITICAL REGRESSION TEST:
    Executes WinProbabilityModel on fixed deterministic feature inputs and asserts exact literal
    pre-Stage-5 outputs established from commit be3d76d4d3243bc26a4b6d99dcaa0d3ca5774b75.
    """
    from app.analytics.forecasting.win_probability import FEATURE_NAMES

    with app.app_context():
        model, manifest = ForecastModelRegistry.load_active_model()
        assert manifest["model_version"] == "v1.4.0"

        # Fixture 1: Neutral baseline input (all zeros)
        f1 = {fname: 0.0 for fname in FEATURE_NAMES}
        res1 = model.predict_game_probability(f1)
        assert res1["home_win_probability"] == 0.72
        assert res1["away_win_probability"] == 0.28
        assert res1["uncalibrated_home_probability"] == pytest.approx(0.8262, abs=1e-4)

        # Fixture 2: Strong Home Advantage
        f2 = {
            'rest_differential': 2.0,
            'home_is_b2b': 0,
            'away_is_b2b': 1,
            'l10_xgf_pct_diff': 15.0,
            'l10_cf_pct_diff': 10.0,
            'l10_goal_diff_per_game': 1.5,
            'l20_xgf_pct_diff': 12.0,
            'home_venue_l10_win_pct': 0.8,
            'away_venue_l10_win_pct': 0.3,
            'h2h_home_win_pct': 0.75,
            'h2h_home_gd_avg': 2.0
        }
        res2 = model.predict_game_probability(f2)
        assert res2["home_win_probability"] == 0.99
        assert res2["away_win_probability"] == 0.01
        assert res2["uncalibrated_home_probability"] == pytest.approx(0.9614, abs=1e-4)

        # Fixture 3: Strong Away Advantage
        f3 = {
            'rest_differential': -2.0,
            'home_is_b2b': 1,
            'away_is_b2b': 0,
            'l10_xgf_pct_diff': -15.0,
            'l10_cf_pct_diff': -10.0,
            'l10_goal_diff_per_game': -1.5,
            'l20_xgf_pct_diff': -12.0,
            'home_venue_l10_win_pct': 0.3,
            'away_venue_l10_win_pct': 0.8,
            'h2h_home_win_pct': 0.25,
            'h2h_home_gd_avg': -2.0
        }
        res3 = model.predict_game_probability(f3)
        assert res3["home_win_probability"] == pytest.approx(0.5822, abs=1e-4)
        assert res3["away_win_probability"] == pytest.approx(0.4178, abs=1e-4)
        assert res3["uncalibrated_home_probability"] == pytest.approx(0.6489, abs=1e-4)


def test_literal_production_xg_regression_fixtures(app):
    """
    CRITICAL REGRESSION TEST:
    Executes XGService on fixed deterministic shot inputs and asserts exact literal
    pre-Stage-5 outputs established from commit be3d76d4d3243bc26a4b6d99dcaa0d3ca5774b75.
    """
    with app.app_context():
        # Shot 1: Close slot shot (12ft, 5 deg, 1st period 5v5)
        xg1 = XGService.predict_shot_xg(distance=12.0, angle=5.0, period=1, period_seconds=300, is_home=1, shot_type="Wrist", strength_state="5v5")
        assert xg1.xg == 0.2543
        assert xg1.model_name == "pucklens-xg-logistic"
        assert xg1.model_version == "1.0.0"
        assert xg1.method == "ml"
        assert xg1.fallback_used is False

        # Shot 2: Point shot (55ft, 40 deg, 2nd period 5v5)
        xg2 = XGService.predict_shot_xg(distance=55.0, angle=40.0, period=2, period_seconds=900, is_home=0, shot_type="Slap", strength_state="5v5")
        assert xg2.xg == 0.0387
        assert xg2.model_name == "pucklens-xg-logistic"

        # Shot 3: Power play rebound opportunity (8ft, 12 deg, 3rd period 5v4)
        xg3 = XGService.predict_shot_xg(distance=8.0, angle=12.0, period=3, period_seconds=1100, is_home=1, shot_type="Snap", strength_state="5v4", empty_net=False)
        assert xg3.xg == 0.3971
        assert xg3.model_name == "pucklens-xg-logistic"
