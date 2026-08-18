import pytest
from datetime import date
from app.models import Game, Team, Player, Event, Shot
from app.services.xg_service import XGService
from app.services.game_service import GameService

def test_xg_service_logic():
    """
    Verifies the mathematical correctness and features adjustments of the Expected Goals model.
    """
    # 1. Close wrist shot vs Far slap shot
    close_wrist = XGService.calculate_shot_xg(distance=10.0, angle=0.0, shot_type="wrist", strength_state="EV")
    far_slap = XGService.calculate_shot_xg(distance=60.0, angle=45.0, shot_type="slap", strength_state="EV")
    
    # Close wrist shot should have significantly higher xG
    assert close_wrist > far_slap
    assert 0.0 < close_wrist < 1.0
    assert 0.0 < far_slap < 1.0
    
    # 2. Deflection/tip-in bonus
    standard_wrist = XGService.calculate_shot_xg(distance=15.0, angle=10.0, shot_type="wrist", strength_state="EV")
    tip_in = XGService.calculate_shot_xg(distance=15.0, angle=10.0, shot_type="tip-in", strength_state="EV")
    assert tip_in > standard_wrist
    
    # 3. Manpower state adjustments (PP vs SH)
    pp_shot = XGService.calculate_shot_xg(distance=25.0, angle=15.0, shot_type="wrist", strength_state="PP")
    sh_shot = XGService.calculate_shot_xg(distance=25.0, angle=15.0, shot_type="wrist", strength_state="SH")
    assert pp_shot > sh_shot
    
    # 4. Empty Net override
    close_empty = XGService.calculate_shot_xg(distance=30.0, angle=0.0, empty_net=True)
    far_empty = XGService.calculate_shot_xg(distance=150.0, angle=0.0, empty_net=True)
    assert close_empty > far_empty
    assert close_empty == 0.85 # 1.0 - 30 * 0.005 = 0.85
    assert far_empty == 0.25 # 1.0 - 150 * 0.005 = 0.25

def test_xg_game_integration(app, db, client):
    """
    Verifies that game statistics and skater details aggregate and return expected xG values.
    """
    team = Team(team_id=1, name="Test Team", abbreviation="TST")
    db.session.add(team)
    db.session.commit()
    
    skater = Player(player_id=10, first_name="John", last_name="Skater", position="C", current_team_id=1)
    db.session.add(skater)
    db.session.commit()
    
    game = Game(
        game_id=900,
        season="20232024",
        game_date=date(2023, 11, 1),
        game_type="R",
        home_team_id=1,
        away_team_id=1,
        home_score=1,
        away_score=1,
        game_status="Final"
    )
    db.session.add(game)
    db.session.commit()
    
    # Create shot with set xG
    e1 = Event(event_id="e_xg", game_id=900, period=1, period_time="05:00", elapsed_game_seconds=300, event_type="shot-on-goal", team_id=1, primary_player_id=10)
    db.session.add(e1)
    db.session.commit()
    
    shot = Shot(
        shot_id="e_xg", game_id=900, team_id=1, shooter_id=10, goalie_id=None,
        x_coordinate=75.0, y_coordinate=-5.0, distance=15.0, angle=10.0,
        outcome="Saved", shot_type="wrist", goal=False, xg=0.185
    )
    db.session.add(shot)
    db.session.commit()
    
    # Test service overview sum
    overview = GameService.get_game_overview_stats(900)
    assert overview is not None
    assert overview["stats"]["home_xg"] == 0.18
    
    # Test service player details sum
    player_stats = GameService.get_player_game_stats(900, 10)
    assert player_stats is not None
    assert player_stats["xg"] == 0.18
    
    # Test API response includes xg
    resp = client.get("/api/shots?game_id=900")
    assert resp.status_code == 200
    shots_data = resp.get_json()
    assert len(shots_data) == 1
    assert shots_data[0]["xg"] == 0.185
