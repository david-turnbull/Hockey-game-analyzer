import pytest
from datetime import datetime, date, time
from app import create_app
from app.models import db, Team, Game, Event, Shot, Player
from app.services.pregame_feature_service import PregameFeatureService

@pytest.fixture
def app():
    app = create_app('testing')
    with app.app_context():
        db.create_all()
        # Seed test teams
        team1 = Team(team_id=101, abbreviation='TST1', name='Test Team 1')
        team2 = Team(team_id=102, abbreviation='TST2', name='Test Team 2')
        db.session.add_all([team1, team2])
        db.session.commit()

        yield app

        db.session.remove()
        db.drop_all()

def test_pregame_feature_leakage_safety(app):
    with app.app_context():
        # Setup 3 games: Game 1 (past), Game 2 (target), Game 3 (future)
        g1 = Game(
            game_id=9001, season='20232024', game_date=date(2023, 10, 10),
            start_time_utc=datetime(2023, 10, 10, 19, 0, 0), game_type='R',
            home_team_id=101, away_team_id=102, home_score=4, away_score=2, nhl_game_state='OFF'
        )
        g2_target = Game(
            game_id=9002, season='20232024', game_date=date(2023, 10, 12),
            start_time_utc=datetime(2023, 10, 12, 19, 0, 0), game_type='R',
            home_team_id=101, away_team_id=102, home_score=0, away_score=0, nhl_game_state='FUT'
        )
        g3_future = Game(
            game_id=9003, season='20232024', game_date=date(2023, 10, 15),
            start_time_utc=datetime(2023, 10, 15, 19, 0, 0), game_type='R',
            home_team_id=101, away_team_id=102, home_score=10, away_score=0, nhl_game_state='OFF'
        )
        db.session.add_all([g1, g2_target, g3_future])
        db.session.commit()

        # Prior games for g2_target should ONLY return g1 (not g3_future and not g2_target itself)
        prior_home = PregameFeatureService.get_prior_completed_games_for_team(101, g2_target)
        assert len(prior_home) == 1
        assert prior_home[0].game_id == 9001

        # Compute pregame features
        feats = PregameFeatureService.get_pregame_features(g2_target)
        assert feats["game_id"] == 9002
        assert feats["home_rest_days"] == 2.0
        assert feats["home_l10_gf_per_game"] == 4.0
        assert feats["home_l10_ga_per_game"] == 2.0
