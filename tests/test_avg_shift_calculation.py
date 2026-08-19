import pytest
from datetime import date
from app.models import Game, Team, Player, Shift, GamePlayer
from app.services.player_game_service import PlayerGameService

def test_avg_shift_excludes_anomalies(app, db):
    """
    Verifies that average shift duration calculation:
      - uses only valid shifts (not anomalies, not zero duration, not None duration)
      - total TOI = 70 seconds (30s + 40s)
      - valid shift count = 2
      - average shift duration = 35 seconds
    And distinguishes raw shifts count (3) in the returned metrics.
    """
    # 1. Seed Teams
    team1 = Team(team_id=1, name="Flames", abbreviation="CGY")
    db.session.add(team1)
    db.session.commit()

    # 2. Seed Player
    player = Player(player_id=10, first_name="John", last_name="Skater", position="C", current_team_id=1)
    db.session.add(player)
    db.session.commit()

    # 3. Seed Game
    game = Game(
        game_id=4001,
        season="20232024",
        game_date=date(2023, 11, 15),
        game_type="R",
        home_team_id=1,
        away_team_id=1,
        home_score=1,
        away_score=1,
        game_status="Final"
    )
    db.session.add(game)
    db.session.commit()

    # 4. Seed GamePlayer
    gp = GamePlayer(game_id=4001, player_id=10, team_id=1, position="C")
    db.session.add(gp)
    db.session.commit()

    # 5. Seed Shifts
    # Shift 1: 30s (valid)
    s1 = Shift(shift_id="sh1", game_id=4001, player_id=10, team_id=1, period=1, start_time="00:00", end_time="00:30", start_elapsed_seconds=0, end_elapsed_seconds=30, duration=30, is_anomaly=False)
    # Shift 2: 40s (valid)
    s2 = Shift(shift_id="sh2", game_id=4001, player_id=10, team_id=1, period=1, start_time="01:00", end_time="01:40", start_elapsed_seconds=60, end_elapsed_seconds=100, duration=40, is_anomaly=False)
    # Shift 3: 0s (invalid, anomaly)
    s3 = Shift(shift_id="sh3", game_id=4001, player_id=10, team_id=1, period=1, start_time="02:00", end_time="02:00", start_elapsed_seconds=120, end_elapsed_seconds=120, duration=0, is_anomaly=True)
    db.session.add_all([s1, s2, s3])
    db.session.commit()

    # 6. Retrieve Stats
    stats = PlayerGameService.get_player_game_stats(4001, 10)
    assert stats is not None
    assert stats["toi"] == "01:10"  # 70 seconds
    assert stats["shifts_count"] == 2  # valid shifts
    assert stats["raw_shifts_count"] == 3  # raw shifts
    assert stats["avg_shift"] == "00:35"  # 70 / 2 = 35 seconds
