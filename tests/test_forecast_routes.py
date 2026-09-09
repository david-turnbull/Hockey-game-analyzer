import pytest
from datetime import date, datetime
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

        # Seed sample game
        g = Game(
            game_id=2024020001,
            season='20242025',
            game_date=date(2024, 10, 10),
            start_time_utc=datetime(2024, 10, 10, 19, 0, 0),
            game_type='R',
            home_team_id=1,
            away_team_id=2,
            home_score=3,
            away_score=2,
            nhl_game_state='OFF'
        )
        db.session.add(g)
        db.session.commit()

        yield app

        db.session.remove()
        db.drop_all()

@pytest.fixture
def client(app):
    return app.test_client()

def test_forecast_api_game_prediction(client):
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

def test_forecast_ui_routes(client):
    res = client.get('/forecast')
    assert res.status_code == 200

    res_game = client.get('/forecast/game/2024020001')
    assert res_game.status_code == 200
