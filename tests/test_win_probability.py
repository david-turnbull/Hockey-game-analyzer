import pytest
import numpy as np
from datetime import date, datetime
from app import create_app
from app.models import db, Team, Game
from app.analytics.forecasting.win_probability import WinProbabilityModel

@pytest.fixture
def app():
    app = create_app('testing')
    with app.app_context():
        db.create_all()
        t1 = Team(team_id=1, abbreviation='T1', name='Team 1')
        t2 = Team(team_id=2, abbreviation='T2', name='Team 2')
        db.session.add_all([t1, t2])

        # Seed sample games for train, select, and calibrate
        for s in ['20212022', '20222023', '20232024']:
            for i in range(10):
                g = Game(
                    game_id=int(f"{s[:4]}02{i+1:04d}"),
                    season=s,
                    game_date=date(int(s[:4]), 10, 10 + i),
                    start_time_utc=datetime(int(s[:4]), 10, 10 + i, 19, 0, 0),
                    game_type='R',
                    home_team_id=1,
                    away_team_id=2,
                    home_score=3 if i % 2 == 0 else 1,
                    away_score=1 if i % 2 == 0 else 3,
                    nhl_game_state='OFF'
                )
                db.session.add(g)
        db.session.commit()

        yield app

        db.session.remove()
        db.drop_all()

def test_win_probability_model_pipeline(app):
    with app.app_context():
        model = WinProbabilityModel()
        res = model.train_and_select(train_season='20212022', select_season='20222023', calibrate_season='20232024')
        
        assert res["selected_model"] in ["LogisticRegression", "HistGradientBoosting"]
        assert model.model is not None

        # Test single game prediction
        dummy_features = {
            "rest_differential": 1.0,
            "home_is_b2b": 0.0,
            "away_is_b2b": 1.0,
            "l10_xgf_pct_diff": 5.2,
            "l10_cf_pct_diff": 4.1,
            "l10_goal_diff_per_game": 0.8,
            "l20_xgf_pct_diff": 3.5,
            "home_venue_l10_win_pct": 60.0,
            "away_venue_l10_win_pct": 40.0,
            "h2h_home_win_pct": 60.0,
            "h2h_home_gd_avg": 1.0
        }

        pred = model.predict_game_probability(dummy_features)
        assert 0.0 < pred["home_win_probability"] < 1.0
        assert round(pred["home_win_probability"] + pred["away_win_probability"], 4) == 1.0
        assert len(pred["explanations"]) == len(model.feature_names)
