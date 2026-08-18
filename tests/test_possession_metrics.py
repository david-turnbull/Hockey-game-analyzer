import pytest
from datetime import date
from app.models import Game, Team, Player, Shift, Event, Shot
from app.services.game_service import GameService

def test_possession_metrics_logic(app, db):
    """
    Tests the Skaters-on-Ice engine and verify that Corsi/Fenwick metrics 
    are computed correctly for skaters and handle situational filters (e.g. shot type blocking, manpower state).
    """
    # 1. Seed Teams and Players
    home_team = Team(team_id=1, name="Home", abbreviation="HOM")
    away_team = Team(team_id=2, name="Away", abbreviation="AWA")
    db.session.add_all([home_team, away_team])
    db.session.commit()
    
    # 3 active skaters on ice for home team, 1 goalie
    h1 = Player(player_id=11, first_name="Home", last_name="Skater1", position="C", current_team_id=1)
    h2 = Player(player_id=12, first_name="Home", last_name="Skater2", position="D", current_team_id=1)
    hg = Player(player_id=13, first_name="Home", last_name="Goalie", position="G", current_team_id=1)
    
    # 2 active skaters on ice for away team, 1 goalie
    a1 = Player(player_id=21, first_name="Away", last_name="Skater1", position="RW", current_team_id=2)
    ag = Player(player_id=22, first_name="Away", last_name="Goalie", position="G", current_team_id=2)
    db.session.add_all([h1, h2, hg, a1, ag])
    db.session.commit()
    
    # Create game
    game = Game(
        game_id=500,
        season="20232024",
        game_date=date(2023, 10, 15),
        game_type="R",
        home_team_id=1,
        away_team_id=2,
        home_score=1,
        away_score=1,
        game_status="Final"
    )
    db.session.add(game)
    db.session.commit()
    
    # Create shifts (0 to 600 seconds)
    s_h1 = Shift(shift_id="sh1", game_id=500, player_id=11, team_id=1, period=1, start_time="00:00", end_time="10:00", start_elapsed_seconds=0, end_elapsed_seconds=600, duration=600)
    s_h2 = Shift(shift_id="sh2", game_id=500, player_id=12, team_id=1, period=1, start_time="00:00", end_time="10:00", start_elapsed_seconds=0, end_elapsed_seconds=600, duration=600)
    s_a1 = Shift(shift_id="sa1", game_id=500, player_id=21, team_id=2, period=1, start_time="00:00", end_time="10:00", start_elapsed_seconds=0, end_elapsed_seconds=600, duration=600)
    s_hg = Shift(shift_id="shg", game_id=500, player_id=13, team_id=1, period=1, start_time="00:00", end_time="20:00", start_elapsed_seconds=0, end_elapsed_seconds=1200, duration=1200)
    s_ag = Shift(shift_id="sag", game_id=500, player_id=22, team_id=2, period=1, start_time="00:00", end_time="20:00", start_elapsed_seconds=0, end_elapsed_seconds=1200, duration=1200)
    db.session.add_all([s_h1, s_h2, s_a1, s_hg, s_ag])
    db.session.commit()
    
    # Create events
    # Event 1: Unblocked Saved Shot by Home team at 200 seconds (EV strength)
    # Skaters on ice: h1, h2, a1
    e1 = Event(event_id="evt1", game_id=500, period=1, period_time="03:20", elapsed_game_seconds=200, event_type="shot-on-goal", team_id=1, primary_player_id=11, manpower_state="EV")
    db.session.add(e1)
    db.session.commit()
    sh1 = Shot(shot_id="evt1", game_id=500, team_id=1, shooter_id=11, goalie_id=22, x_coordinate=70.0, y_coordinate=0.0, distance=20.0, angle=0.0, outcome="Saved", shot_type="snap", goal=False)
    db.session.add(sh1)
    db.session.commit()
    
    # Event 2: Blocked Shot by Away team at 400 seconds (EV strength)
    # Skaters on ice: h1, h2, a1
    e2 = Event(event_id="evt2", game_id=500, period=1, period_time="06:40", elapsed_game_seconds=400, event_type="blocked-shot", team_id=2, primary_player_id=21, manpower_state="EV")
    db.session.add(e2)
    db.session.commit()
    sh2 = Shot(shot_id="evt2", game_id=500, team_id=2, shooter_id=21, goalie_id=13, x_coordinate=-65.0, y_coordinate=10.0, distance=30.0, angle=15.0, outcome="Blocked", shot_type="slap", goal=False)
    db.session.add(sh2)
    db.session.commit()
    
    # Event 3: Power Play Shot by Home team at 500 seconds (PP strength)
    # PP shot should be EXCLUDED from Corsi/Fenwick metrics!
    e3 = Event(event_id="evt3", game_id=500, period=1, period_time="08:20", elapsed_game_seconds=500, event_type="shot-on-goal", team_id=1, primary_player_id=11, manpower_state="PP")
    db.session.add(e3)
    db.session.commit()
    sh3 = Shot(shot_id="evt3", game_id=500, team_id=1, shooter_id=11, goalie_id=22, x_coordinate=75.0, y_coordinate=-2.0, distance=18.0, angle=5.0, outcome="Saved", shot_type="wrist", goal=False)
    db.session.add(sh3)
    db.session.commit()
    
    # 2. Run calculations
    pos = GameService.calculate_possession_stats(500)
    
    # Assertions
    # h1 (Home Skater 1):
    # Event 1: Shot taken by their team (For). Saved (CF + 1, FF + 1)
    # Event 2: Shot taken by opponent (Against). Blocked (CA + 1, FA + 0)
    # Event 3: Excluded (PP)
    h1_stats = pos.get(11)
    assert h1_stats is not None
    assert h1_stats["cf"] == 1
    assert h1_stats["ca"] == 1
    assert h1_stats["cf_pct"] == 50.0
    assert h1_stats["ff"] == 1
    assert h1_stats["fa"] == 0
    assert h1_stats["ff_pct"] == 100.0
    
    # h2 (Home Skater 2):
    # On ice for both EV shots (since shift is 0 to 600s).
    # Same stats as h1.
    h2_stats = pos.get(12)
    assert h2_stats is not None
    assert h2_stats["cf"] == 1
    assert h2_stats["ca"] == 1
    assert h2_stats["cf_pct"] == 50.0
    
    # a1 (Away Skater 1):
    # Event 1: Shot taken by opponent (Against). Saved (CA + 1, FA + 1)
    # Event 2: Shot taken by their team (For). Blocked (CF + 1, FF + 0)
    # Total for a1:
    # CF = 1, CA = 1, CF% = 50.0
    # FF = 0, FA = 1, FF% = 0.0
    a1_stats = pos.get(21)
    assert a1_stats is not None
    assert a1_stats["cf"] == 1
    assert a1_stats["ca"] == 1
    assert a1_stats["cf_pct"] == 50.0
    assert a1_stats["ff"] == 0
    assert a1_stats["fa"] == 1
    assert a1_stats["ff_pct"] == 0.0
    
    # Verify goalie is NOT in possession dictionary
    assert 13 not in pos
    assert 22 not in pos
