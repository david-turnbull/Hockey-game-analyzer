import pytest
from datetime import date
from app.models import Game, Team, Player, Shift, GamePlayer, Event, Shot
from app.services.unit_service import UnitService
from app.services.on_ice_service import OnIceService

def test_line_reconstruction_shift_boundaries(app, db):
    """
    Verifies that UnitService uses the same active-player logic as OnIceService at boundaries.
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
    # Home forwards 103 and 107 alternate for exactly 60 seconds each.
    # Home defense: 104, 105 (active [0, 1000))
    # Player 103 and 107 switch at t=660 using half-open intervals.
    p1 = Player(player_id=101, first_name="P1", last_name="Home", position="LW", current_team_id=1)
    p2 = Player(player_id=102, first_name="P2", last_name="Home", position="C", current_team_id=1)
    p3 = Player(player_id=103, first_name="P3", last_name="Home", position="RW", current_team_id=1)
    p4 = Player(player_id=104, first_name="D1", last_name="Home", position="D", current_team_id=1)
    p5 = Player(player_id=105, first_name="D2", last_name="Home", position="D", current_team_id=1)
    p7 = Player(player_id=107, first_name="P4", last_name="Home", position="RW", current_team_id=1)
    p6 = Player(player_id=106, first_name="G1", last_name="Home", position="G", current_team_id=1)
    a1 = Player(player_id=201, first_name="A1", last_name="Away", position="LW", current_team_id=2)
    a2 = Player(player_id=202, first_name="A2", last_name="Away", position="C", current_team_id=2)
    a3 = Player(player_id=203, first_name="A3", last_name="Away", position="RW", current_team_id=2)
    ad1 = Player(player_id=204, first_name="AD1", last_name="Away", position="D", current_team_id=2)
    ad2 = Player(player_id=205, first_name="AD2", last_name="Away", position="D", current_team_id=2)
    ag = Player(player_id=206, first_name="AG", last_name="Away", position="G", current_team_id=2)
    db.session.add_all([p1, p2, p3, p4, p5, p6, p7, a1, a2, a3, ad1, ad2, ag])
    db.session.commit()

    # 4. Seed Roster Spots
    gps = [
        GamePlayer(game_id=850, player_id=101, team_id=1, position="LW"),
        GamePlayer(game_id=850, player_id=102, team_id=1, position="C"),
        GamePlayer(game_id=850, player_id=103, team_id=1, position="RW"),
        GamePlayer(game_id=850, player_id=104, team_id=1, position="D"),
        GamePlayer(game_id=850, player_id=105, team_id=1, position="D"),
        GamePlayer(game_id=850, player_id=106, team_id=1, position="G"),
        GamePlayer(game_id=850, player_id=107, team_id=1, position="RW"),
        GamePlayer(game_id=850, player_id=201, team_id=2, position="LW"),
        GamePlayer(game_id=850, player_id=202, team_id=2, position="C"),
        GamePlayer(game_id=850, player_id=203, team_id=2, position="RW"),
        GamePlayer(game_id=850, player_id=204, team_id=2, position="D"),
        GamePlayer(game_id=850, player_id=205, team_id=2, position="D"),
        GamePlayer(game_id=850, player_id=206, team_id=2, position="G")
    ]
    db.session.add_all(gps)
    db.session.commit()

    # 5. Seed Shifts
    s1 = Shift(shift_id="s1", game_id=850, player_id=101, team_id=1, period=1, start_time="00:00", end_time="16:40", start_elapsed_seconds=0, end_elapsed_seconds=1000, duration=1000)
    s2 = Shift(shift_id="s2", game_id=850, player_id=102, team_id=1, period=1, start_time="00:00", end_time="16:40", start_elapsed_seconds=0, end_elapsed_seconds=1000, duration=1000)
    # Player A: [600, 660)
    s3 = Shift(shift_id="s3", game_id=850, player_id=103, team_id=1, period=1, start_time="10:00", end_time="11:00", start_elapsed_seconds=600, end_elapsed_seconds=660, duration=60)
    # Player B: [660, 720)
    s7 = Shift(shift_id="s7", game_id=850, player_id=107, team_id=1, period=1, start_time="11:00", end_time="12:00", start_elapsed_seconds=660, end_elapsed_seconds=720, duration=60)
    
    # Defensemen
    s4 = Shift(shift_id="s4", game_id=850, player_id=104, team_id=1, period=1, start_time="00:00", end_time="16:40", start_elapsed_seconds=0, end_elapsed_seconds=1000, duration=1000)
    s5 = Shift(shift_id="s5", game_id=850, player_id=105, team_id=1, period=1, start_time="00:00", end_time="16:40", start_elapsed_seconds=0, end_elapsed_seconds=1000, duration=1000)
    s6 = Shift(shift_id="s6", game_id=850, player_id=106, team_id=1, period=1, start_time="00:00", end_time="16:40", start_elapsed_seconds=0, end_elapsed_seconds=1000, duration=1000)

    # Complete away 5v5 unit throughout the tested interval.
    sa1 = Shift(shift_id="sa1", game_id=850, player_id=201, team_id=2, period=1, start_time="00:00", end_time="16:40", start_elapsed_seconds=0, end_elapsed_seconds=1000, duration=1000)
    sa2 = Shift(shift_id="sa2", game_id=850, player_id=202, team_id=2, period=1, start_time="00:00", end_time="16:40", start_elapsed_seconds=0, end_elapsed_seconds=1000, duration=1000)
    sa3 = Shift(shift_id="sa3", game_id=850, player_id=203, team_id=2, period=1, start_time="00:00", end_time="16:40", start_elapsed_seconds=0, end_elapsed_seconds=1000, duration=1000)
    sad1 = Shift(shift_id="sad1", game_id=850, player_id=204, team_id=2, period=1, start_time="00:00", end_time="16:40", start_elapsed_seconds=0, end_elapsed_seconds=1000, duration=1000)
    sad2 = Shift(shift_id="sad2", game_id=850, player_id=205, team_id=2, period=1, start_time="00:00", end_time="16:40", start_elapsed_seconds=0, end_elapsed_seconds=1000, duration=1000)
    sag = Shift(shift_id="sag", game_id=850, player_id=206, team_id=2, period=1, start_time="00:00", end_time="16:40", start_elapsed_seconds=0, end_elapsed_seconds=1000, duration=1000)

    db.session.add_all([s1, s2, s3, s7, s4, s5, s6, sa1, sa2, sa3, sad1, sad2, sag])
    db.session.commit()

    # 6. Verify OnIceService directly
    active_659 = OnIceService.filter_active_shifts([s3, s7], elapsed_seconds=659)
    assert len(active_659) == 1
    assert active_659[0].player_id == 103

    active_660 = OnIceService.filter_active_shifts([s3, s7], elapsed_seconds=660)
    assert len(active_660) == 1
    assert active_660[0].player_id == 107

    # 7. Add event exactly at boundary: Goal at 660s
    e1 = Event(event_id="e_b1", game_id=850, period=1, period_time="11:00", elapsed_game_seconds=660, event_type="goal", team_id=1, primary_player_id=101, manpower_state="EV")
    db.session.add(e1)
    db.session.commit()
    shot1 = Shot(shot_id="e_b1", game_id=850, team_id=1, shooter_id=101, goalie_id=206, x_coordinate=80.0, y_coordinate=5.0, distance=10.0, angle=5.0, outcome="Goal", shot_type="wrist", goal=True)
    db.session.add(shot1)
    db.session.commit()

    # 8. Run combinations calculation
    combos = UnitService.get_unit_combinations(850)
    home_lines = combos["home"]["lines"]

    # Player 103 is active on [600, 660); Player 107 is active on [660, 720).
    # Each true-5v5 forward line therefore has exactly 60 seconds of TOI.
    # The goal at t=660 belongs exclusively to the new line (101, 102, 107).
    line1 = next((line for line in home_lines if 103 in line["player_ids"]), None)
    line2 = next((line for line in home_lines if 107 in line["player_ids"]), None)

    assert line1 is not None
    assert line1["toi_seconds"] == 60
    assert line1["goals_for"] == 0

    assert line2 is not None
    assert line2["toi_seconds"] == 60
    assert line2["goals_for"] == 1