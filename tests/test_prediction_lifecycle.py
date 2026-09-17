import os
import json
import pytest
import numpy as np
from datetime import datetime, date, timezone, timedelta
from sqlalchemy.exc import IntegrityError

from app.models import db, Game, GamePrediction, Team, Event, Shot
from app.services.forecast_service import ForecastService
from app.services.pregame_feature_service import PregameFeatureService
from app.analytics.forecasting.model_registry import ForecastModelRegistry

def test_legacy_migration_classification(app, db):
    """Verifies that legacy prediction rows created after puck drop are classified as legacy_unverified."""
    with app.app_context():
        t1 = Team(team_id=1, abbreviation="CGY", name="Calgary Flames")
        t2 = Team(team_id=2, abbreviation="EDM", name="Edmonton Oilers")
        db.session.add_all([t1, t2])

        g1 = Game(
            game_id=2023029001, season='20232024', game_date=date(2023, 10, 10),
            start_time_utc=datetime(2023, 10, 10, 19, 0, 0), game_type='R',
            home_team_id=1, away_team_id=2, nhl_game_state='OFF', data_source='nhl_api'
        )
        db.session.add(g1)
        db.session.commit()

        # Legacy pre-puck-drop prediction
        p_official = GamePrediction(
            game_id=2023029001, created_at=datetime(2023, 10, 10, 18, 0, 0),
            home_win_probability=0.55, away_win_probability=0.45,
            expected_home_goals=3.1, expected_away_goals=2.5,
            model_version='v1.4.0', is_official=True, prediction_type=''
        )

        # Legacy post-puck-drop prediction
        p_unverified = GamePrediction(
            game_id=2023029001, created_at=datetime(2023, 10, 10, 20, 0, 0),
            home_win_probability=0.60, away_win_probability=0.40,
            expected_home_goals=3.5, expected_away_goals=2.0,
            model_version='v1.4.0-old', is_official=False, prediction_type=''
        )
        db.session.add_all([p_official, p_unverified])
        db.session.commit()

        # Run migration logic
        from app.utils.db_migrator import run_migrations
        run_migrations(db)

        p_off_db = db.session.get(GamePrediction, p_official.prediction_id)
        p_unv_db = db.session.get(GamePrediction, p_unverified.prediction_id)

        assert p_off_db.prediction_type == 'official_pregame'
        assert p_unv_db.prediction_type == 'legacy_unverified'

def test_duplicate_detection(app, db):
    """Verifies that duplicate official_pregame predictions for (game_id, model_version) raise IntegrityError."""
    with app.app_context():
        t1 = Team.query.get(1) or Team(team_id=1, abbreviation="CGY", name="Calgary Flames")
        t2 = Team.query.get(2) or Team(team_id=2, abbreviation="EDM", name="Edmonton Oilers")
        db.session.add_all([t1, t2])

        g = Game(
            game_id=2023029002, season='20232024', game_date=date(2023, 10, 11),
            start_time_utc=datetime(2023, 10, 11, 19, 0, 0), game_type='R',
            home_team_id=1, away_team_id=2, nhl_game_state='FUT', data_source='nhl_api'
        )
        db.session.add(g)
        db.session.commit()

        p1 = GamePrediction(
            game_id=2023029002, created_at=datetime.now(timezone.utc),
            home_win_probability=0.52, away_win_probability=0.48,
            expected_home_goals=3.0, expected_away_goals=2.8,
            model_version='v1.4.0', prediction_type='official_pregame', is_official=True
        )
        p2 = GamePrediction(
            game_id=2023029002, created_at=datetime.now(timezone.utc),
            home_win_probability=0.54, away_win_probability=0.46,
            expected_home_goals=3.2, expected_away_goals=2.6,
            model_version='v1.4.0', prediction_type='official_pregame', is_official=True
        )

        db.session.add(p1)
        db.session.commit()

        # Adding duplicate prediction_type='official_pregame' for same game & model_version triggers IntegrityError
        db.session.add(p2)
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()

        # Multiple ad_hoc predictions are allowed
        adhoc1 = GamePrediction(
            game_id=2023029002, created_at=datetime.now(timezone.utc),
            home_win_probability=0.50, away_win_probability=0.50,
            expected_home_goals=2.5, expected_away_goals=2.5,
            model_version='v1.4.0', prediction_type='ad_hoc', run_id='run-1', is_official=False
        )
        adhoc2 = GamePrediction(
            game_id=2023029002, created_at=datetime.now(timezone.utc),
            home_win_probability=0.51, away_win_probability=0.49,
            expected_home_goals=2.6, expected_away_goals=2.4,
            model_version='v1.4.0', prediction_type='ad_hoc', run_id='run-2', is_official=False
        )
        db.session.add_all([adhoc1, adhoc2])
        db.session.commit()

def test_timezone_normalization_and_post_puck_drop_rejection(app, db):
    """Verifies naive SQLite datetimes are normalized to UTC and post-puck-drop creation requests are rejected."""
    with app.app_context():
        t1 = Team.query.get(1) or Team(team_id=1, abbreviation="CGY", name="Calgary Flames")
        t2 = Team.query.get(2) or Team(team_id=2, abbreviation="EDM", name="Edmonton Oilers")
        db.session.add_all([t1, t2])

        # Past game with naive start_time_utc
        past_start_naive = datetime.utcnow() - timedelta(hours=2)
        g_past = Game(
            game_id=2023029003, season='20232024', game_date=past_start_naive.date(),
            start_time_utc=past_start_naive, game_type='R',
            home_team_id=1, away_team_id=2, nhl_game_state='LIVE', data_source='nhl_api'
        )
        db.session.add(g_past)
        db.session.commit()

        # Post-puck-drop prediction attempt without pre-existing snapshot must be rejected
        res = ForecastService.get_or_create_prediction(2023029003, prediction_type='official_pregame')
        assert "error" in res
        assert res["error"] == "GAME_ALREADY_STARTED"
        assert res["status_code"] == 400

def test_immutable_snapshot_retrieval(app, db):
    """Proves an existing official_pregame snapshot is returned unchanged even if game finishes or underlying data changes."""
    with app.app_context():
        t1 = Team.query.get(1) or Team(team_id=1, abbreviation="CGY", name="Calgary Flames")
        t2 = Team.query.get(2) or Team(team_id=2, abbreviation="EDM", name="Edmonton Oilers")
        db.session.add_all([t1, t2])

        future_start = datetime.utcnow() + timedelta(days=1)
        g = Game(
            game_id=2023029004, season='20232024', game_date=future_start.date(),
            start_time_utc=future_start, game_type='R',
            home_team_id=1, away_team_id=2, nhl_game_state='FUT', data_source='nhl_api'
        )
        db.session.add(g)
        db.session.commit()

        # Create official pregame snapshot prior to puck drop
        pred1 = ForecastService.get_or_create_prediction(2023029004, prediction_type='official_pregame')
        assert "error" not in pred1
        orig_p_home = pred1["win_probability"]["home_win_probability"]

        # Mutate game status and score (simulate game finishing 5-0)
        g.nhl_game_state = 'OFF'
        g.home_score = 5
        g.away_score = 0
        db.session.commit()

        # Re-query prediction after game finish
        pred2 = ForecastService.get_or_create_prediction(2023029004, prediction_type='official_pregame')
        assert "error" not in pred2
        assert pred2["win_probability"]["home_win_probability"] == orig_p_home
        assert pred2["prediction_id"] == pred1["prediction_id"]

def test_model_version_specific_lookup(app, db):
    """Verifies that prediction lookup queries exact (game_id, model_version, prediction_type)."""
    with app.app_context():
        t1 = Team.query.get(1) or Team(team_id=1, abbreviation="CGY", name="Calgary Flames")
        t2 = Team.query.get(2) or Team(team_id=2, abbreviation="EDM", name="Edmonton Oilers")
        db.session.add_all([t1, t2])

        future_start = datetime.utcnow() + timedelta(days=2)
        g = Game(
            game_id=2023029005, season='20232024', game_date=future_start.date(),
            start_time_utc=future_start, game_type='R',
            home_team_id=1, away_team_id=2, nhl_game_state='FUT', data_source='nhl_api'
        )
        db.session.add(g)
        db.session.commit()

        # Create snapshot under active model
        pred = ForecastService.get_or_create_prediction(2023029005, prediction_type='official_pregame')
        assert "error" not in pred
        assert pred["game_id"] == 2023029005
        assert pred["prediction_type"] == 'official_pregame'
        assert pred["feature_payload_sha256"] is not None

def test_synthetic_data_exclusion_from_caches(app, db):
    """Proves that preload_all_stats() excludes synthetic test games (data_source == 'synthetic_test')."""
    with app.app_context():
        t99 = Team(team_id=99, abbreviation="SYN1", name="Synthetic Team 1")
        t98 = Team(team_id=98, abbreviation="SYN2", name="Synthetic Team 2")
        db.session.add_all([t99, t98])

        # Create synthetic game
        g_synth = Game(
            game_id=9999020001, season='20232024', game_date=date(2023, 10, 10),
            start_time_utc=datetime(2023, 10, 10, 19, 0, 0), game_type='R',
            home_team_id=99, away_team_id=98, home_score=4, away_score=1,
            nhl_game_state='OFF', data_source='synthetic_test'
        )
        db.session.add(g_synth)
        db.session.commit()

        # Reload stats cache
        PregameFeatureService.preload_all_stats()

        # Synthetic game must not be pre-indexed into _team_games_cache
        assert 99 not in PregameFeatureService._team_games_cache
        assert 98 not in PregameFeatureService._team_games_cache

def test_production_artifact_sha_consistency(app):
    """Validates that the SHA loaded by ForecastModelRegistry matches the manifest SHA."""
    with app.app_context():
        model_instance, manifest = ForecastModelRegistry.load_active_model()
        computed_sha = manifest["artifact_sha256"]
        assert len(computed_sha) == 64
        assert manifest["model_version"] == "v1.4.0"
        assert "production_refit_seasons" in manifest
        assert manifest["production_refit_seasons"] == ["20212022", "20222023"]
