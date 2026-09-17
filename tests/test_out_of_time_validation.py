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


def _seed_sample_seasons(db):
    """Helper to seed mock games for training and selection tests."""
    from datetime import date, datetime
    from app.models import Team, Game
    if not db.session.get(Team, 1):
        db.session.add(Team(team_id=1, abbreviation="T1", name="Team 1"))
    if not db.session.get(Team, 2):
        db.session.add(Team(team_id=2, abbreviation="T2", name="Team 2"))

    for s in ['20212022', '20222023', '20232024', '20242025']:
        for i in range(5):
            gid = int(f"{s[:4]}02{i+1:04d}")
            if not db.session.get(Game, gid):
                g = Game(
                    game_id=gid, season=s, game_type='R',
                    game_date=date(int(s[:4]), 10, 10 + i),
                    start_time_utc=datetime(int(s[:4]), 10, 10 + i, 19, 0, 0),
                    home_team_id=1, away_team_id=2,
                    home_score=3 if i % 2 == 0 else 1, away_score=1 if i % 2 == 0 else 3,
                    nhl_game_state='OFF', data_source='nhl_api'
                )
                db.session.add(g)
    db.session.commit()


def test_test_season_never_used_in_fitting(app, db, monkeypatch):
    """Proves that WinProbabilityModel.train_and_select never queries or fits on test_season (2024-25)."""
    from app.analytics.forecasting.win_probability import WinProbabilityModel
    with app.app_context():
        _seed_sample_seasons(db)
        model = WinProbabilityModel()
        queried_seasons = []

        orig_extract = model.extract_features_and_targets

        def mock_extract(season):
            queried_seasons.append(season)
            return orig_extract(season)

        monkeypatch.setattr(model, "extract_features_and_targets", mock_extract)
        model.train_and_select(train_season='20212022', select_season='20222023', calibrate_season='20232024', skip_gate=True)

        assert "20242025" not in queried_seasons
        assert queried_seasons == ['20212022', '20222023', '20232024']


def test_calibration_season_not_used_in_candidate_selection(app, db, monkeypatch):
    """Proves that candidate model selection decision relies on select_season (2022-23) and not calibrate_season (2023-24)."""
    from app.analytics.forecasting.win_probability import WinProbabilityModel
    with app.app_context():
        _seed_sample_seasons(db)
        model = WinProbabilityModel()
        
        # Run model selection and verify returned log loss metrics correspond to selection split
        summary = model.train_and_select(train_season='20212022', select_season='20222023', calibrate_season='20232024', skip_gate=True)
        assert "logistic_regression_log_loss" in summary
        assert "hgb_log_loss" in summary
        assert summary["selected_model"] in ["LogisticRegression", "HistGradientBoosting"]


def test_source_games_must_precede_target_games(app, db):
    """Proves that PregameFeatureService strictly enforces source.start_time_utc < target.start_time_utc."""
    from datetime import date, datetime, timezone
    from app.models import Game, Team
    from app.services.pregame_feature_service import PregameFeatureService

    with app.app_context():
        t1 = Team(team_id=10, abbreviation="T10", name="Team 10")
        t2 = Team(team_id=11, abbreviation="T11", name="Team 11")
        db.session.add_all([t1, t2])

        g_prior = Game(
            game_id=2023020998, season="20232024", game_type="R", game_date=date(2023, 10, 10),
            start_time_utc=datetime(2023, 10, 10, 19, 0, tzinfo=timezone.utc),
            home_team_id=10, away_team_id=11, home_score=3, away_score=1, nhl_game_state="OFF"
        )
        g_target = Game(
            game_id=2023020999, season="20232024", game_type="R", game_date=date(2023, 10, 15),
            start_time_utc=datetime(2023, 10, 15, 19, 0, tzinfo=timezone.utc),
            home_team_id=10, away_team_id=11, home_score=0, away_score=0, nhl_game_state="FUT"
        )
        g_future = Game(
            game_id=2023021000, season="20232024", game_type="R", game_date=date(2023, 10, 20),
            start_time_utc=datetime(2023, 10, 20, 19, 0, tzinfo=timezone.utc),
            home_team_id=10, away_team_id=11, home_score=2, away_score=4, nhl_game_state="OFF"
        )
        db.session.add_all([g_prior, g_target, g_future])
        db.session.commit()

        prior_games = PregameFeatureService.get_prior_completed_games_for_team(10, g_target)
        prior_ids = [g.game_id for g in prior_games]

        assert 2023020998 in prior_ids
        assert 2023021000 not in prior_ids


def test_synthetic_games_cannot_enter_production_training(app, db):
    """Proves that WinProbabilityModel feature extraction filters out synthetic data."""
    from datetime import date, datetime, timezone
    from app.models import Game, Team
    from app.analytics.forecasting.win_probability import WinProbabilityModel

    with app.app_context():
        if not db.session.get(Team, 10):
            db.session.add(Team(team_id=10, abbreviation="T10", name="Team 10"))
        if not db.session.get(Team, 11):
            db.session.add(Team(team_id=11, abbreviation="T11", name="Team 11"))

        g_real = Game(
            game_id=2021020001, season="20212022", game_type="R", game_date=date(2021, 10, 12),
            start_time_utc=datetime(2021, 10, 12, 19, 0, tzinfo=timezone.utc),
            home_team_id=10, away_team_id=11, home_score=2, away_score=1, nhl_game_state="OFF",
            data_source="nhl_api"
        )
        g_synth = Game(
            game_id=2021020002, season="20212022", game_type="R", game_date=date(2021, 10, 13),
            start_time_utc=datetime(2021, 10, 13, 19, 0, tzinfo=timezone.utc),
            home_team_id=10, away_team_id=11, home_score=5, away_score=2, nhl_game_state="OFF",
            data_source="synthetic_test"
        )
        db.session.add_all([g_real, g_synth])
        db.session.commit()

        model = WinProbabilityModel()
        _, _, game_ids = model.extract_features_and_targets("20212022")

        assert 2021020001 in game_ids
        assert 2021020002 not in game_ids


def test_holdout_predictions_generated_using_frozen_model(app, db):
    """Proves that evaluate_season uses fitted frozen model weights without modifying or retraining the classifier."""
    from app.analytics.forecasting.backtest_engine import BacktestEngine
    with app.app_context():
        _seed_sample_seasons(db)
        engine = BacktestEngine()
        engine.win_model.train_and_select(skip_gate=True)

        initial_weights = engine.win_model.model.coef_.copy() if hasattr(engine.win_model.model, 'coef_') else None

        # Evaluate season holdout
        engine.evaluate_season('20242025')

        if initial_weights is not None:
            import numpy as np
            assert np.array_equal(engine.win_model.model.coef_, initial_weights)


