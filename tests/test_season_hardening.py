import pytest
import hashlib
from datetime import date
from app.models import db, Team, Player, Game, Event, Shot, Shift, GamePlayer
from app.services.player_season_service import PlayerSeasonService
from app.services.goalie_season_service import GoalieSeasonService
from app.services.team_season_service import TeamSeasonService

FROZEN_MODEL_SHA256 = "c7f4f55bb0136f5d1774267446f5bd07a9a0bad2285238a25f551a61b0927635"


def test_frozen_model_invariance():
    """Verify that models/xg/xg_v1.pkl remains bitwise identical to approved frozen SHA-256."""
    h = hashlib.sha256()
    with open("models/xg/xg_v1.pkl", "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    assert h.hexdigest() == FROZEN_MODEL_SHA256


def test_traded_skater_representation_league_and_filtered(app, db):
    """
    Verify traded player representation:
    - When team_id is None: full-season statistics aggregated across all team stints,
      with combined team representation ordered chronologically from actual game appearances (e.g. CGY/VAN/CGY).
    - When team_id=<team>: only production recorded while representing that team is returned.
    """
    cgy = Team(team_id=1, abbreviation='CGY', name='Calgary Flames')
    edm = Team(team_id=2, abbreviation='EDM', name='Edmonton Oilers')
    van = Team(team_id=3, abbreviation='VAN', name='Vancouver Canucks')
    player = Player(player_id=101, first_name='Traded', last_name='Skater', position='F')
    other = Player(player_id=999, first_name='Other', last_name='Player', position='D')
    db.session.add_all([cgy, edm, van, player, other])
    db.session.commit()

    # Game 1: 2024-10-01 - Skater plays for CGY vs EDM. Scores 1 goal, 1 assist, 2 SOG, 0.3 xG, 600s TOI
    g1 = Game(
        game_id=2024020011, season='20242025', game_date=date(2024, 10, 1),
        game_type='R', home_team_id=1, away_team_id=2, home_score=3, away_score=2, nhl_game_state='FINAL'
    )
    # Game 2: 2024-10-10 - Skater was traded to VAN vs EDM. Scores 2 goals, 0 assists, 4 SOG, 0.5 xG, 1200s TOI
    g2 = Game(
        game_id=2024020012, season='20242025', game_date=date(2024, 10, 10),
        game_type='R', home_team_id=3, away_team_id=2, home_score=4, away_score=1, nhl_game_state='FINAL'
    )
    # Game 3: 2024-10-20 - Skater was traded back to CGY vs VAN. Scores 0 goals, 1 assist, 1 SOG, 0.1 xG, 800s TOI
    g3 = Game(
        game_id=2024020013, season='20242025', game_date=date(2024, 10, 20),
        game_type='R', home_team_id=1, away_team_id=3, home_score=2, away_score=1, nhl_game_state='FINAL'
    )
    db.session.add_all([g1, g2, g3])
    db.session.flush()

    # GamePlayer entries establishing chronological stints: CGY -> VAN -> CGY
    gp1 = GamePlayer(game_id=g1.game_id, player_id=101, team_id=1, position='F')
    gp2 = GamePlayer(game_id=g2.game_id, player_id=101, team_id=3, position='F')
    gp3 = GamePlayer(game_id=g3.game_id, player_id=101, team_id=1, position='F')

    # Shifts
    s1 = Shift(shift_id='s1', game_id=g1.game_id, player_id=101, period=1, start_time='00:00', end_time='10:00',
               start_elapsed_seconds=0, end_elapsed_seconds=600, duration=600, team_id=1)
    s2 = Shift(shift_id='s2', game_id=g2.game_id, player_id=101, period=1, start_time='00:00', end_time='20:00',
               start_elapsed_seconds=0, end_elapsed_seconds=1200, duration=1200, team_id=3)
    s3 = Shift(shift_id='s3', game_id=g3.game_id, player_id=101, period=1, start_time='00:00', end_time='13:20',
               start_elapsed_seconds=0, end_elapsed_seconds=800, duration=800, team_id=1)

    # Events & Shots
    # G1 (CGY): 1 goal (0.2 xG), 1 saved (0.1 xG), 1 assist (on other player's goal)
    e1_g = Event(event_id='e1_g', game_id=g1.game_id, period=1, period_time='02:00', event_type='goal', team_id=1, primary_player_id=101)
    sh1_g = Shot(shot_id='e1_g', game_id=g1.game_id, team_id=1, shooter_id=101, outcome='Goal', goal=True, xg=0.20, distance=10.0, strength_state='EV')
    e1_s = Event(event_id='e1_s', game_id=g1.game_id, period=1, period_time='05:00', event_type='shot-on-goal', team_id=1, primary_player_id=101)
    sh1_s = Shot(shot_id='e1_s', game_id=g1.game_id, team_id=1, shooter_id=101, outcome='Saved', goal=False, xg=0.10, distance=20.0, strength_state='EV')
    e1_a = Event(event_id='e1_a', game_id=g1.game_id, period=1, period_time='08:00', event_type='goal', team_id=1, primary_player_id=999, assist1_player_id=101)

    # G2 (VAN): 2 goals (0.3 xG, 0.1 xG), 2 saved (0.05 xG, 0.05 xG)
    e2_g1 = Event(event_id='e2_g1', game_id=g2.game_id, period=1, period_time='02:00', event_type='goal', team_id=3, primary_player_id=101)
    sh2_g1 = Shot(shot_id='e2_g1', game_id=g2.game_id, team_id=3, shooter_id=101, outcome='Goal', goal=True, xg=0.30, distance=12.0, strength_state='EV')
    e2_g2 = Event(event_id='e2_g2', game_id=g2.game_id, period=1, period_time='04:00', event_type='goal', team_id=3, primary_player_id=101)
    sh2_g2 = Shot(shot_id='e2_g2', game_id=g2.game_id, team_id=3, shooter_id=101, outcome='Goal', goal=True, xg=0.10, distance=25.0, strength_state='EV')
    e2_s1 = Event(event_id='e2_s1', game_id=g2.game_id, period=1, period_time='06:00', event_type='shot-on-goal', team_id=3, primary_player_id=101)
    sh2_s1 = Shot(shot_id='e2_s1', game_id=g2.game_id, team_id=3, shooter_id=101, outcome='Saved', goal=False, xg=0.05, distance=30.0, strength_state='EV')
    e2_s2 = Event(event_id='e2_s2', game_id=g2.game_id, period=1, period_time='08:00', event_type='shot-on-goal', team_id=3, primary_player_id=101)
    sh2_s2 = Shot(shot_id='e2_s2', game_id=g2.game_id, team_id=3, shooter_id=101, outcome='Saved', goal=False, xg=0.05, distance=35.0, strength_state='EV')

    # G3 (CGY): 1 saved shot (0.1 xG), 1 assist (on other player's goal)
    e3_s = Event(event_id='e3_s', game_id=g3.game_id, period=1, period_time='03:00', event_type='shot-on-goal', team_id=1, primary_player_id=101)
    sh3_s = Shot(shot_id='e3_s', game_id=g3.game_id, team_id=1, shooter_id=101, outcome='Saved', goal=False, xg=0.10, distance=22.0, strength_state='EV')
    e3_a = Event(event_id='e3_a', game_id=g3.game_id, period=1, period_time='07:00', event_type='goal', team_id=1, primary_player_id=999, assist2_player_id=101)

    db.session.add_all([gp1, gp2, gp3, s1, s2, s3, e1_g, sh1_g, e1_s, sh1_s, e1_a,
                        e2_g1, sh2_g1, e2_g2, sh2_g2, e2_s1, sh2_s1, e2_s2, sh2_s2,
                        e3_s, sh3_s, e3_a])
    db.session.commit()

    # 1. League-wide query: team_id is None
    all_skaters = PlayerSeasonService.get_season_skaters_summary(season='20242025', team_id=None, min_gp=1)
    skater_data = next((s for s in all_skaters if s['player_id'] == 101), None)
    assert skater_data is not None
    # Combined team representation preserves chronological stint sequence CGY -> VAN -> CGY
    assert skater_data['team'] == 'CGY/VAN/CGY'
    assert skater_data['gp'] == 3
    assert skater_data['goals'] == 3       # 1 (CGY) + 2 (VAN) + 0 (CGY)
    assert skater_data['assists'] == 2     # 1 (CGY) + 0 (VAN) + 1 (CGY)
    assert skater_data['points'] == 5
    assert skater_data['shots'] == 7       # 2 + 4 + 1
    assert skater_data['xg'] == pytest.approx(0.90, rel=1e-2) # 0.3 + 0.5 + 0.1
    assert skater_data['toi_seconds'] == 2600 # 600 + 1200 + 800

    # 2. Filtered query: team_id=1 (CGY)
    cgy_skaters = PlayerSeasonService.get_season_skaters_summary(season='20242025', team_id=1, min_gp=1)
    cgy_data = next((s for s in cgy_skaters if s['player_id'] == 101), None)
    assert cgy_data is not None
    assert cgy_data['team'] == 'CGY'
    assert cgy_data['gp'] == 2
    assert cgy_data['goals'] == 1
    assert cgy_data['assists'] == 2
    assert cgy_data['points'] == 3
    assert cgy_data['shots'] == 3
    assert cgy_data['xg'] == pytest.approx(0.40, rel=1e-2)
    assert cgy_data['toi_seconds'] == 1400 # 600 + 800

    # 3. Filtered query: team_id=3 (VAN)
    van_skaters = PlayerSeasonService.get_season_skaters_summary(season='20242025', team_id=3, min_gp=1)
    van_data = next((s for s in van_skaters if s['player_id'] == 101), None)
    assert van_data is not None
    assert van_data['team'] == 'VAN'
    assert van_data['gp'] == 1
    assert van_data['goals'] == 2
    assert van_data['assists'] == 0
    assert van_data['points'] == 2
    assert van_data['shots'] == 4
    assert van_data['xg'] == pytest.approx(0.50, rel=1e-2)
    assert van_data['toi_seconds'] == 1200


def test_traded_goalie_representation_league_and_filtered(app, db):
    """
    Verify traded goalie representation:
    - League-wide (team_id is None): combined team representation (e.g. CGY/VAN) and full-season totals.
    - Filtered (team_id=<team>): only shots faced, GA, xGA, and TOI while representing that team.
    """
    cgy = Team(team_id=1, abbreviation='CGY', name='Calgary Flames')
    van = Team(team_id=3, abbreviation='VAN', name='Vancouver Canucks')
    edm = Team(team_id=2, abbreviation='EDM', name='Edmonton Oilers')
    goalie = Player(player_id=202, first_name='Traded', last_name='Goalie', position='G')
    shooter = Player(player_id=303, first_name='Edm', last_name='Shooter', position='F')
    db.session.add_all([cgy, van, edm, goalie, shooter])
    db.session.commit()

    # Game 1: 2024-10-02 - Goalie in net for CGY vs EDM. 10 shots faced, 2 GA, 1.8 xGA, 3600s TOI
    g1 = Game(
        game_id=2024020021, season='20242025', game_date=date(2024, 10, 2),
        game_type='R', home_team_id=1, away_team_id=2, home_score=3, away_score=2, nhl_game_state='FINAL'
    )
    # Game 2: 2024-10-15 - Goalie in net for VAN vs EDM. 15 shots faced, 1 GA, 2.2 xGA, 3600s TOI
    g2 = Game(
        game_id=2024020022, season='20242025', game_date=date(2024, 10, 15),
        game_type='R', home_team_id=3, away_team_id=2, home_score=4, away_score=1, nhl_game_state='FINAL'
    )
    db.session.add_all([g1, g2])
    db.session.flush()

    gp1 = GamePlayer(game_id=g1.game_id, player_id=202, team_id=1, position='G')
    gp2 = GamePlayer(game_id=g2.game_id, player_id=202, team_id=3, position='G')

    s1 = Shift(shift_id='gs1', game_id=g1.game_id, player_id=202, period=1, start_time='00:00', end_time='20:00',
               start_elapsed_seconds=0, end_elapsed_seconds=3600, duration=3600, team_id=1)
    s2 = Shift(shift_id='gs2', game_id=g2.game_id, player_id=202, period=1, start_time='00:00', end_time='20:00',
               start_elapsed_seconds=0, end_elapsed_seconds=3600, duration=3600, team_id=3)

    db.session.add_all([gp1, gp2, s1, s2])

    # G1 shots (EDM shooting on CGY goalie): 2 goals, 8 saves
    for i in range(10):
        is_g = (i < 2)
        xg_val = 0.50 if is_g else 0.10 # total xG = 2 * 0.5 + 8 * 0.1 = 1.8
        eid = f"g1_shot_{i}"
        ev = Event(event_id=eid, game_id=g1.game_id, period=1, period_time=f"0{i}:00", event_type='goal' if is_g else 'shot-on-goal', team_id=2)
        sh = Shot(shot_id=eid, game_id=g1.game_id, team_id=2, shooter_id=303, goalie_id=202, outcome='Goal' if is_g else 'Saved', goal=is_g, xg=xg_val, empty_net=False)
        db.session.add_all([ev, sh])

    # G2 shots (EDM shooting on VAN goalie): 1 goal, 14 saves
    for i in range(15):
        is_g = (i == 0)
        xg_val = 0.80 if is_g else 0.10 # total xG = 0.8 + 14 * 0.1 = 2.2
        eid = f"g2_shot_{i}"
        ev = Event(event_id=eid, game_id=g2.game_id, period=1, period_time=f"0{i}:00", event_type='goal' if is_g else 'shot-on-goal', team_id=2)
        sh = Shot(shot_id=eid, game_id=g2.game_id, team_id=2, shooter_id=303, goalie_id=202, outcome='Goal' if is_g else 'Saved', goal=is_g, xg=xg_val, empty_net=False)
        db.session.add_all([ev, sh])

    db.session.commit()

    # 1. League-wide query
    all_goalies = GoalieSeasonService.get_season_goalies_summary(season='20242025', team_id=None, min_gp=1)
    goalie_data = next((g for g in all_goalies if g['player_id'] == 202), None)
    assert goalie_data is not None
    assert goalie_data['team'] == 'CGY/VAN'
    assert goalie_data['gp'] == 2
    assert goalie_data['shots_faced'] == 25
    assert goalie_data['goals_against'] == 3
    assert goalie_data['xga'] == pytest.approx(4.0, rel=1e-2)
    assert goalie_data['save_pct'] == pytest.approx(round(22 / 25 * 100, 2))
    assert goalie_data['gsax'] == pytest.approx(round(4.0 - 3, 2))

    # 2. Filtered query: CGY (team_id=1)
    cgy_goalies = GoalieSeasonService.get_season_goalies_summary(season='20242025', team_id=1, min_gp=1)
    cgy_g = next((g for g in cgy_goalies if g['player_id'] == 202), None)
    assert cgy_g is not None
    assert cgy_g['team'] == 'CGY'
    assert cgy_g['gp'] == 1
    assert cgy_g['shots_faced'] == 10
    assert cgy_g['goals_against'] == 2
    assert cgy_g['xga'] == pytest.approx(1.8, rel=1e-2)
    assert cgy_g['save_pct'] == pytest.approx(round(8 / 10 * 100, 2))

    # 3. Filtered query: VAN (team_id=3)
    van_goalies = GoalieSeasonService.get_season_goalies_summary(season='20242025', team_id=3, min_gp=1)
    van_g = next((g for g in van_goalies if g['player_id'] == 202), None)
    assert van_g is not None
    assert van_g['team'] == 'VAN'
    assert van_g['gp'] == 1
    assert van_g['shots_faced'] == 15
    assert van_g['goals_against'] == 1
    assert van_g['xga'] == pytest.approx(2.2, rel=1e-2)
    assert van_g['save_pct'] == pytest.approx(round(14 / 15 * 100, 2))


def test_situation_toi_rate_precision_and_missing_state(app, db, client):
    """
    Verify situation TOI rate precision:
    - Situation-specific /60 metrics must use actual situation time derived from shifts/timelines.
    - No fixed assumptions (48m 5v5, 5m PP, 5m PK).
    - If reliable actual duration cannot be established, return None at service layer (not 0.00 / 60).
    - Template renders '—' when rates are None.
    """
    cgy = Team(team_id=1, abbreviation='CGY', name='Calgary Flames')
    edm = Team(team_id=2, abbreviation='EDM', name='Edmonton Oilers')
    p1 = Player(player_id=1, first_name='Calgary', last_name='Shooter', position='F')
    p2 = Player(player_id=2, first_name='Edmonton', last_name='Shooter', position='F')
    db.session.add_all([cgy, edm, p1, p2])
    db.session.commit()

    # Game 1: Without shifts (timeline unavailable)
    g1 = Game(
        game_id=2024020031, season='20242025', game_date=date(2024, 10, 1),
        game_type='R', home_team_id=1, away_team_id=2, home_score=2, away_score=1, nhl_game_state='FINAL'
    )
    db.session.add(g1)
    db.session.flush()

    # 1 shot for CGY (xg=0.3)
    ev = Event(event_id='e_no_shifts', game_id=g1.game_id, period=1, period_time='05:00', elapsed_game_seconds=300,
               event_type='shot-on-goal', team_id=1, team_strength_state='5v5')
    sh = Shot(shot_id='e_no_shifts', game_id=g1.game_id, team_id=1, shooter_id=1, outcome='Saved',
              goal=False, xg=0.30, strength_state='EV')
    db.session.add_all([ev, sh])
    db.session.commit()

    # Query 5v5 situation stats with no shifts
    stats_5v5 = TeamSeasonService.get_team_season_stats(team_id=1, season='20242025', situation='5v5')
    assert stats_5v5 is not None
    # Denominator cannot be established -> toi_seconds must be None, rates must be None (never 0.00 / 60)
    assert stats_5v5['toi_seconds'] is None
    assert stats_5v5['xgf_per_60'] is None
    assert stats_5v5['xga_per_60'] is None

    # Verify UI rendering: season page with 5v5 situation displays '—' / '&mdash;'
    res = client.get('/season/20242025?situation=5v5')
    assert res.status_code == 200
    html = res.data.decode('utf-8')
    assert ('&mdash;' in html) or ('—' in html)


def test_on_ice_xg_calculation_non_default(app, db):
    """
    Verify on-ice 5v5 xGF and xGA calculation accumulates true Shot.xg values,
    producing non-default (not 50.0%) xG% when shots exist.
    """
    cgy = Team(team_id=1, abbreviation='CGY', name='Calgary Flames')
    edm = Team(team_id=2, abbreviation='EDM', name='Edmonton Oilers')
    skater = Player(player_id=50, first_name='OnIce', last_name='Player', position='F')
    shooter_against = Player(player_id=2, first_name='Edm', last_name='Shooter', position='F')
    goalie_cgy = Player(player_id=901, first_name='CGY', last_name='Goalie', position='G')
    goalie_edm = Player(player_id=902, first_name='EDM', last_name='Goalie', position='G')
    db.session.add_all([cgy, edm, skater, shooter_against, goalie_cgy, goalie_edm])
    db.session.commit()

    g = Game(
        game_id=2024020051, season='20242025', game_date=date(2024, 10, 8),
        game_type='R', home_team_id=1, away_team_id=2, home_score=3, away_score=1, nhl_game_state='FINAL'
    )
    db.session.add(g)
    db.session.flush()

    gp = GamePlayer(game_id=g.game_id, player_id=50, team_id=1, position='F')
    s = Shift(shift_id='s_oi', game_id=g.game_id, player_id=50, period=1, start_time='00:00',
              end_time='10:00', start_elapsed_seconds=0, end_elapsed_seconds=600, duration=600, team_id=1)

    # 1 shot for CGY on-ice during skater shift: xG = 0.60
    ev_f = Event(event_id='e_oi_f', game_id=g.game_id, period=1, period_time='03:00', elapsed_game_seconds=180,
                 event_type='shot-on-goal', team_id=1, primary_player_id=50, team_strength_state='5v5',
                 manpower_state='EV', raw_situation_code='1551')
    sh_f = Shot(shot_id='e_oi_f', game_id=g.game_id, team_id=1, shooter_id=50, goalie_id=902,
                outcome='Saved', goal=False, xg=0.60, strength_state='EV')

    # 1 shot against CGY on-ice during skater shift: xG = 0.20
    ev_a = Event(event_id='e_oi_a', game_id=g.game_id, period=1, period_time='06:00', elapsed_game_seconds=360,
                 event_type='shot-on-goal', team_id=2, primary_player_id=2, team_strength_state='5v5',
                 manpower_state='EV', raw_situation_code='1551')
    sh_a = Shot(shot_id='e_oi_a', game_id=g.game_id, team_id=2, shooter_id=2, goalie_id=901,
                outcome='Saved', goal=False, xg=0.20, strength_state='EV')

    db.session.add_all([gp, s, ev_f, sh_f, ev_a, sh_a])
    db.session.commit()

    skaters = PlayerSeasonService.get_season_skaters_summary(season='20242025', team_id=1, min_gp=1)
    p_stat = next((p for p in skaters if p['player_id'] == 50), None)
    assert p_stat is not None
    # xG% should be 0.60 / (0.60 + 0.20) * 100 = 75.0%
    assert p_stat['on_ice_5v5']['on_ice_xg_pct'] == pytest.approx(75.0, rel=1e-2)
    assert p_stat['on_ice_5v5']['on_ice_xgf'] == pytest.approx(0.60, rel=1e-2)
    assert p_stat['on_ice_5v5']['on_ice_xga'] == pytest.approx(0.20, rel=1e-2)


def test_season_route_team_filtering_and_leaders_api(client, app, db):
    """
    Verify /season/<season> route preserves team_id and situation parameters,
    and /api/seasons/<season>/leaders accepts team_id.
    """
    cgy = Team(team_id=1, abbreviation='CGY', name='Calgary Flames')
    edm = Team(team_id=2, abbreviation='EDM', name='Edmonton Oilers')
    p1 = Player(player_id=1, first_name='Connor', last_name='Zary', position='F')
    db.session.add_all([cgy, edm, p1])
    db.session.commit()

    g = Game(
        game_id=2024020041, season='20242025', game_date=date(2024, 10, 5),
        game_type='R', home_team_id=1, away_team_id=2, home_score=4, away_score=1, nhl_game_state='FINAL'
    )
    db.session.add(g)
    db.session.flush()

    gp = GamePlayer(game_id=g.game_id, player_id=1, team_id=1, position='F')
    s = Shift(shift_id='s_lead', game_id=g.game_id, player_id=1, period=1, start_time='00:00',
              end_time='10:00', start_elapsed_seconds=0, end_elapsed_seconds=600, duration=600, team_id=1)
    ev = Event(event_id='e_lead', game_id=g.game_id, period=1, period_time='05:00', event_type='goal', team_id=1, primary_player_id=1)
    sh = Shot(shot_id='e_lead', game_id=g.game_id, team_id=1, shooter_id=1, outcome='Goal', goal=True, xg=0.45)
    db.session.add_all([gp, s, ev, sh])
    db.session.commit()

    # 1. Season page request with team_id and situation
    res = client.get('/season/20242025?team_id=1&situation=5v5')
    assert res.status_code == 200
    html = res.data.decode('utf-8')
    # Check that Calgary Flames is in the page and team_id is preserved
    assert 'Calgary Flames' in html
    assert 'value="1" selected' in html or 'selected>Calgary Flames' in html or 'Filtering to' in html

    # 2. Leaders API with team_id
    res_api = client.get('/api/seasons/20242025/leaders?category=skaters&metric=goals&team_id=1')
    assert res_api.status_code == 200
    data = res_api.get_json()
    assert data['season'] == '20242025'
    assert data['team_id'] == 1
    assert 'leaders' in data
    assert len(data['leaders']) > 0
    assert any('Connor' in lead['name'] for lead in data['leaders'])
