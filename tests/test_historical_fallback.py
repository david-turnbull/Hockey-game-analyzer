import pytest
from datetime import date
from app.models import Game, Team, Player, Shift, Event, GamePlayer
from app.services.player_game_service import PlayerGameService

def test_historical_fallback_hierarchy(app, db):
    """
    Verifies that PlayerGameService follows the safe fallback hierarchy:
      1. GamePlayer authoritative mapping
      2. Game shifts team ID
      3. Game events team ID
      4. Unknown / unresolved (returns None)
    And never silently uses player.current_team_id.
    """
    # 1. Seed Teams
    cgy = Team(team_id=1, name="Calgary Flames", abbreviation="CGY")
    van = Team(team_id=2, name="Vancouver Canucks", abbreviation="VAN")
    db.session.add_all([cgy, van])
    db.session.commit()

    # 2. Seed Game
    game = Game(
        game_id=2001,
        season="20232024",
        game_date=date(2023, 10, 15),
        game_type="R",
        home_team_id=1,  # CGY
        away_team_id=2,  # VAN
        home_score=1,
        away_score=1,
        game_status="Final"
    )
    db.session.add(game)
    db.session.commit()

    # 3. Seed Player 500 (current team is VAN, but historically played for CGY)
    player = Player(
        player_id=500,
        first_name="Test",
        last_name="Attribution",
        position="C",
        shoots_catches="L",
        current_team_id=2  # current_team_id is VAN (2)
    )
    db.session.add(player)
    db.session.commit()

    # Case A: GamePlayer is present (authoritative) -> resolves to CGY (1)
    gp = GamePlayer(game_id=2001, player_id=500, team_id=1, position="C")
    db.session.add(gp)
    db.session.commit()

    stats_a = PlayerGameService.get_player_game_stats(2001, 500)
    assert stats_a is not None
    assert stats_a["team_id"] == 1
    assert stats_a["team_abbrev"] == "CGY"

    # Clean up GamePlayer for next cases
    db.session.delete(gp)
    db.session.commit()

    # Case B: GamePlayer is missing, but valid Shift is present -> resolves to CGY (1)
    s = Shift(
        shift_id="fallback_shift_1",
        game_id=2001,
        player_id=500,
        team_id=1,  # CGY
        period=1,
        start_time="00:00",
        end_time="00:45",
        start_elapsed_seconds=0,
        end_elapsed_seconds=45,
        duration=45
    )
    db.session.add(s)
    db.session.commit()

    stats_b = PlayerGameService.get_player_game_stats(2001, 500)
    assert stats_b is not None
    assert stats_b["team_id"] == 1
    assert stats_b["team_abbrev"] == "CGY"

    # Clean up Shift for next cases
    db.session.delete(s)
    db.session.commit()

    # Case C: GamePlayer & Shifts missing, but Event is present -> resolves to CGY (1)
    e = Event(
        event_id="fallback_event_1",
        game_id=2001,
        period=1,
        period_time="05:00",
        elapsed_game_seconds=300,
        event_type="hit",
        team_id=1,  # CGY
        primary_player_id=500
    )
    db.session.add(e)
    db.session.commit()

    stats_c = PlayerGameService.get_player_game_stats(2001, 500)
    assert stats_c is not None
    assert stats_c["team_id"] == 1
    assert stats_c["team_abbrev"] == "CGY"

    # Clean up Event for next cases
    db.session.delete(e)
    db.session.commit()

    # Case D: All missing -> Unresolved (should return None/Unknown safely)
    stats_d = PlayerGameService.get_player_game_stats(2001, 500)
    assert stats_d is not None
    assert stats_d["team_id"] is None
    assert stats_d["team_abbrev"] == "UNK"
    assert stats_d["team_name"] == "Unknown"
