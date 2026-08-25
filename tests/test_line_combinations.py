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
    p_a_f1 = Player(
    player_id=201,
    first_name="F1",
    last_name="Away",
    position="LW",
    current_team_id=2,
    )  
    p_a_f2 = Player(
        player_id=202,
        first_name="F2",
        last_name="Away",
        position="C",
        current_team_id=2,
    )
    p_a_f3 = Player(
        player_id=203,
        first_name="F3",
        last_name="Away",
        position="RW",
        current_team_id=2,
    )
    p_a_d1 = Player(
        player_id=204,
        first_name="D1",
        last_name="Away",
        position="D",
        current_team_id=2,
    )
    p_a_d2 = Player(
        player_id=205,
        first_name="D2",
        last_name="Away",
        position="D",
        current_team_id=2,
    )
    p_a_g = Player(
        player_id=206,
        first_name="G1",
        last_name="Away",
        position="G",
        current_team_id=2,
    )

    db.session.add_all([
        p_a_f1,
        p_a_f2,
        p_a_f3,
        p_a_d1,
        p_a_d2,
        p_a_g,
    ])
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
    s_af1 = Shift(shift_id="sh_af1", game_id=800, player_id=201, team_id=2, period=1, start_time="00:00", end_time="01:40", start_elapsed_seconds=0, end_elapsed_seconds=100, duration=100)
    s_af2 = Shift(shift_id="sh_af2", game_id=800, player_id=202, team_id=2, period=1, start_time="00:00", end_time="01:40", start_elapsed_seconds=0, end_elapsed_seconds=100, duration=100)
    s_af3 = Shift(shift_id="sh_af3", game_id=800, player_id=203, team_id=2, period=1, start_time="00:00", end_time="01:40", start_elapsed_seconds=0, end_elapsed_seconds=100, duration=100)
    s_ad1 = Shift(shift_id="sh_ad1", game_id=800, player_id=204, team_id=2, period=1, start_time="00:00", end_time="01:40", start_elapsed_seconds=0, end_elapsed_seconds=100, duration=100)
    s_ad2 = Shift(shift_id="sh_ad2", game_id=800, player_id=205, team_id=2, period=1, start_time="00:00", end_time="01:40", start_elapsed_seconds=0, end_elapsed_seconds=100, duration=100)
    s_ag = Shift(shift_id="sh_ag", game_id=800, player_id=206, team_id=2, period=1, start_time="00:00", end_time="01:40", start_elapsed_seconds=0, end_elapsed_seconds=100, duration=100)
    
    db.session.add_all([s_f1, s_f2, s_f3, s_d1, s_d2, s_g, s_af1, s_af2, s_af3, s_ad1, s_ad2, s_ag])
    db.session.commit()
    
    # Seed GamePlayer roster records
    gps = [
        GamePlayer(game_id=800, player_id=101, team_id=1, position="LW"),
        GamePlayer(game_id=800, player_id=102, team_id=1, position="C"),
        GamePlayer(game_id=800, player_id=103, team_id=1, position="RW"),
        GamePlayer(game_id=800, player_id=104, team_id=1, position="D"),
        GamePlayer(game_id=800, player_id=105, team_id=1, position="D"),
        GamePlayer(game_id=800, player_id=106, team_id=1, position="G"),
        GamePlayer(game_id=800, player_id=201, team_id=2, position="LW"),
        GamePlayer(game_id=800, player_id=202, team_id=2, position="C"),
        GamePlayer(game_id=800, player_id=203, team_id=2, position="RW"),
        GamePlayer(game_id=800, player_id=204, team_id=2, position="D"),
        GamePlayer(game_id=800, player_id=205, team_id=2, position="D"),
        GamePlayer(game_id=800, player_id=206, team_id=2, position="G"),
    ]
    db.session.add_all(gps)
    db.session.commit()
    
    # 5. Add a shot and a goal event at 50 seconds (while line and pairing are on ice)
    # Event 1: Goal by Home team at 50s
    e1 = Event(event_id="e_g1", game_id=800, period=1, period_time="00:50", elapsed_game_seconds=50, event_type="goal", team_id=1, primary_player_id=101, manpower_state="EV")
    db.session.add(e1)
    db.session.commit()
    shot1 = Shot(shot_id="e_g1", game_id=800, team_id=1, shooter_id=101, goalie_id=206, x_coordinate=80.0, y_coordinate=5.0, distance=10.0, angle=5.0, outcome="Goal", shot_type="wrist", goal=True)
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
    
    # Assert Away 5v5 line and pairing receive against-stat attribution
    away_lines = combos["away"]["lines"]
    assert len(away_lines) == 1
    assert away_lines[0]["toi_seconds"] == 100
    assert away_lines[0]["goals_for"] == 0
    assert away_lines[0]["goals_against"] == 1
    assert away_lines[0]["sog_against"] == 1

    away_pairings = combos["away"]["pairings"]
    assert len(away_pairings) == 1
    assert away_pairings[0]["toi_seconds"] == 100
    assert away_pairings[0]["goals_against"] == 1

def test_forward_line_minimum_toi_boundary_59_excluded_60_included(app, db):
    """A 59-second true-5v5 forward trio is excluded; a 60-second trio is included."""
    home = Team(team_id=3, name="Home", abbreviation="HOM")
    away = Team(team_id=4, name="Away", abbreviation="AWA")
    db.session.add_all([home, away])

    players = [
        Player(player_id=301, first_name="F1", last_name="Home", position="LW", current_team_id=3),
        Player(player_id=302, first_name="F2", last_name="Home", position="C", current_team_id=3),
        Player(player_id=303, first_name="F3", last_name="Home", position="RW", current_team_id=3),
        Player(player_id=307, first_name="F4", last_name="Home", position="RW", current_team_id=3),
        Player(player_id=304, first_name="D1", last_name="Home", position="D", current_team_id=3),
        Player(player_id=305, first_name="D2", last_name="Home", position="D", current_team_id=3),
        Player(player_id=306, first_name="G1", last_name="Home", position="G", current_team_id=3),
        Player(player_id=401, first_name="F1", last_name="Away", position="LW", current_team_id=4),
        Player(player_id=402, first_name="F2", last_name="Away", position="C", current_team_id=4),
        Player(player_id=403, first_name="F3", last_name="Away", position="RW", current_team_id=4),
        Player(player_id=404, first_name="D1", last_name="Away", position="D", current_team_id=4),
        Player(player_id=405, first_name="D2", last_name="Away", position="D", current_team_id=4),
        Player(player_id=406, first_name="G1", last_name="Away", position="G", current_team_id=4),
    ]
    db.session.add_all(players)

    game = Game(
        game_id=801,
        season="20232024",
        game_date=date(2023, 10, 21),
        game_type="R",
        home_team_id=3,
        away_team_id=4,
        home_score=0,
        away_score=0,
        game_status="Final"
    )
    db.session.add(game)
    db.session.flush()

    gps = [
        GamePlayer(game_id=801, player_id=301, team_id=3, position="LW"),
        GamePlayer(game_id=801, player_id=302, team_id=3, position="C"),
        GamePlayer(game_id=801, player_id=303, team_id=3, position="RW"),
        GamePlayer(game_id=801, player_id=307, team_id=3, position="RW"),
        GamePlayer(game_id=801, player_id=304, team_id=3, position="D"),
        GamePlayer(game_id=801, player_id=305, team_id=3, position="D"),
        GamePlayer(game_id=801, player_id=306, team_id=3, position="G"),
        GamePlayer(game_id=801, player_id=401, team_id=4, position="LW"),
        GamePlayer(game_id=801, player_id=402, team_id=4, position="C"),
        GamePlayer(game_id=801, player_id=403, team_id=4, position="RW"),
        GamePlayer(game_id=801, player_id=404, team_id=4, position="D"),
        GamePlayer(game_id=801, player_id=405, team_id=4, position="D"),
        GamePlayer(game_id=801, player_id=406, team_id=4, position="G"),
    ]
    db.session.add_all(gps)

    def shift(shift_id, player_id, team_id, start, end):
        return Shift(
            shift_id=shift_id,
            game_id=801,
            player_id=player_id,
            team_id=team_id,
            period=1,
            start_time="00:00",
            end_time="01:59",
            start_elapsed_seconds=start,
            end_elapsed_seconds=end,
            duration=end - start
        )

    shifts = [
        # Shared home players.
        shift("b_h_f1", 301, 3, 0, 119),
        shift("b_h_f2", 302, 3, 0, 119),
        shift("b_h_d1", 304, 3, 0, 119),
        shift("b_h_d2", 305, 3, 0, 119),
        shift("b_h_g", 306, 3, 0, 119),

        # 59-second trio then 60-second trio.
        shift("b_h_f3", 303, 3, 0, 59),
        shift("b_h_f4", 307, 3, 59, 119),

        # Complete away 5v5 unit for the whole interval.
        shift("b_a_f1", 401, 4, 0, 119),
        shift("b_a_f2", 402, 4, 0, 119),
        shift("b_a_f3", 403, 4, 0, 119),
        shift("b_a_d1", 404, 4, 0, 119),
        shift("b_a_d2", 405, 4, 0, 119),
        shift("b_a_g", 406, 4, 0, 119),
    ]
    db.session.add_all(shifts)
    db.session.commit()

    combos = LineService.get_line_combinations(801)
    home_lines = combos["home"]["lines"]

    excluded_59 = next((line for line in home_lines if 303 in line["player_ids"]), None)
    included_60 = next((line for line in home_lines if 307 in line["player_ids"]), None)

    assert excluded_59 is None
    assert included_60 is not None
    assert included_60["toi_seconds"] == 60
    assert included_60["toi"] == "01:00"
