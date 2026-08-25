import pytest
from datetime import date
from app.models import Game, Team, Player, Shift, Event, Shot, GamePlayer
from app.services.possession_service import PossessionService

def test_empty_possession_metrics(app, db):
    """
    Verifies that empty possession samples (CF+CA=0, FF+FA=0) return None (undefined),
    while a true 0% (CF=0, CA=5) returns 0%.
    """
    # 1. Seed Teams
    team1 = Team(team_id=1, name="Home", abbreviation="HOM")
    team2 = Team(team_id=2, name="Away", abbreviation="AWA")
    db.session.add_all([team1, team2])
    db.session.commit()

    # 2. Seed Players
    p_h1 = Player(player_id=10, first_name="Skater", last_name="H1", position="C", current_team_id=1)
    p_a1 = Player(player_id=20, first_name="Skater", last_name="A1", position="LW", current_team_id=2)
    db.session.add_all([p_h1, p_a1])
    db.session.commit()

    # 3. Seed Game
    game = Game(
        game_id=3001,
        season="20232024",
        game_date=date(2023, 11, 1),
        game_type="R",
        home_team_id=1,
        away_team_id=2,
        game_status="Final"
    )
    db.session.add(game)
    db.session.commit()

    # 4. Seed Shifts (both on ice)
    s1 = Shift(shift_id="s10", game_id=3001, player_id=10, team_id=1, period=1, start_time="00:00", end_time="10:00", start_elapsed_seconds=0, end_elapsed_seconds=600, duration=600)
    s2 = Shift(shift_id="s20", game_id=3001, player_id=20, team_id=2, period=1, start_time="00:00", end_time="10:00", start_elapsed_seconds=0, end_elapsed_seconds=600, duration=600)
    db.session.add_all([s1, s2])
    db.session.commit()

    # Case A: No shot events at all. Denominators are zero.
    pos_empty = PossessionService.calculate_possession_stats(3001, mode="All")
    assert 10 in pos_empty
    assert pos_empty[10]["cf_pct"] is None
    assert pos_empty[10]["ff_pct"] is None

    # Case B: Seed shot attempts against Home player (CA = 5, CF = 0). True 0%.
    for i in range(5):
        e = Event(
            event_id=f"e_{i}",
            game_id=3001,
            period=1,
            period_time="05:00",
            elapsed_game_seconds=300,
            event_type="shot-on-goal",
            team_id=2,  # Away team takes shot (against Home player)
            primary_player_id=20
        )
        db.session.add(e)
        sh = Shot(
            shot_id=f"e_{i}",
            game_id=3001,
            team_id=2,
            shooter_id=20,
            outcome="Saved",
            x_coordinate=55.0,
            y_coordinate=10.0,
            distance=30.0,
            angle=15.0,
            goal=False,
            empty_net=False,
            xg=0.05
        )
        db.session.add(sh)
    db.session.commit()

    pos_zero = PossessionService.calculate_possession_stats(3001, mode="All")
    assert 10 in pos_zero
    assert pos_zero[10]["cf"] == 0
    assert pos_zero[10]["ca"] == 5
    assert pos_zero[10]["cf_pct"] == 0.0
    assert pos_zero[10]["ff_pct"] == 0.0


def test_empty_possession_ui_rendering(client, db):
    """
    Verifies that undefined possession percentages are rendered as N/A in the HTML UI,
    and are not shown as None%, 0%, or 50.0%.
    """
    # 1. Seed Teams
    team1 = Team(team_id=1, name="Home", abbreviation="HOM")
    team2 = Team(team_id=2, name="Away", abbreviation="AWA")
    db.session.add_all([team1, team2])
    db.session.commit()

    # 2. Seed Players
    p_h1 = Player(player_id=10, first_name="Skater", last_name="H1", position="C", current_team_id=1)
    p_a1 = Player(player_id=20, first_name="Skater", last_name="A1", position="LW", current_team_id=2)
    db.session.add_all([p_h1, p_a1])
    db.session.commit()

    # 3. Seed Game
    game = Game(
        game_id=3001,
        season="20232024",
        game_date=date(2023, 11, 1),
        game_type="R",
        home_team_id=1,
        away_team_id=2,
        game_status="Final"
    )
    db.session.add(game)
    db.session.commit()

    # 4. Seed Shifts (both on ice)
    s1 = Shift(shift_id="s10", game_id=3001, player_id=10, team_id=1, period=1, start_time="00:00", end_time="10:00", start_elapsed_seconds=0, end_elapsed_seconds=600, duration=600)
    s2 = Shift(shift_id="s20", game_id=3001, player_id=20, team_id=2, period=1, start_time="00:00", end_time="10:00", start_elapsed_seconds=0, end_elapsed_seconds=600, duration=600)
    db.session.add_all([s1, s2])
    db.session.commit()

    # Seed GamePlayer roster records
    gps = [
        GamePlayer(game_id=3001, player_id=10, team_id=1, position="C"),
        GamePlayer(game_id=3001, player_id=20, team_id=2, position="LW")
    ]
    db.session.add_all(gps)
    db.session.commit()

    # Request game overview
    resp_game = client.get("/game/3001")
    assert resp_game.status_code == 200
    # The game page should contain N/A for CF% and FF%
    assert b"N/A" in resp_game.data
    assert b"None%" not in resp_game.data

    # Request player game page
    resp_player = client.get("/game/3001/player/10")
    assert resp_player.status_code == 200
    # Should render N/A for Corsi and Fenwick cards
    assert b"N/A" in resp_player.data
    assert b"None%" not in resp_player.data
    assert b"50.0% CF" not in resp_player.data
    assert b"50.0% FF" not in resp_player.data
