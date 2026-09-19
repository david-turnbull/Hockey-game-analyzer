import pytest
from datetime import date, datetime, timedelta, timezone
from app import create_app
from app.models import db, Team, Game, GamePrediction

@pytest.fixture
def app():
    app = create_app('testing')
    with app.app_context():
        db.create_all()
        t1 = Team(team_id=1, abbreviation='T1', name='Team 1')
        t2 = Team(team_id=2, abbreviation='T2', name='Team 2')
        db.session.add_all([t1, t2])

        future_dt = datetime.now(timezone.utc) + timedelta(days=5)
        g = Game(
            game_id=2024020001,
            season='20242025',
            game_date=future_dt.date(),
            start_time_utc=future_dt,
            game_type='R',
            home_team_id=1,
            away_team_id=2,
            home_score=0,
            away_score=0,
            nhl_game_state='FUT'
        )
        db.session.add(g)
        db.session.commit()

        yield app

        db.session.remove()
        db.drop_all()

@pytest.fixture
def client(app):
    return app.test_client()

from app.services.forecast_service import ForecastService

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

def test_forecast_api_upcoming(client):
    res = client.get('/api/v1/forecast/upcoming')
    assert res.status_code == 200
    data = res.get_json()
    assert "forecasts" in data

def test_forecast_ui_routes(app, client):
    res = client.get('/forecast')
    assert res.status_code == 200

    # Before prediction creation -> 404
    res_game_404 = client.get('/forecast/game/2024020001')
    assert res_game_404.status_code == 404

    # Create prediction explicitly
    with app.app_context():
        ForecastService.create_prediction(2024020001, prediction_type='official_pregame')

    # After prediction creation -> 200
    res_game = client.get('/forecast/game/2024020001')
    assert res_game.status_code == 200
