import pytest
from datetime import date
from app.models import Team, Player, Game, Event, Shot, Shift, GamePlayer
from app.services.player_season_service import PlayerSeasonService
from app.services.team_season_service import TeamSeasonService

@pytest.fixture
def stage0_deterministic_5v5_fixture(db):
    """
    Constructs a deterministic full 5v5 reference fixture for two full NHL lineups (Calgary & Edmonton).
    Each team features 3 Forwards, 2 Defencemen, and 1 Goalie (6 players per team, 12 total).
    All 10 skaters and 2 goalies share a continuous 600s (10:00) 5v5 shift.
    """
    # 1. Teams
    t_cgy = Team(team_id=1, abbreviation='CGY', name='Calgary Flames')
    t_edm = Team(team_id=2, abbreviation='EDM', name='Edmonton Oilers')
    db.session.add_all([t_cgy, t_edm])

    # 2. Players - Calgary (Home)
    cgy_c  = Player(player_id=101, first_name='Mikael', last_name='Backlund', position='C')
    cgy_lw = Player(player_id=102, first_name='Blake', last_name='Coleman', position='LW')
    cgy_rw = Player(player_id=103, first_name='Jonathan', last_name='Huberdeau', position='RW')
    cgy_ld = Player(player_id=104, first_name='Rasmus', last_name='Andersson', position='D')
    cgy_rd = Player(player_id=105, first_name='Mackenzie', last_name='Weegar', position='D')
    cgy_g  = Player(player_id=106, first_name='Jacob', last_name='Markstrom', position='G')

    # Players - Edmonton (Away)
    edm_c  = Player(player_id=201, first_name='Connor', last_name='McDavid', position='C')
    edm_lw = Player(player_id=202, first_name='Leon', last_name='Draisaitl', position='LW')
    edm_rw = Player(player_id=203, first_name='Zach', last_name='Hyman', position='RW')
    edm_ld = Player(player_id=204, first_name='Evan', last_name='Bouchard', position='D')
    edm_rd = Player(player_id=205, first_name='Mattias', last_name='Ekholm', position='D')
    edm_g  = Player(player_id=206, first_name='Stuart', last_name='Skinner', position='G')

    all_players = [
        cgy_c, cgy_lw, cgy_rw, cgy_ld, cgy_rd, cgy_g,
        edm_c, edm_lw, edm_rw, edm_ld, edm_rd, edm_g
    ]
    db.session.add_all(all_players)
    db.session.commit()

    # 3. Game
    g1 = Game(
        game_id=2023020001,
        season='20232024',
        game_date=date(2023, 10, 12),
        game_type='R',
        home_team_id=1,
        away_team_id=2,
        home_score=1,
        away_score=0,
        nhl_game_state='FINAL'
    )
    db.session.add(g1)
    db.session.commit()

    # 4. GamePlayer entries for all 12 players
    gp_list = []
    for p in [cgy_c, cgy_lw, cgy_rw, cgy_ld, cgy_rd, cgy_g]:
        gp_list.append(GamePlayer(game_id=2023020001, player_id=p.player_id, team_id=1, position=p.position))
    for p in [edm_c, edm_lw, edm_rw, edm_ld, edm_rd, edm_g]:
        gp_list.append(GamePlayer(game_id=2023020001, player_id=p.player_id, team_id=2, position=p.position))
    db.session.add_all(gp_list)

    # 5. Continuous 5v5 Shifts (00:00 to 10:00 = 600 seconds)
    shifts = []
    for p in [cgy_c, cgy_lw, cgy_rw, cgy_ld, cgy_rd, cgy_g]:
        shifts.append(Shift(
            shift_id=f'2023020001_{p.player_id}_1_0',
            game_id=2023020001,
            player_id=p.player_id,
            period=1,
            start_time='00:00',
            end_time='10:00',
            start_elapsed_seconds=0,
            end_elapsed_seconds=600,
            duration=600,
            team_id=1,
            is_anomaly=False
        ))
    for p in [edm_c, edm_lw, edm_rw, edm_ld, edm_rd, edm_g]:
        shifts.append(Shift(
            shift_id=f'2023020001_{p.player_id}_1_0',
            game_id=2023020001,
            player_id=p.player_id,
            period=1,
            start_time='00:00',
            end_time='10:00',
            start_elapsed_seconds=0,
            end_elapsed_seconds=600,
            duration=600,
            team_id=2,
            is_anomaly=False
        ))
    db.session.add_all(shifts)

    # 6. Controlled Events & Shots
    # Event 1: Calgary Goal by 101 (Backlund), Assist1 by 102 (Coleman), xG=0.35
    ev1 = Event(
        event_id='2023020001_10',
        game_id=2023020001,
        period=1,
        period_time='02:00',
        elapsed_game_seconds=120,
        event_type='goal',
        team_id=1,
        primary_player_id=101,
        assist1_player_id=102,
        raw_situation_code='1551',
        home_skaters=5,
        away_skaters=5,
        team_strength_state='5v5',
        manpower_state='EV'
    )
    sh1 = Shot(
        shot_id='2023020001_10',
        game_id=2023020001,
        shooter_id=101,
        team_id=1,
        outcome='Goal',
        shot_type='Snap',
        distance=15.0,
        xg=0.35
    )

    # Event 2: Calgary Missed Shot by 103 (Huberdeau), xG=0.20
    ev2 = Event(
        event_id='2023020001_20',
        game_id=2023020001,
        period=1,
        period_time='04:00',
        elapsed_game_seconds=240,
        event_type='missed-shot',
        team_id=1,
        primary_player_id=103,
        raw_situation_code='1551',
        home_skaters=5,
        away_skaters=5,
        team_strength_state='5v5',
        manpower_state='EV'
    )
    sh2 = Shot(
        shot_id='2023020001_20',
        game_id=2023020001,
        shooter_id=103,
        team_id=1,
        outcome='Missed',
        shot_type='Wrist',
        distance=25.0,
        xg=0.20
    )

    # Event 3: Calgary Blocked Shot Attempt by 104 (Andersson)
    # Corsi For (+1), Fenwick For (0), xG (None)
    ev3 = Event(
        event_id='2023020001_30',
        game_id=2023020001,
        period=1,
        period_time='06:00',
        elapsed_game_seconds=360,
        event_type='blocked-shot',
        team_id=1,
        primary_player_id=104,
        raw_situation_code='1551',
        home_skaters=5,
        away_skaters=5,
        team_strength_state='5v5',
        manpower_state='EV'
    )

    # Event 4: Edmonton Shot on Goal (Saved) by 201 (McDavid), xG=0.21
    ev4 = Event(
        event_id='2023020001_40',
        game_id=2023020001,
        period=1,
        period_time='07:00',
        elapsed_game_seconds=420,
        event_type='shot-on-goal',
        team_id=2,
        primary_player_id=201,
        raw_situation_code='1551',
        home_skaters=5,
        away_skaters=5,
        team_strength_state='5v5',
        manpower_state='EV'
    )
    sh4 = Shot(
        shot_id='2023020001_40',
        game_id=2023020001,
        shooter_id=201,
        team_id=2,
        outcome='Saved',
        shot_type='Wrist',
        distance=12.0,
        xg=0.21
    )

    # Event 5: Edmonton Missed Shot by 202 (Draisaitl), xG=0.09
    ev5 = Event(
        event_id='2023020001_50',
        game_id=2023020001,
        period=1,
        period_time='08:00',
        elapsed_game_seconds=480,
        event_type='missed-shot',
        team_id=2,
        primary_player_id=202,
        raw_situation_code='1551',
        home_skaters=5,
        away_skaters=5,
        team_strength_state='5v5',
        manpower_state='EV'
    )
    sh5 = Shot(
        shot_id='2023020001_50',
        game_id=2023020001,
        shooter_id=202,
        team_id=2,
        outcome='Missed',
        shot_type='Slap',
        distance=35.0,
        xg=0.09
    )

    db.session.add_all([ev1, sh1, ev2, sh2, ev3, ev4, sh4, ev5, sh5])
    db.session.commit()

def test_stage0_frozen_analytical_reference_outputs(app, db, stage0_deterministic_5v5_fixture):
    """
    Freezes exact analytical reference outputs for Calgary skater 101 (Mikael Backlund).
    Asserts hard numerical expected values for individual counting stats, rates, and 5v5 on-ice metrics.
    """
    skaters = PlayerSeasonService.get_season_skaters_summary(season='20232024', include_on_ice_5v5=True)
    assert len(skaters) == 10, "Should return 10 skaters across both teams (goalies excluded)"

    # Find Calgary Player 101 (Backlund)
    skater = next(s for s in skaters if s["player_id"] == 101)

    # Individual / Counting Statistics
    assert skater["gp"] == 1
    assert skater["goals"] == 1
    assert skater["assists"] == 0
    assert skater["points"] == 1
    assert skater["shots_on_goal"] == 1
    assert skater["shots"] == 1
    assert skater["unblocked_attempts"] == 1
    assert skater["xg"] == 0.35
    assert skater["goals_minus_xg"] == 0.65
    assert skater["g_minus_xg"] == 0.65
    assert skater["toi_seconds"] == 600
    assert skater["toi_formatted"] == "10:00"

    # Individual Rates
    assert skater["shooting_pct"] == 100.0
    assert skater["expected_conversion_pct"] == 35.0
    assert skater["goals_per_60"] == 6.0
    assert skater["xg_per_60"] == 2.1

    # 5v5 On-Ice Metrics
    # CGY Events: Goal (CF+1, FF+1, xGF+0.35), Missed (CF+1, FF+1, xGF+0.20), Blocked (CF+1, FF+0, xGF+0.00) => CF=3, FF=2, xGF=0.55
    # EDM Events: Saved (CA+1, FA+1, xGA+0.21), Missed (CA+1, FA+1, xGA+0.09) => CA=2, FA=2, xGA=0.30
    oi = skater["on_ice_5v5"]
    assert oi["cf"] == 3
    assert oi["ca"] == 2
    assert oi["cf_pct"] == 60.0
    assert oi["ff"] == 2
    assert oi["fa"] == 2
    assert oi["ff_pct"] == 50.0
    assert oi["on_ice_xgf"] == 0.55
    assert oi["on_ice_xga"] == 0.30
    assert oi["on_ice_xg_pct"] == 64.71
    assert oi["toi_seconds"] == 600
    assert oi["toi_formatted"] == "10:00"

def test_stage0_single_player_full_summary_equivalence(app, db, stage0_deterministic_5v5_fixture):
    """
    Verifies that get_skater_season_stats returns identical analytical values to get_season_skaters_summary
    across all counting stats, rates, and 5v5 on-ice metrics.
    """
    all_skaters = PlayerSeasonService.get_season_skaters_summary(season='20232024', include_on_ice_5v5=True)
    skater_summary = next(s for s in skaters_list if s["player_id"] == 101) if (skaters_list := all_skaters) else None
    assert skater_summary is not None

    single_skater = PlayerSeasonService.get_skater_season_stats(player_id=101, season='20232024')
    assert single_skater is not None

    # Hard equivalence assertions across all analytical fields
    assert single_skater["player_id"] == skater_summary["player_id"]
    assert single_skater["gp"] == skater_summary["gp"]
    assert single_skater["goals"] == skater_summary["goals"]
    assert single_skater["assists"] == skater_summary["assists"]
    assert single_skater["points"] == skater_summary["points"]
    assert single_skater["shots"] == skater_summary["shots"]
    assert single_skater["unblocked_attempts"] == skater_summary["unblocked_attempts"]
    assert single_skater["xg"] == skater_summary["xg"]
    assert single_skater["goals_minus_xg"] == skater_summary["goals_minus_xg"]
    assert single_skater["shooting_pct"] == skater_summary["shooting_pct"]
    assert single_skater["goals_per_60"] == skater_summary["goals_per_60"]
    assert single_skater["xg_per_60"] == skater_summary["xg_per_60"]
    assert single_skater["toi_seconds"] == skater_summary["toi_seconds"]

    # 5v5 On-Ice Equivalence
    oi_single = single_skater["on_ice_5v5"]
    oi_summary = skater_summary["on_ice_5v5"]
    assert oi_single["cf"] == oi_summary["cf"] == 3
    assert oi_single["ca"] == oi_summary["ca"] == 2
    assert oi_single["cf_pct"] == oi_summary["cf_pct"] == 60.0
    assert oi_single["ff"] == oi_summary["ff"] == 2
    assert oi_single["fa"] == oi_summary["fa"] == 2
    assert oi_single["ff_pct"] == oi_summary["ff_pct"] == 50.0
    assert oi_single["on_ice_xgf"] == oi_summary["on_ice_xgf"] == 0.55
    assert oi_single["on_ice_xga"] == oi_summary["on_ice_xga"] == 0.30
    assert oi_single["on_ice_xg_pct"] == oi_summary["on_ice_xg_pct"] == 64.71
    assert oi_single["toi_seconds"] == oi_summary["toi_seconds"] == 600

def test_stage0_ratio_aggregation_semantics(app, db):
    """
    Freezes the fundamental analytical invariant:
    Season percentages MUST be calculated from summed additive primitives (sum(num) / sum(den)),
    NEVER by averaging individual game percentages (avg(game_pcts)).
    """
    # Setup two asymmetric games for a team and player
    t1 = Team(team_id=10, abbreviation='CGY', name='Calgary Flames')
    t2 = Team(team_id=20, abbreviation='EDM', name='Edmonton Oilers')
    p1 = Player(player_id=501, first_name='Test', last_name='Skater', position='C')
    p_goalie1 = Player(player_id=502, first_name='Home', last_name='Goalie', position='G')
    p_goalie2 = Player(player_id=503, first_name='Away', last_name='Goalie', position='G')

    # Fill out 4 extra skaters per team for 5v5
    cgy_skaters = [p1] + [Player(player_id=504+i, first_name=f'CGY{i}', last_name='Skater', position='D') for i in range(4)]
    edm_skaters = [Player(player_id=510+i, first_name=f'EDM{i}', last_name='Skater', position='F') for i in range(5)]
    db.session.add_all([t1, t2, p_goalie1, p_goalie2] + cgy_skaters + edm_skaters)
    db.session.commit()

    # Game 1: Asymmetric high CF for Calgary (CF=9, CA=1 -> Game 1 CF% = 90.0%)
    g1 = Game(game_id=2023020101, season='20232024', game_date=date(2023, 11, 1), game_type='R', home_team_id=10, away_team_id=20, home_score=2, away_score=1, nhl_game_state='FINAL')
    # Game 2: Asymmetric low CF for Calgary (CF=1, CA=99 -> Game 2 CF% = 1.0%)
    g2 = Game(game_id=2023020102, season='20232024', game_date=date(2023, 11, 2), game_type='R', home_team_id=10, away_team_id=20, home_score=1, away_score=5, nhl_game_state='FINAL')
    db.session.add_all([g1, g2])
    db.session.commit()

    # Add GamePlayers and Shifts for both games
    for g in [g1, g2]:
        gp_rows = [GamePlayer(game_id=g.game_id, player_id=p.player_id, team_id=10, position=p.position) for p in cgy_skaters + [p_goalie1]] + \
                  [GamePlayer(game_id=g.game_id, player_id=p.player_id, team_id=20, position=p.position) for p in edm_skaters + [p_goalie2]]
        db.session.add_all(gp_rows)

        shift_rows = [Shift(shift_id=f'{g.game_id}_{p.player_id}_1', game_id=g.game_id, player_id=p.player_id, period=1, start_time='00:00', end_time='10:00', start_elapsed_seconds=0, end_elapsed_seconds=600, duration=600, team_id=10 if p in cgy_skaters or p == p_goalie1 else 20, is_anomaly=False) for p in cgy_skaters + [p_goalie1] + edm_skaters + [p_goalie2]]
        db.session.add_all(shift_rows)

    # Game 1 Events: 9 Calgary goals (CF=9, FF=9, xGF=1.80), 1 Edmonton saved shot (CA=1, FA=1, xGA=0.20)
    for i in range(9):
        ev = Event(event_id=f'2023020101_cgy_{i}', game_id=2023020101, period=1, period_time=f'0{i}:00', elapsed_game_seconds=10+i*10, event_type='goal', team_id=10, primary_player_id=501, raw_situation_code='1551', home_skaters=5, away_skaters=5, team_strength_state='5v5', manpower_state='EV')
        sh = Shot(shot_id=f'2023020101_cgy_{i}', game_id=2023020101, shooter_id=501, team_id=10, outcome='Goal', xg=0.20)
        db.session.add_all([ev, sh])
    ev_g1_ca = Event(event_id='2023020101_edm_0', game_id=2023020101, period=1, period_time='09:00', elapsed_game_seconds=540, event_type='shot-on-goal', team_id=20, primary_player_id=510, raw_situation_code='1551', home_skaters=5, away_skaters=5, team_strength_state='5v5', manpower_state='EV')
    sh_g1_ca = Shot(shot_id='2023020101_edm_0', game_id=2023020101, shooter_id=510, team_id=20, outcome='Saved', xg=0.20)
    db.session.add_all([ev_g1_ca, sh_g1_ca])

    # Game 2 Events: 1 Calgary goal (CF=1, FF=1, xGF=0.10), 99 Edmonton saved shots (CA=99, FA=99, xGA=9.90)
    ev_g2_cf = Event(event_id='2023020102_cgy_0', game_id=2023020102, period=1, period_time='00:30', elapsed_game_seconds=30, event_type='goal', team_id=10, primary_player_id=501, raw_situation_code='1551', home_skaters=5, away_skaters=5, team_strength_state='5v5', manpower_state='EV')
    sh_g2_cf = Shot(shot_id='2023020102_cgy_0', game_id=2023020102, shooter_id=501, team_id=10, outcome='Goal', xg=0.10)
    db.session.add_all([ev_g2_cf, sh_g2_cf])

    for i in range(99):
        ev = Event(event_id=f'2023020102_edm_{i}', game_id=2023020102, period=1, period_time='01:00', elapsed_game_seconds=40+i*5, event_type='shot-on-goal', team_id=20, primary_player_id=510, raw_situation_code='1551', home_skaters=5, away_skaters=5, team_strength_state='5v5', manpower_state='EV')
        sh = Shot(shot_id=f'2023020102_edm_{i}', game_id=2023020102, shooter_id=510, team_id=20, outcome='Saved', xg=0.10)
        db.session.add_all([ev, sh])

    db.session.commit()

    skaters = PlayerSeasonService.get_season_skaters_summary(season='20232024', include_on_ice_5v5=True)
    p1_stats = next(s for s in skaters if s["player_id"] == 501)
    oi = p1_stats["on_ice_5v5"]

    # Verify Additive Primitives
    assert oi["cf"] == 9 + 1 == 10
    assert oi["ca"] == 1 + 99 == 100
    assert oi["ff"] == 9 + 1 == 10
    assert oi["fa"] == 1 + 99 == 100
    assert abs(oi["on_ice_xgf"] - 1.90) < 0.01
    assert abs(oi["on_ice_xga"] - 10.10) < 0.01

    # Simple Average of Game CF% would be (90.0% + 1.0%) / 2 = 45.5%
    # Summed Ratio Season CF% is 10 / 110 * 100 = 9.09%
    avg_game_cf_pct = (90.0 + 1.0) / 2.0  # 45.5
    correct_season_cf_pct = round(10.0 / 110.0 * 100.0, 2)  # 9.09

    assert oi["cf_pct"] == correct_season_cf_pct == 9.09
    assert oi["cf_pct"] != avg_game_cf_pct

    # FF% assertion
    assert oi["ff_pct"] == 9.09
    assert oi["ff_pct"] != 45.5

    # xG% assertion: 1.90 / (1.90 + 10.10) * 100 = 1.90 / 12.00 * 100 = 15.83%
    # Simple average of game xG% would be (90.0% + 1.0%) / 2 = 45.5%
    correct_season_xg_pct = round(1.90 / 12.00 * 100.0, 2)  # 15.83
    assert oi["on_ice_xg_pct"] == correct_season_xg_pct == 15.83
    assert oi["on_ice_xg_pct"] != 45.5
