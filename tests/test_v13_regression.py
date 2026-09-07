import pytest
from datetime import date
from app.models import db, Team, Player, Game, Event, Shot, Shift, GamePlayer
from app.services.team_season_service import TeamSeasonService
from app.services.player_season_service import PlayerSeasonService
from app.services.goalie_season_service import GoalieSeasonService
from app.services.rolling_service import RollingService

@pytest.fixture
def v13_data(app, db):
    """Sets up rich multi-game season fixtures for v1.3 regression testing."""
    cgy = Team(team_id=1, abbreviation='CGY', name='Calgary Flames')
    edm = Team(team_id=2, abbreviation='EDM', name='Edmonton Oilers')
    van = Team(team_id=3, abbreviation='VAN', name='Vancouver Canucks')
    
    skater1 = Player(player_id=101, first_name='Mikael', last_name='Backlund', position='C')
    skater2 = Player(player_id=102, first_name='Connor', last_name='McDavid', position='C')
    goalie1 = Player(player_id=201, first_name='Dustin', last_name='Wolf', position='G')
    goalie2 = Player(player_id=202, first_name='Stuart', last_name='Skinner', position='G')
    
    db.session.add_all([cgy, edm, van, skater1, skater2, goalie1, goalie2])
    db.session.commit()

    # Create 2 games
    g1 = Game(game_id=2024020001, season='20242025', game_date=date(2024, 10, 10),
              game_type='R', home_team_id=1, away_team_id=2, home_score=4, away_score=2,
              nhl_game_state='FINAL')
    g2 = Game(game_id=2024020002, season='20242025', game_date=date(2024, 10, 12),
              game_type='R', home_team_id=2, away_team_id=3, home_score=3, away_score=1,
              nhl_game_state='FINAL')
    db.session.add_all([g1, g2])
    db.session.commit()

    # Roster entries
    gp1 = GamePlayer(game_id=g1.game_id, player_id=101, team_id=1, position='C')
    gp2 = GamePlayer(game_id=g1.game_id, player_id=201, team_id=1, position='G')
    gp3 = GamePlayer(game_id=g1.game_id, player_id=102, team_id=2, position='C')
    gp4 = GamePlayer(game_id=g1.game_id, player_id=202, team_id=2, position='G')
    db.session.add_all([gp1, gp2, gp3, gp4])

    # Regular goal by skater1 on goalie2
    e1 = Event(event_id='e1', game_id=g1.game_id, period=1, period_time='05:00',
               period_type='REG', event_type='goal', team_id=1, primary_player_id=101)
    s1 = Shot(shot_id='e1', game_id=g1.game_id, shooter_id=101, goalie_id=202, team_id=1,
              outcome='Goal', xg=0.25, goal=True, empty_net=False)

    # Empty-net goal by skater1 (goalie pulled)
    e2 = Event(event_id='e2', game_id=g1.game_id, period=3, period_time='19:30',
               period_type='REG', event_type='goal', team_id=1, primary_player_id=101)
    s2 = Shot(shot_id='e2', game_id=g1.game_id, shooter_id=101, goalie_id=202, team_id=1,
              outcome='Goal', xg=0.80, goal=True, empty_net=True)

    # Blocked shot by skater2 (blocked attempt: xg should be None or null, excluded from goalie)
    e3 = Event(event_id='e3', game_id=g1.game_id, period=2, period_time='10:00',
               period_type='REG', event_type='blocked-shot', team_id=2, primary_player_id=102)
    s3 = Shot(shot_id='e3', game_id=g1.game_id, shooter_id=102, goalie_id=201, team_id=2,
              outcome='Blocked', xg=None, goal=False, empty_net=False)

    # Saved shot on goalie1
    e4 = Event(event_id='e4', game_id=g1.game_id, period=2, period_time='12:00',
               period_type='REG', event_type='shot-on-goal', team_id=2, primary_player_id=102)
    s4 = Shot(shot_id='e4', game_id=g1.game_id, shooter_id=102, goalie_id=201, team_id=2,
              outcome='Saved', xg=0.15, goal=False, empty_net=False)

    db.session.add_all([e1, s1, e2, s2, e3, s3, e4, s4])
    db.session.commit()

    return {"season": "20242025"}

def test_team_season_ranking_sort_options(v13_data):
    """Verify team rankings sort cleanly across all defined metrics."""
    metrics = ['xg_pct', 'xgf_per_60', 'xga_per_60', 'cf_pct', 'ff_pct', 'gf_xgf_diff']
    for m in metrics:
        ranked = TeamSeasonService.get_season_team_rankings('20242025', sort_by=m)
        assert isinstance(ranked, list)
        for t in ranked:
            assert "rank" in t

def test_goalie_empty_net_exclusion(v13_data):
    """
    Verify empty-net goals are excluded from goalie xGA and GSAx.
    Goalie 202 faced 1 regular goal (xG=0.25) and 1 empty-net goal (xG=0.80).
    Non-empty net xGA must be 0.25, NOT 1.05!
    """
    stats = GoalieSeasonService.get_goalie_season_stats(202, '20242025')
    assert stats is not None
    # Empty net goal must be excluded from xga and gsax
    assert stats["xga"] == 0.25
    assert stats["gsax"] == 0.25 - 1.0  # -0.75

def test_skater_leaderboard_thresholds(v13_data):
    """Verify min_gp, min_toi, and min_unblocked filters in skater leaderboards."""
    all_leaders = PlayerSeasonService.get_skater_leaderboards('20242025', min_gp=1)
    assert len(all_leaders) > 0

    # Setting impossibly high threshold returns empty
    empty_leaders = PlayerSeasonService.get_skater_leaderboards('20242025', min_gp=100)
    assert len(empty_leaders) == 0

def test_blocked_shot_xg_explanation_rejection(client, v13_data):
    """Verify that attempting to get an xG explanation for a blocked shot returns 400."""
    res = client.get('/api/shots/e3/xg-explanation')
    assert res.status_code == 400
    json_data = res.get_json()
    assert "Blocked shot attempts are excluded" in json_data["error"]

def test_rolling_trend_insufficient_sample(v13_data):
    """Verify rolling trend behavior for zero appearances and single game sample."""
    # Player with 0 games in season
    trend_zero = RollingService.get_player_rolling_trends(999, '20242025', window_size=5)
    assert trend_zero["trend"] == []

    # Player with 1 game in season produces 1 window point with games_in_window=1
    trend_one = RollingService.get_player_rolling_trends(101, '20242025', window_size=5)
    assert len(trend_one["trend"]) == 1
    assert trend_one["trend"][0]["games_in_window"] == 1
