import pytest
from datetime import date
from app.models import db, Team, Player, Game, Event, Shot, Shift, GamePlayer
from app.services.goalie_season_service import GoalieSeasonService

def test_goalie_season_aggregation_deterministic(app, db):
    """
    Verify xGA, GA, GSAx, expected save %, and empty-net exclusion.
    """
    team = Team(team_id=1, abbreviation='CGY', name='Calgary Flames')
    goalie = Player(player_id=25, first_name='Jacob', last_name='Markstrom', position='G')
    shooter = Player(player_id=99, first_name='Opponent', last_name='Shooter', position='F')
    db.session.add_all([team, goalie, shooter])
    db.session.commit()

    g = Game(
        game_id=2024020005, season='20242025', game_date=date(2024, 10, 12),
        game_type='R', home_team_id=1, away_team_id=1, home_score=2, away_score=3,
        nhl_game_state='FINAL'
    )
    db.session.add(g)
    db.session.flush()

    gp = GamePlayer(game_id=g.game_id, player_id=25, team_id=1, position='G')
    shift = Shift(shift_id='s_g', game_id=g.game_id, player_id=25, period=1, start_time='00:00',
                  end_time='20:00', start_elapsed_seconds=0, end_elapsed_seconds=3600, duration=3600, team_id=1)

    # Shots faced by Markstrom:
    # Shot 1: Goal against, xG = 0.20, empty_net = False
    # Shot 2: Saved, xG = 0.35, empty_net = False
    # Shot 3: Saved, xG = 0.15, empty_net = False
    # Shot 4: Saved, xG = 0.10, empty_net = False
    # Shot 5: Empty Net Goal! (Markstrom was pulled, goalie_id=25 or None, empty_net = True) -> MUST BE EXCLUDED from xGA/GSAx!
    ev1 = Event(event_id='e1', game_id=g.game_id, period=1, period_time='05:00', event_type='goal', team_id=1)
    sh1 = Shot(shot_id='e1', game_id=g.game_id, team_id=1, shooter_id=99, goalie_id=25, outcome='Goal', goal=True, xg=0.20, empty_net=False)

    ev2 = Event(event_id='e2', game_id=g.game_id, period=1, period_time='10:00', event_type='shot-on-goal', team_id=1)
    sh2 = Shot(shot_id='e2', game_id=g.game_id, team_id=1, shooter_id=99, goalie_id=25, outcome='Saved', goal=False, xg=0.35, empty_net=False)

    ev3 = Event(event_id='e3', game_id=g.game_id, period=2, period_time='05:00', event_type='shot-on-goal', team_id=1)
    sh3 = Shot(shot_id='e3', game_id=g.game_id, team_id=1, shooter_id=99, goalie_id=25, outcome='Saved', goal=False, xg=0.15, empty_net=False)

    ev4 = Event(event_id='e4', game_id=g.game_id, period=3, period_time='10:00', event_type='shot-on-goal', team_id=1)
    sh4 = Shot(shot_id='e4', game_id=g.game_id, team_id=1, shooter_id=99, goalie_id=25, outcome='Saved', goal=False, xg=0.10, empty_net=False)

    # Empty net goal
    ev5 = Event(event_id='e5', game_id=g.game_id, period=3, period_time='19:50', event_type='goal', team_id=1)
    sh5 = Shot(shot_id='e5', game_id=g.game_id, team_id=1, shooter_id=99, goalie_id=25, outcome='Goal', goal=True, xg=0.90, empty_net=True)

    db.session.add_all([gp, shift, ev1, sh1, ev2, sh2, ev3, sh3, ev4, sh4, ev5, sh5])
    db.session.commit()

    stats = GoalieSeasonService.get_goalie_season_stats(goalie_id=25, season='20242025')
    assert stats is not None
    assert stats["gp"] == 1
    assert stats["shots_faced"] == 5  # Total SOG (including EN)
    assert stats["goals_against"] == 2  # 1 regular + 1 EN

    # xGA MUST EXCLUDE the empty net goal (0.90)!
    # xGA = 0.20 + 0.35 + 0.15 + 0.10 = 0.80
    assert pytest.approx(stats["xga"], 0.01) == 0.80

    # GSAx = xGA - Non-Empty-Net GA = 0.80 - 1 = -0.20
    assert pytest.approx(stats["gsax"], 0.01) == -0.20

    # TOI: 3600s = 60 mins = 1.0 hour
    assert stats["toi_seconds"] == 3600
    assert stats["toi_formatted"] == "60:00"
    assert pytest.approx(stats["gsax_per_60"], 0.01) == -0.20

    # Expected save % on shots faced
    # Non-empty net shots = 4. (4 - 0.80) / 4 = 80.00%
    assert pytest.approx(stats["expected_save_pct"], 0.1) == 80.00


def test_goalie_leaderboards_and_thresholds(app, db):
    """
    Verify goalie leaderboards sort properly by GSAx and respect sample filters.
    """
    team = Team(team_id=1, abbreviation='CGY', name='Calgary Flames')
    g1 = Player(player_id=31, first_name='Star', last_name='Goalie', position='G')
    g2 = Player(player_id=32, first_name='Backup', last_name='Goalie', position='G')
    shooter = Player(player_id=99, first_name='Shooter', last_name='One', position='F')
    db.session.add_all([team, g1, g2, shooter])
    db.session.commit()

    game = Game(
        game_id=2024020006, season='20242025', game_date=date(2024, 10, 14),
        game_type='R', home_team_id=1, away_team_id=1, home_score=2, away_score=1,
        nhl_game_state='FINAL'
    )
    db.session.add(game)
    db.session.flush()

    gp1 = GamePlayer(game_id=game.game_id, player_id=31, team_id=1, position='G')
    gp2 = GamePlayer(game_id=game.game_id, player_id=32, team_id=1, position='G')

    # g1 faced 5 shots with 1.5 xGA, allowed 0 goals -> GSAx = +1.50
    # g2 faced 1 shot with 0.1 xGA, allowed 0 goals -> GSAx = +0.10
    ev1 = Event(event_id='g1_ev', game_id=game.game_id, period=1, period_time='05:00', event_type='shot-on-goal', team_id=1)
    sh1 = Shot(shot_id='g1_ev', game_id=game.game_id, team_id=1, shooter_id=99, goalie_id=31, outcome='Saved', goal=False, xg=1.50, empty_net=False)

    ev2 = Event(event_id='g2_ev', game_id=game.game_id, period=2, period_time='05:00', event_type='shot-on-goal', team_id=1)
    sh2 = Shot(shot_id='g2_ev', game_id=game.game_id, team_id=1, shooter_id=99, goalie_id=32, outcome='Saved', goal=False, xg=0.10, empty_net=False)

    db.session.add_all([gp1, gp2, ev1, sh1, ev2, sh2])
    db.session.commit()

    leaderboard = GoalieSeasonService.get_goalie_leaderboards('20242025', sort_by='gsax', min_shots_faced=0)
    assert len(leaderboard) == 2
    assert leaderboard[0]["player_id"] == 31
    assert leaderboard[0]["rank"] == 1
    assert leaderboard[0]["gsax"] == 1.50
    assert leaderboard[1]["player_id"] == 32
    assert leaderboard[1]["rank"] == 2
