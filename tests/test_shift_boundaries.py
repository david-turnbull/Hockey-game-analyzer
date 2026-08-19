import pytest
from datetime import date
from app.models import Game, Team, Player, Shift
from app.services.on_ice_service import OnIceService

def test_shift_change_boundaries(app, db):
    """
    Verifies that shift time boundaries use the half-open interval [start, end)
    so that overlapping seconds at shift changes do not count both players as on-ice.
    """
    # 1. Seed Teams and Players
    team = Team(team_id=1, name="Test Team", abbreviation="TST")
    db.session.add(team)
    db.session.commit()

    player_a = Player(player_id=101, first_name="Player", last_name="A", position="C", current_team_id=1)
    player_b = Player(player_id=102, first_name="Player", last_name="B", position="LW", current_team_id=1)
    db.session.add_all([player_a, player_b])
    db.session.commit()

    # 2. Seed Game
    game = Game(
        game_id=3001,
        season="20232024",
        game_date=date(2023, 10, 15),
        game_type="R",
        home_team_id=1,
        away_team_id=1,
        game_status="Final"
    )
    db.session.add(game)
    db.session.commit()

    # 3. Seed shifts: Player A [600, 640), Player B [640, 675)
    s_a = Shift(
        shift_id="shift_a",
        game_id=3001,
        player_id=101,
        team_id=1,
        period=1,
        start_time="10:00",
        end_time="10:40",
        start_elapsed_seconds=600,
        end_elapsed_seconds=640,
        duration=40
    )
    s_b = Shift(
        shift_id="shift_b",
        game_id=3001,
        player_id=102,
        team_id=1,
        period=1,
        start_time="10:40",
        end_time="11:15",
        start_elapsed_seconds=640,
        end_elapsed_seconds=675,
        duration=35
    )
    db.session.add_all([s_a, s_b])
    db.session.commit()

    # 4. Verify boundaries with OnIceService
    # At t = 639 (1 second before change), Player A is on ice, Player B is not
    on_ice_639 = OnIceService.get_players_on_ice(3001, 639)
    ids_639 = [p["player_id"] for p in on_ice_639]
    assert 101 in ids_639
    assert 102 not in ids_639

    # At t = 640 (exact change time), Player B is on ice, Player A is NOT
    on_ice_640 = OnIceService.get_players_on_ice(3001, 640)
    ids_640 = [p["player_id"] for p in on_ice_640]
    assert 102 in ids_640
    assert 101 not in ids_640  # Crucial: Player A is off the ice at t = 640

    # At t = 641 (1 second after change), Player B is on ice, Player A is not
    on_ice_641 = OnIceService.get_players_on_ice(3001, 641)
    ids_641 = [p["player_id"] for p in on_ice_641]
    assert 102 in ids_641
    assert 101 not in ids_641
