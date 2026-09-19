import pytest
import hmac
from datetime import datetime, date, timezone, timedelta
from pathlib import Path

from app import create_app
from app.models import db, Team, Game, GamePrediction, Event
from app.services.forecast_service import ForecastService
from app.services.schedule_sync_service import ScheduleSyncService
from app.services.prediction_generator_service import PredictionGeneratorService
from app.services.operational_monitoring_service import OperationalMonitoringService

@pytest.fixture
def app_fixture():
    app = create_app('testing')
    with app.app_context():
        db.create_all()
        t1 = Team(team_id=1, abbreviation='T1', name='Team 1')
        t2 = Team(team_id=2, abbreviation='T2', name='Team 2')
        db.session.add_all([t1, t2])

        future_dt = datetime.now(timezone.utc) + timedelta(hours=36)
        g_fut = Game(
            game_id=2024020101,
            season='20242025',
            game_date=future_dt.date(),
            start_time_utc=future_dt,
            game_type='R',
            home_team_id=1,
            away_team_id=2,
            home_score=0,
            away_score=0,
            nhl_game_state='FUT',
            data_source='nhl_api'
        )
        db.session.add(g_fut)
        db.session.commit()

        yield app

        db.session.remove()
        db.drop_all()

@pytest.fixture
def client(app_fixture):
    return app_fixture.test_client()

def test_strictly_read_only_get_routes(client, app_fixture):
    """Proves GET forecast routes strictly query existing predictions and never mutate DB."""
    with app_fixture.app_context():
        assert GamePrediction.query.count() == 0

        # 1. GET /api/v1/forecast/game/2024020101 returns 404 when no prediction exists
        res_api = client.get('/api/v1/forecast/game/2024020101')
        assert res_api.status_code == 404
        assert res_api.get_json()["error"] == "PREDICTION_NOT_FOUND"
        assert GamePrediction.query.count() == 0

        # 2. GET /forecast/game/2024020101 returns 404
        res_ui = client.get('/forecast/game/2024020101')
        assert res_ui.status_code == 404
        assert GamePrediction.query.count() == 0

        # 3. GET /api/v1/forecast/upcoming exposes prediction_status = 'missing'
        res_up = client.get('/api/v1/forecast/upcoming')
        assert res_up.status_code == 200
        data_up = res_up.get_json()
        assert data_up["count"] == 1
        assert data_up["forecasts"][0]["prediction_status"] == "missing"
        assert data_up["forecasts"][0]["prediction"] is None
        assert GamePrediction.query.count() == 0

def test_provenance_and_timestamp_snapshots(app_fixture):
    """Verifies created_at and input_cutoff_time_utc record generation time while scheduled_start_time_utc records start_time_utc."""
    with app_fixture.app_context():
        g = db.session.get(Game, 2024020101)
        start_time_orig = g.start_time_utc

        pred_dict = ForecastService.create_prediction(2024020101, prediction_type='official_pregame')
        assert "error" not in pred_dict
        pred_id = pred_dict["prediction_id"]

        pred_db = db.session.get(GamePrediction, pred_id)
        assert pred_db.scheduled_start_time_utc == start_time_orig
        assert pred_db.created_at is not None
        assert pred_db.input_cutoff_time_utc is not None
        # Difference between creation time and scheduled start time (2 days)
        diff_hours = abs((pred_db.scheduled_start_time_utc.replace(tzinfo=timezone.utc) - pred_db.created_at.replace(tzinfo=timezone.utc)).total_seconds()) / 3600.0
        assert diff_hours > 24.0

def test_dual_auth_post_prediction_generation(client, app_fixture):
    """Verifies fail-closed POST prediction generation semantics requiring both config flag and constant-time token."""
    with app_fixture.app_context():
        # 1. When ALLOW_PREDICTION_GENERATION is False -> 403
        app_fixture.config['ALLOW_PREDICTION_GENERATION'] = False
        res_dis = client.post('/api/v1/forecast/game/2024020101/generate')
        assert res_dis.status_code == 403
        assert res_dis.get_json()["error"] == "GENERATION_DISABLED"

        # 2. When ALLOW_PREDICTION_GENERATION is True but token invalid/missing -> 401
        app_fixture.config['ALLOW_PREDICTION_GENERATION'] = True
        app_fixture.config['PREDICTION_GENERATION_TOKEN'] = 'secret-token-123'

        res_unauth = client.post('/api/v1/forecast/game/2024020101/generate', headers={'X-Generation-Token': 'wrong-token'})
        assert res_unauth.status_code == 401
        assert res_unauth.get_json()["error"] == "UNAUTHORIZED"

        # 3. With valid token -> 201 Created
        res_ok = client.post('/api/v1/forecast/game/2024020101/generate', headers={'X-Generation-Token': 'secret-token-123'})
        assert res_ok.status_code == 201
        assert res_ok.get_json()["game_id"] == 2024020101

        # Re-querying GET now returns 200 OK with the generated prediction
        res_get = client.get('/api/v1/forecast/game/2024020101')
        assert res_get.status_code == 200
        assert res_get.get_json()["is_official"] is True

def test_prediction_generator_service_idempotency_and_cutoff(app_fixture):
    """Tests PredictionGeneratorService idempotency, lookahead, and cutoff enforcement."""
    with app_fixture.app_context():
        # Add past game (already started)
        past_dt = datetime.now(timezone.utc) - timedelta(hours=1)
        g_past = Game(
            game_id=2024020102, season='20242025', game_date=past_dt.date(),
            start_time_utc=past_dt, game_type='R', home_team_id=1, away_team_id=2,
            nhl_game_state='LIVE', data_source='nhl_api'
        )
        db.session.add(g_past)
        db.session.commit()

        # Run generator - past games excluded by SQL query filter (start_time_utc > now_utc)
        summary1 = PredictionGeneratorService.generate_official_pregame_predictions(lookahead_hours=72)
        assert summary1["generated_count"] == 1
        assert summary1["total_games_scanned"] == 1
        assert summary1["skipped_existing_count"] == 0

        # Re-run generator (idempotent: skips existing prediction)
        summary2 = PredictionGeneratorService.generate_official_pregame_predictions(lookahead_hours=72)
        assert summary2["generated_count"] == 0
        assert summary2["skipped_existing_count"] == 1

def test_schedule_sync_service_freshness(app_fixture):
    """Verifies schedule freshness auditing."""
    with app_fixture.app_context():
        res = ScheduleSyncService.check_schedule_freshness('20242025')
        assert res["total_games"] == 1
        assert res["missing_start_time_count"] == 0
        assert res["is_fresh"] is True

def test_sample_aware_operational_monitoring(app_fixture):
    """Verifies operational monitoring grouped by (model_version, model_sha256) and INSUFFICIENT_SAMPLE threshold."""
    with app_fixture.app_context():
        # Active model status
        m_status = OperationalMonitoringService.get_active_model_status()
        assert m_status["status"] == "ACTIVE"
        assert m_status["model_version"] == "v1.4.0"

        # Coverage summary
        cov = OperationalMonitoringService.get_coverage_summary()
        assert cov["lookahead_hours"] == 48
        assert cov["upcoming_games_total"] == 1
        assert cov["upcoming_games_predicted"] == 0
        assert cov["remaining_season_games_total"] == 1

        # Create prediction and simulate outcome resolution
        ForecastService.create_prediction(2024020101, prediction_type='official_pregame')
        g = db.session.get(Game, 2024020101)
        g.nhl_game_state = 'OFF'
        g.home_score = 4
        g.away_score = 2
        db.session.commit()

        # Calibration check with min_sample_threshold = 30 -> INSUFFICIENT_SAMPLE
        calib_thresh = OperationalMonitoringService.get_calibration_and_performance(min_sample_threshold=30)
        assert len(calib_thresh["groups"]) == 1
        assert calib_thresh["groups"][0]["status"] == "INSUFFICIENT_SAMPLE"
        assert calib_thresh["groups"][0]["sample_count"] == 1

        # Calibration check with min_sample_threshold = 1 -> EVALUATED
        calib_eval = OperationalMonitoringService.get_calibration_and_performance(min_sample_threshold=1)
        grp = calib_eval["groups"][0]
        assert grp["status"] == "EVALUATED"
        assert grp["sample_count"] == 1
        assert "brier_score" in grp
        assert "log_loss" in grp
        assert "score_mae_reg_ot" in grp

def test_health_and_readiness_probes(client, app_fixture):
    """Verifies /api/v1/health (liveness) and /api/v1/ready (readiness) endpoints."""
    # Liveness probe
    res_health = client.get('/api/v1/health')
    assert res_health.status_code == 200
    assert res_health.get_json()["status"] == "healthy"

    # Readiness probe
    res_ready = client.get('/api/v1/ready')
    assert res_ready.status_code == 200
    data_r = res_ready.get_json()
    assert data_r["status"] == "READY"
    assert data_r["checks"]["database_connection"] == "OK"
    assert data_r["checks"]["sqlite_foreign_keys"] == "ENABLED"
    assert data_r["checks"]["official_pregame_index"] == "OK"
    assert data_r["checks"]["model_artifact_sha256"] == "VERIFIED_OK"
