import pytest
from datetime import date
from app.models import Game, Team, Player, Shift, Event, Shot, GamePlayer
from app.services.line_service import LineService

def test_line_combinations_logic(app, db):
    """
    Verify that get_line_combinations correctly identifies 3-forward lines 
    and 2-defenseman pairings, computes their TOI, and maps events to them.
    """
    # 1. Seed Teams
    team1 = Team(team_id=1, name="Flames", abbreviation="CGY")
    team2 = Team(team_id=2, name="Jets", abbreviation="WPG")
    db.session.add_all([team1, team2])
    db.session.commit()
    
    # 2. Seed Players (3 forwards, 2 defensemen, 1 goalie for Home; same for Away)
    p_h_f1 = Player(player_id=101, first_name="F1", last_name="Home", position="LW", current_team_id=1)
    p_h_f2 = Player(player_id=102, first_name="F2", last_name="Home", position="C", current_team_id=1)
    p_h_f3 = Player(player_id=103, first_name="F3", last_name="Home", position="RW", current_team_id=1)
    p_h_d1 = Player(player_id=104, first_name="D1", last_name="Home", position="D", current_team_id=1)
    p_h_d2 = Player(player_id=105, first_name="D2", last_name="Home", position="D", current_team_id=1)
    p_h_g = Player(player_id=106, first_name="G1", last_name="Home", position="G", current_team_id=1)
    
    db.session.add_all([p_h_f1, p_h_f2, p_h_f3, p_h_d1, p_h_d2, p_h_g])
    db.session.commit()
    
    # 3. Create Game
    game = Game(
        game_id=800,
        season="20232024",
        game_date=date(2023, 10, 20),
        game_type="R",
        home_team_id=1,
        away_team_id=2,
        home_score=1,
        away_score=0,
        game_status="Final"
    )
    db.session.add(game)
    db.session.commit()
    
    # 4. Create Shifts (all skaters are active from 0 to 100 seconds)
    # This forms a single forward line and a single defensive pairing for Home
    s_f1 = Shift(shift_id="sh_f1", game_id=800, player_id=101, team_id=1, period=1, start_time="00:00", end_time="01:40", start_elapsed_seconds=0, end_elapsed_seconds=100, duration=100)
    s_f2 = Shift(shift_id="sh_f2", game_id=800, player_id=102, team_id=1, period=1, start_time="00:00", end_time="01:40", start_elapsed_seconds=0, end_elapsed_seconds=100, duration=100)
    s_f3 = Shift(shift_id="sh_f3", game_id=800, player_id=103, team_id=1, period=1, start_time="00:00", end_time="01:40", start_elapsed_seconds=0, end_elapsed_seconds=100, duration=100)
    s_d1 = Shift(shift_id="sh_d1", game_id=800, player_id=104, team_id=1, period=1, start_time="00:00", end_time="01:40", start_elapsed_seconds=0, end_elapsed_seconds=100, duration=100)
    s_d2 = Shift(shift_id="sh_d2", game_id=800, player_id=105, team_id=1, period=1, start_time="00:00", end_time="01:40", start_elapsed_seconds=0, end_elapsed_seconds=100, duration=100)
    s_g = Shift(shift_id="sh_g", game_id=800, player_id=106, team_id=1, period=1, start_time="00:00", end_time="01:40", start_elapsed_seconds=0, end_elapsed_seconds=100, duration=100)
    
    db.session.add_all([s_f1, s_f2, s_f3, s_d1, s_d2, s_g])
    db.session.commit()
    
    # Seed GamePlayer roster records
    gps = [
        GamePlayer(game_id=800, player_id=101, team_id=1, position="LW"),
        GamePlayer(game_id=800, player_id=102, team_id=1, position="C"),
        GamePlayer(game_id=800, player_id=103, team_id=1, position="RW"),
        GamePlayer(game_id=800, player_id=104, team_id=1, position="D"),
        GamePlayer(game_id=800, player_id=105, team_id=1, position="D"),
        GamePlayer(game_id=800, player_id=106, team_id=1, position="G"),
    ]
    db.session.add_all(gps)
    db.session.commit()
    
    # 5. Add a shot and a goal event at 50 seconds (while line and pairing are on ice)
    # Event 1: Goal by Home team at 50s
    e1 = Event(event_id="e_g1", game_id=800, period=1, period_time="00:50", elapsed_game_seconds=50, event_type="goal", team_id=1, primary_player_id=101, manpower_state="EV")
    db.session.add(e1)
    db.session.commit()
    shot1 = Shot(shot_id="e_g1", game_id=800, team_id=1, shooter_id=101, goalie_id=106, x_coordinate=80.0, y_coordinate=5.0, distance=10.0, angle=5.0, outcome="Goal", shot_type="wrist", goal=True)
    db.session.add(shot1)
    db.session.commit()
    
    # 6. Run line combinations engine
    combos = LineService.get_line_combinations(800)
    
    assert combos is not None
    assert "home" in combos
    assert "away" in combos
    
    # Assert Home Forward Lines
    home_lines = combos["home"]["lines"]
    assert len(home_lines) == 1
    assert home_lines[0]["toi_seconds"] == 100
    assert home_lines[0]["toi"] == "01:40"
    assert home_lines[0]["goals_for"] == 1
    assert home_lines[0]["goals_against"] == 0
    assert home_lines[0]["sog_for"] == 1
    
    # Assert Home Defensive Pairings
    home_pairings = combos["home"]["pairings"]
    assert len(home_pairings) == 1
    assert home_pairings[0]["toi_seconds"] == 100
    assert home_pairings[0]["toi"] == "01:40"
    assert home_pairings[0]["goals_for"] == 1
    assert home_pairings[0]["sog_for"] == 1
    
    # Assert Away lists are empty
    assert len(combos["away"]["lines"]) == 0
    assert len(combos["away"]["pairings"]) == 0
