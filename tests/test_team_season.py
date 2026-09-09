import pytest
from datetime import date
from app.models import db, Team, Player, Game, Event, Shot
from app.services.team_season_service import TeamSeasonService

def test_team_season_aggregation_deterministic(app, db):
    """
    Construct deterministic games with known Corsi, Fenwick, xGF, xGA, GF, and GA,
    and verify season sums and rates.
    """
    cgy = Team(team_id=1, abbreviation='CGY', name='Calgary Flames')
    edm = Team(team_id=2, abbreviation='EDM', name='Edmonton Oilers')
    p1 = Player(player_id=1, first_name='Calgary', last_name='Shooter', position='F')
    p2 = Player(player_id=2, first_name='Edmonton', last_name='Shooter', position='F')
    db.session.add_all([cgy, edm, p1, p2])
    db.session.commit()

    # Game 1: CGY home vs EDM away
    # CGY: 2 goals, 3 saves, 1 miss, 2 blocked attempts (CF = 8, FF = 6, GF = 2, xGF = 0.8)
    # EDM: 1 goal, 2 saves, 2 misses, 1 blocked attempt (CF = 6, FF = 5, GF = 1, xGF = 0.5)
    g1 = Game(
        game_id=2024020001,
        season='20242025',
        game_date=date(2024, 10, 1),
        game_type='R',
        home_team_id=1,
        away_team_id=2,
        home_score=2,
        away_score=1,
        nhl_game_state='FINAL'
    )
    db.session.add(g1)
    db.session.flush()

    events = []
    shots = []

    # CGY shots in G1
    cgy_attempts = [
        ('shot-on-goal', 'Saved', 0.1, False, False),
        ('shot-on-goal', 'Saved', 0.1, False, False),
        ('shot-on-goal', 'Saved', 0.1, False, False),
        ('goal', 'Goal', 0.25, True, False),
        ('goal', 'Goal', 0.25, True, False),
        ('missed-shot', 'Missed', 0.05, False, False),
        ('blocked-shot', 'Blocked', None, False, False),
        ('blocked-shot', 'Blocked', None, False, False),
    ]
    for idx, (etype, outcome, xg, is_goal, empty_net) in enumerate(cgy_attempts):
        eid = f"2024020001_cgy_{idx}"
        ev = Event(
            event_id=eid, game_id=g1.game_id, period=1, period_time='05:00',
            elapsed_game_seconds=300, event_type=etype, team_id=1, team_strength_state='5v5'
        )
        events.append(ev)
        sh = Shot(
            shot_id=eid, game_id=g1.game_id, team_id=1, shooter_id=1,
            distance=20.0, angle=10.0, outcome=outcome, goal=is_goal,
            empty_net=empty_net, xg=xg, strength_state='EV'
        )
        shots.append(sh)

    # EDM shots in G1
    edm_attempts = [
        ('shot-on-goal', 'Saved', 0.1, False, False),
        ('shot-on-goal', 'Saved', 0.1, False, False),
        ('goal', 'Goal', 0.2, True, False),
        ('missed-shot', 'Missed', 0.05, False, False),
        ('missed-shot', 'Missed', 0.05, False, False),
        ('blocked-shot', 'Blocked', None, False, False),
    ]
    for idx, (etype, outcome, xg, is_goal, empty_net) in enumerate(edm_attempts):
        eid = f"2024020001_edm_{idx}"
        ev = Event(
            event_id=eid, game_id=g1.game_id, period=2, period_time='10:00',
            elapsed_game_seconds=1800, event_type=etype, team_id=2, team_strength_state='5v5'
        )
        events.append(ev)
        sh = Shot(
            shot_id=eid, game_id=g1.game_id, team_id=2, shooter_id=2,
            distance=25.0, angle=15.0, outcome=outcome, goal=is_goal,
            empty_net=empty_net, xg=xg, strength_state='EV'
        )
        shots.append(sh)

    db.session.add_all(events + shots)
    db.session.commit()

    # Query CGY season stats
    cgy_stats = TeamSeasonService.get_team_season_stats(team_id=1, season='20242025', situation='all')
    assert cgy_stats is not None
    assert cgy_stats["gp"] == 1
    assert cgy_stats["w"] == 1
    assert cgy_stats["l"] == 0
    assert cgy_stats["gf"] == 2
    assert cgy_stats["ga"] == 1
    assert cgy_stats["goal_diff"] == 1
    assert cgy_stats["cf"] == 8
    assert cgy_stats["ca"] == 6
    # CF% = 8 / (8 + 6) * 100 = 57.14%
    assert pytest.approx(cgy_stats["cf_pct"], 0.1) == 57.14
    assert cgy_stats["ff"] == 6
    assert cgy_stats["fa"] == 5
    # FF% = 6 / (6 + 5) * 100 = 54.55%
    assert pytest.approx(cgy_stats["ff_pct"], 0.1) == 54.55
    # xGF = 0.1*3 + 0.25*2 + 0.05 = 0.85
    assert pytest.approx(cgy_stats["xgf"], 0.05) == 0.85
    # xGA = 0.1*2 + 0.2 + 0.05*2 = 0.50
    assert pytest.approx(cgy_stats["xga"], 0.05) == 0.50
    # xG% = 0.85 / (0.85 + 0.50) * 100 = 62.96%
    assert pytest.approx(cgy_stats["xg_pct"], 0.1) == 62.96
    # GF - xGF
    assert pytest.approx(cgy_stats["gf_xgf_diff"], 0.05) == round(2 - 0.85, 2)
    # GA - xGA
    assert pytest.approx(cgy_stats["ga_xga_diff"], 0.05) == round(1 - 0.50, 2)
    # xG diff
    assert pytest.approx(cgy_stats["xg_diff"], 0.05) == round(0.85 - 0.50, 2)


def test_team_season_rankings(app, db):
    """
    Verify rankings sort properly for xG%, xGF/60, xGA/60, CF%, FF%, GF - xGF.
    """
    t1 = Team(team_id=10, abbreviation='AAA', name='Alpha Team')
    t2 = Team(team_id=20, abbreviation='BBB', name='Beta Team')
    p1 = Player(player_id=101, first_name='Alpha', last_name='Player', position='F')
    p2 = Player(player_id=201, first_name='Beta', last_name='Player', position='F')
    db.session.add_all([t1, t2, p1, p2])
    db.session.commit()

    g = Game(
        game_id=2024020099,
        season='20242025',
        game_date=date(2024, 10, 5),
        game_type='R',
        home_team_id=10,
        away_team_id=20,
        home_score=4,
        away_score=1,
        nhl_game_state='FINAL'
    )
    db.session.add(g)
    db.session.flush()

    # AAA dominates xG and possession
    ev_a = Event(event_id='2024020099_1', game_id=g.game_id, period=1, period_time='01:00',
                 event_type='goal', team_id=10, team_strength_state='5v5')
    sh_a = Shot(shot_id='2024020099_1', game_id=g.game_id, team_id=10, shooter_id=101,
                distance=10.0, angle=5.0, outcome='Goal', goal=True, xg=0.6)
    
    ev_b = Event(event_id='2024020099_2', game_id=g.game_id, period=2, period_time='01:00',
                 event_type='shot-on-goal', team_id=20, team_strength_state='5v5')
    sh_b = Shot(shot_id='2024020099_2', game_id=g.game_id, team_id=20, shooter_id=201,
                distance=50.0, angle=40.0, outcome='Saved', goal=False, xg=0.1)

    db.session.add_all([ev_a, sh_a, ev_b, sh_b])
    db.session.commit()

    rankings_xg = TeamSeasonService.get_season_team_rankings('20242025', situation='all', sort_by='xg_pct')
    assert len(rankings_xg) == 2
    assert rankings_xg[0]["team_id"] == 10
    assert rankings_xg[0]["rank"] == 1
    assert rankings_xg[1]["team_id"] == 20
    assert rankings_xg[1]["rank"] == 2

    # Lower xGA is better
    rankings_xga = TeamSeasonService.get_season_team_rankings('20242025', situation='all', sort_by='xga_per_60')
    assert rankings_xga[0]["team_id"] == 10  # Team 10 allowed only 0.1 xGA
    assert rankings_xga[0]["rank"] == 1
