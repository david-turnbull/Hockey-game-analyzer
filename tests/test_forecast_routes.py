import pytest
from datetime import date, datetime, timedelta, timezone
from app import create_app
from app.models import db, Team, Game, GamePrediction
from app.services.forecast_service import ForecastService
from app.services.prediction_generator_service import PredictionGeneratorService
from app.services.operational_monitoring_service import OperationalMonitoringService

@pytest.fixture
def app():
    app = create_app('testing')
    with app.app_context():
        db.create_all()
        t1 = Team(team_id=1, abbreviation='T1', name='Team 1')
        t2 = Team(team_id=2, abbreviation='T2', name='Team 2')
        db.session.add_all([t1, t2])

        now_utc = datetime.now(timezone.utc)

        # Game inside 48-hour horizon (24h out)
        g_inside = Game(
            game_id=2024020001,
            season='20242025',
            game_date=(now_utc + timedelta(hours=24)).date(),
            start_time_utc=now_utc + timedelta(hours=24),
            game_type='R',
            home_team_id=1,
            away_team_id=2,
            home_score=0,
            away_score=0,
            nhl_game_state='FUT',
            data_source='nhl_api'
        )

        # Game inside 48-hour horizon but past 24h (30h out)
        g_30h = Game(
            game_id=2024020030,
            season='20242025',
            game_date=(now_utc + timedelta(hours=30)).date(),
            start_time_utc=now_utc + timedelta(hours=30),
            game_type='R',
            home_team_id=1,
            away_team_id=2,
            home_score=0,
            away_score=0,
            nhl_game_state='FUT',
            data_source='nhl_api'
        )

        # Game specifically at +49h (outside 48-hour horizon)
        g_49h = Game(
            game_id=2024020049,
            season='20242025',
            game_date=(now_utc + timedelta(hours=49)).date(),
            start_time_utc=now_utc + timedelta(hours=49),
            game_type='R',
            home_team_id=1,
            away_team_id=2,
            home_score=0,
            away_score=0,
            nhl_game_state='FUT',
            data_source='nhl_api'
        )

        db.session.add_all([g_inside, g_30h, g_49h])
        db.session.commit()

        yield app

        db.session.remove()
        db.drop_all()

@pytest.fixture
def client(app):
    return app.test_client()

def test_forecast_api_game_prediction(app, client):
    # 1. Read-only GET returns 404 when no prediction has been generated yet
    res_404 = client.get('/api/v1/forecast/game/2024020001')
    assert res_404.status_code == 404
    assert res_404.get_json()["error"] == "PREDICTION_NOT_FOUND"

    # 2. Create prediction explicitly via service
    with app.app_context():
        ForecastService.create_prediction(2024020001, prediction_type='official_pregame')

    # 3. Read-only GET returns 200 OK after prediction has been generated
    res = client.get('/api/v1/forecast/game/2024020001')
    assert res.status_code == 200
    data = res.get_json()
    assert data["game_id"] == 2024020001
    assert "win_probability" in data
    assert "score_projection" in data
    assert data["is_official"] is True

def test_forecast_api_upcoming_48h_horizon_and_counts(app, client):
    """Verifies metadata fields: count, available_count, missing_count, lookahead_hours, window timestamps."""
    # Create prediction for g_inside (24h out)
    with app.app_context():
        ForecastService.create_prediction(2024020001, prediction_type='official_pregame')

    res = client.get('/api/v1/forecast/upcoming')
    assert res.status_code == 200
    data = res.get_json()
    assert data["lookahead_hours"] == 48
    assert "window_start_utc" in data
    assert "window_end_utc" in data
    assert data["count"] == 2
    assert data["available_count"] == 1
    assert data["missing_count"] == 1

    forecasts = data["forecasts"]
    assert len(forecasts) == 2
    
    # 2024020001 is available
    f_avail = next(f for f in forecasts if f["game_id"] == 2024020001)
    assert f_avail["prediction_status"] == "available"
    assert f_avail["win_probability"] is not None

    # 2024020030 is missing
    f_miss = next(f for f in forecasts if f["game_id"] == 2024020030)
    assert f_miss["prediction_status"] == "missing"
    assert f_miss["win_probability"] is None
    assert f_miss["score_projection"] is None

def test_games_inside_48h_included_and_49h_excluded(client):
    """Proves game inside 48h is included while game at +49h is excluded under default horizon."""
    res_default = client.get('/api/v1/forecast/upcoming')
    assert res_default.status_code == 200
    data_def = res_default.get_json()
    game_ids_def = [f["game_id"] for f in data_def["forecasts"]]
    assert 2024020001 in game_ids_def
    assert 2024020030 in game_ids_def
    assert 2024020049 not in game_ids_def

def test_explicit_lookahead_hours_override(client):
    """Proves explicit lookahead_hours=24 overrides configured 48h default."""
    # lookahead=24 includes 24h game, excludes 30h and 49h games
    res_24 = client.get('/api/v1/forecast/upcoming?lookahead_hours=24')
    assert res_24.status_code == 200
    data_24 = res_24.get_json()
    assert data_24["lookahead_hours"] == 24
    game_ids_24 = [f["game_id"] for f in data_24["forecasts"]]
    assert 2024020001 in game_ids_24
    assert 2024020030 not in game_ids_24
    assert 2024020049 not in game_ids_24

    # lookahead=72 includes all three games
    res_72 = client.get('/api/v1/forecast/upcoming?lookahead_hours=72')
    assert res_72.status_code == 200
    data_72 = res_72.get_json()
    assert data_72["lookahead_hours"] == 72
    game_ids_72 = [f["game_id"] for f in data_72["forecasts"]]
    assert 2024020001 in game_ids_72
    assert 2024020030 in game_ids_72
    assert 2024020049 in game_ids_72

def test_all_games_shown_without_default_limit_of_12(app, client):
    """Verifies that more than 12 games in the 48h window are all returned when no limit is supplied."""
    with app.app_context():
        now_utc = datetime.now(timezone.utc)
        many_games = []
        for i in range(15):
            g = Game(
                game_id=2024021000 + i,
                season='20242025',
                game_date=(now_utc + timedelta(hours=10 + i)).date(),
                start_time_utc=now_utc + timedelta(hours=10 + i),
                game_type='R',
                home_team_id=1,
                away_team_id=2,
                home_score=0,
                away_score=0,
                nhl_game_state='FUT',
                data_source='nhl_api'
            )
            many_games.append(g)
        db.session.add_all(many_games)
        db.session.commit()

    # Query without limit returns all 17 games in window (2 fixture + 15 new)
    res = client.get('/api/v1/forecast/upcoming')
    assert res.status_code == 200
    data = res.get_json()
    assert data["count"] == 17
    assert len(data["forecasts"]) == 17

    # Query with explicit limit=5 returns only 5 games
    res_limit = client.get('/api/v1/forecast/upcoming?limit=5')
    assert res_limit.status_code == 200
    data_lim = res_limit.get_json()
    assert len(data_lim["forecasts"]) == 5

def test_forecast_ui_missing_prediction_pending_state(app, client):
    res = client.get('/forecast')
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "Next 48 Hours" in html
    assert "Prediction pending" in html
    assert "View Full Forecast & Matrix" not in html

def test_generator_and_monitoring_default_horizon_consistency(app):
    with app.app_context():
        # Generator with default lookahead_hours=None defaults to 48
        gen_summary = PredictionGeneratorService.generate_official_pregame_predictions(lookahead_hours=None, dry_run=True)
        assert gen_summary["lookahead_hours"] == 48

        # Monitoring with default lookahead_hours=None defaults to 48
        mon_summary = OperationalMonitoringService.get_coverage_summary(lookahead_hours=None)
        assert mon_summary["lookahead_hours"] == 48
