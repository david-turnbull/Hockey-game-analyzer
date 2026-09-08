import pytest
from app.analytics.model_registry import ModelRegistry
from app.analytics.out_of_time_validation import OutOfTimeValidator

def test_out_of_time_evaluator_invariance():
    """
    Ensure the out-of-time evaluator:
    1. Loads the serialized production model unchanged.
    2. Does NOT call model training or fitting.
    3. Produces deterministic evaluations on fixed fixtures.
    """
    validator = OutOfTimeValidator(season="20242025")

    # 1. Verify model is loaded from registry
    assert validator.model is not None
    assert validator.model.is_fitted is True
    assert validator.model_name == "pucklens-xg-logistic"

    # Ensure pipeline is fitted and has classifier
    assert hasattr(validator.model, 'pipeline')
    assert validator.model.pipeline is not None

    # 2. Fixed synthetic fixture shots
    synthetic_shots = [
        {
            "shot_id": "test_shot_1",
            "distance": 10.0,
            "angle": 5.0,
            "period": 1,
            "period_seconds": 120,
            "score_differential": 0,
            "is_home": 1,
            "empty_net": 0,
            "time_since_prev_event": 2.0,
            "distance_from_prev_event": 5.0,
            "angle_change": 0.0,
            "is_rebound": 1,
            "is_rush": 0,
            "is_turnover": 0,
            "is_after_faceoff": 0,
            "is_lateral_movement": 1,
            "is_power_play": 0,
            "is_shorthanded": 0,
            "coordinates_missing": 0,
            "shot_type": "wrist",
            "strength_state": "EV",
            "prev_event_type": "shot-on-goal",
            "goal": 1,
            "game_id": 2024020001,
            "game_date": "2024-10-10",
            "team_abbrev": "CGY"
        },
        {
            "shot_id": "test_shot_2",
            "distance": 55.0,
            "angle": 45.0,
            "period": 2,
            "period_seconds": 450,
            "score_differential": 1,
            "is_home": 0,
            "empty_net": 0,
            "time_since_prev_event": 10.0,
            "distance_from_prev_event": 40.0,
            "angle_change": 15.0,
            "is_rebound": 0,
            "is_rush": 0,
            "is_turnover": 0,
            "is_after_faceoff": 0,
            "is_lateral_movement": 0,
            "is_power_play": 0,
            "is_shorthanded": 0,
            "coordinates_missing": 0,
            "shot_type": "slap",
            "strength_state": "EV",
            "prev_event_type": "blocked-shot",
            "goal": 0,
            "game_id": 2024020002,
            "game_date": "2024-10-12",
            "team_abbrev": "EDM"
        }
    ]

    report = validator.evaluate(synthetic_shots)

    # 3. Deterministic structure checks
    assert report["evaluation_season"] == "20242025"
    assert report["metrics"]["shot_count"] == 2
    assert report["metrics"]["goal_count"] == 1
    assert "log_loss" in report["metrics"]
    assert "brier_score" in report["metrics"]
    assert "roc_auc" in report["metrics"]
    assert report["metrics"]["predicted_xg"] > 0.0

    # Closer danger shot must have higher xG than long distance slap shot
    pred1 = validator.model.predict(synthetic_shots[0])
    pred2 = validator.model.predict(synthetic_shots[1])
    assert pred1 > pred2

    # Verify decision is one of the valid states
    valid_decisions = [
        "healthy",
        "healthy_on_available_sample",
        "minor calibration drift",
        "meaningful drift",
        "model redevelopment recommended"
    ]
    assert report["model_decision"]["verdict"] in valid_decisions

    # Markdown generation check
    md = validator.generate_markdown(report)
    assert "# Out-of-Time xG Validation Report" in md
    assert "Core Probabilistic Evaluation Metrics" in md


def test_evaluator_rejects_missing_game_provenance():
    """Verify that OutOfTimeValidator rejects shots data without authentic game_id provenance (no fabricated fallbacks)."""
    validator = OutOfTimeValidator(season="20242025")
    shots_without_game_id = [
        {
            "shot_id": "shot_no_game",
            "distance": 15.0,
            "angle": 10.0,
            "goal": 0,
            "game_date": "2024-10-10"
        }
    ]
    with pytest.raises(ValueError, match="Cannot determine game provenance"):
        validator.evaluate(shots_without_game_id)


def test_evaluator_rejects_missing_game_dates():
    """Verify that OutOfTimeValidator rejects shots data without authentic game_date provenance."""
    validator = OutOfTimeValidator(season="20242025")
    shots_without_date = [
        {
            "shot_id": "shot_no_date",
            "distance": 15.0,
            "angle": 10.0,
            "goal": 0,
            "game_id": 2024020001
        }
    ]
    with pytest.raises(ValueError, match="Cannot determine game dates provenance"):
        validator.evaluate(shots_without_date)


def test_model_hashes_recorded_and_persisted():
    """Verify that OutOfTimeValidator records expected, pre-validation, and post-validation model SHA-256 hashes."""
    validator = OutOfTimeValidator(season="20242025")
    shots = [
        {
            "shot_id": "s1",
            "game_id": 2024020001,
            "game_date": "2024-10-10",
            "distance": 20.0,
            "angle": 15.0,
            "goal": 0
        }
    ]
    report = validator.evaluate(shots)
    m = report["model"]
    expected_hash = "c7f4f55bb0136f5d1774267446f5bd07a9a0bad2285238a25f551a61b0927635"
    assert m["expected_sha256"] == expected_hash
    assert m["pre_validation_sha256"] == expected_hash
    assert m["post_validation_sha256"] == expected_hash
    assert m["sha256"] == expected_hash
    assert m["invariance_verified"] is True

    # Check markdown attestation
    md = OutOfTimeValidator.generate_markdown(report)
    assert f"- **Expected SHA-256**: `{expected_hash}`" in md
    assert f"- **Pre-Validation SHA-256**: `{expected_hash}`" in md
    assert f"- **Post-Validation SHA-256**: `{expected_hash}`" in md
    assert "- **Invariance Status**: **PASS**" in md
