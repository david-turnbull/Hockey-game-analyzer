import pytest
from datetime import date
from app.models import Game, Team, Player, Shift, GamePlayer, Event, Shot
from app.services.line_service import LineService
from app.services.on_ice_service import OnIceService

def test_line_reconstruction_shift_boundaries(app, db):
    """
    Verifies that LineService uses the same active-player logic as OnIceService at boundaries.
    Test:
      Player A shift: [600, 640)
      Player B shift: [640, 680)
    Expected:
      t = 639 -> Player A is active, Player B is inactive
      t = 640 -> Player B is active, Player A is inactive
    Also verifies that a line change occurring exactly at a shift boundary resolves correctly.
    """
    # 1. Seed Teams
    team1 = Team(team_id=1, name="Flames", abbreviation="CGY")
    team2 = Team(team_id=2, name="Jets", abbreviation="WPG")
    db.session.add_all([team1, team2])
    db.session.commit()

    # 2. Seed Game
    game = Game(
        game_id=850,
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

    # 3. Seed Skaters
    # Home forwards: 101, 102, 103 (active [0, 640)), 107 (active [640, 1000))
    # Home defense: 104, 105 (active [0, 1000))
    # Player 103 and 107 are switching at t=640
    p1 = Player(player_id=101, first_name="P1", last_name="Home", position="LW", current_team_id=1)
    p2 = Player(player_id=102, first_name="P2", last_name="Home", position="C", current_team_id=1)
    p3 = Player(player_id=103, first_name="P3", last_name="Home", position="RW", current_team_id=1)
    p4 = Player(player_id=104, first_name="D1", last_name="Home", position="D", current_team_id=1)
    p5 = Player(player_id=105, first_name="D2", last_name="Home", position="D", current_team_id=1)
    p7 = Player(player_id=107, first_name="P4", last_name="Home", position="RW", current_team_id=1)
    db.session.add_all([p1, p2, p3, p4, p5, p7])
    db.session.commit()

    # 4. Seed Roster Spots
    gps = [
        GamePlayer(game_id=850, player_id=101, team_id=1, position="LW"),
        GamePlayer(game_id=850, player_id=102, team_id=1, position="C"),
        GamePlayer(game_id=850, player_id=103, team_id=1, position="RW"),
        GamePlayer(game_id=850, player_id=104, team_id=1, position="D"),
        GamePlayer(game_id=850, player_id=105, team_id=1, position="D"),
        GamePlayer(game_id=850, player_id=107, team_id=1, position="RW")
    ]
    db.session.add_all(gps)
    db.session.commit()

    # 5. Seed Shifts
    s1 = Shift(shift_id="s1", game_id=850, player_id=101, team_id=1, period=1, start_time="00:00", end_time="16:40", start_elapsed_seconds=0, end_elapsed_seconds=1000, duration=1000)
    s2 = Shift(shift_id="s2", game_id=850, player_id=102, team_id=1, period=1, start_time="00:00", end_time="16:40", start_elapsed_seconds=0, end_elapsed_seconds=1000, duration=1000)
    # Player A: [600, 640)
    s3 = Shift(shift_id="s3", game_id=850, player_id=103, team_id=1, period=1, start_time="10:00", end_time="10:40", start_elapsed_seconds=600, end_elapsed_seconds=640, duration=40)
    # Player B: [640, 680)
    s7 = Shift(shift_id="s7", game_id=850, player_id=107, team_id=1, period=1, start_time="10:40", end_time="11:20", start_elapsed_seconds=640, end_elapsed_seconds=680, duration=40)
    
    # Defensemen
    s4 = Shift(shift_id="s4", game_id=850, player_id=104, team_id=1, period=1, start_time="00:00", end_time="16:40", start_elapsed_seconds=0, end_elapsed_seconds=1000, duration=1000)
    s5 = Shift(shift_id="s5", game_id=850, player_id=105, team_id=1, period=1, start_time="00:00", end_time="16:40", start_elapsed_seconds=0, end_elapsed_seconds=1000, duration=1000)

    db.session.add_all([s1, s2, s3, s7, s4, s5])
    db.session.commit()

    # 6. Verify OnIceService directly
    active_639 = OnIceService.filter_active_shifts([s3, s7], elapsed_seconds=639)
    assert len(active_639) == 1
    assert active_639[0].player_id == 103

    active_640 = OnIceService.filter_active_shifts([s3, s7], elapsed_seconds=640)
    assert len(active_640) == 1
    assert active_640[0].player_id == 107

    # 7. Add event exactly at boundary: Goal at 640s
    e1 = Event(event_id="e_b1", game_id=850, period=1, period_time="10:40", elapsed_game_seconds=640, event_type="goal", team_id=1, primary_player_id=101, manpower_state="EV")
    db.session.add(e1)
    db.session.commit()
    shot1 = Shot(shot_id="e_b1", game_id=850, team_id=1, shooter_id=101, goalie_id=None, x_coordinate=80.0, y_coordinate=5.0, distance=10.0, angle=5.0, outcome="Goal", shot_type="wrist", goal=True)
    db.session.add(shot1)
    db.session.commit()

    # 8. Run combinations calculation
    combos = LineService.get_line_combinations(850)
    home_lines = combos["home"]["lines"]

    # Since Player 103 is on [600, 640) and Player 107 is on [640, 680)
    # Forward line 1: (101, 102, 103) -> Active for 40 seconds (from 600 to 639)
    # Forward line 2: (101, 102, 107) -> Active for 40 seconds (from 640 to 679)
    # The goal at t=640 should belong exclusively to the new line (101, 102, 107)
    line1 = next((line for line in home_lines if 103 in line["player_ids"]), None)
    line2 = next((line for line in home_lines if 107 in line["player_ids"]), None)

    assert line1 is not None
    assert line1["toi_seconds"] == 40
    assert line1["goals_for"] == 0

    assert line2 is not None
    assert line2["toi_seconds"] == 40
    assert line2["goals_for"] == 1
