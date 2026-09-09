import pytest
from datetime import date
from app.models import db, Team, Player, Game, Event, Shot, Shift, GamePlayer
from app.services.player_season_service import PlayerSeasonService

def test_skater_season_aggregation_deterministic(app, db):
    """
    Verify individual xG, G - xG, xG/60, shooting %, and expected conversion %
    against hand-calculated expected values.
    """
    team = Team(team_id=1, abbreviation='CGY', name='Calgary Flames')
    skater = Player(player_id=10, first_name='Mikael', last_name='Backlund', position='C')
    skater2 = Player(player_id=99, first_name='Other', last_name='Player', position='W')
    db.session.add_all([team, skater, skater2])
    db.session.commit()

    # Game 1: Backlund plays 1200 seconds (20 mins), scores 1 goal on 3 SOG, 4 unblocked attempts (0.6 xG total), 1 assist
    g1 = Game(
        game_id=2024020001,
        season='20242025',
        game_date=date(2024, 10, 10),
        game_type='R',
        home_team_id=1,
        away_team_id=1,
        home_score=3,
        away_score=2,
        nhl_game_state='FINAL'
    )
    db.session.add(g1)
    db.session.flush()

    gp1 = GamePlayer(game_id=g1.game_id, player_id=10, team_id=1, position='C', sweater_number=11)
    # Shift: 1200 seconds
    shift1 = Shift(
        shift_id='2024020001_10_1_0',
        game_id=g1.game_id,
        player_id=10,
        period=1,
        start_time='00:00',
        end_time='20:00',
        start_elapsed_seconds=0,
        end_elapsed_seconds=1200,
        duration=1200,
        team_id=1,
        is_anomaly=False
    )
    # Goal event
    ev_goal = Event(
        event_id='2024020001_1',
        game_id=g1.game_id,
        period=1,
        period_time='05:00',
        elapsed_game_seconds=300,
        event_type='goal',
        team_id=1,
        primary_player_id=10
    )
    sh_goal = Shot(
        shot_id='2024020001_1',
        game_id=g1.game_id,
        team_id=1,
        shooter_id=10,
        outcome='Goal',
        goal=True,
        xg=0.30,
        distance=15.0,
        angle=10.0
    )
    # Saved shot 1
    ev_s1 = Event(
        event_id='2024020001_2',
        game_id=g1.game_id,
        period=1,
        period_time='10:00',
        elapsed_game_seconds=600,
        event_type='shot-on-goal',
        team_id=1,
        primary_player_id=10
    )
    sh_s1 = Shot(
        shot_id='2024020001_2',
        game_id=g1.game_id,
        team_id=1,
        shooter_id=10,
        outcome='Saved',
        goal=False,
        xg=0.15,
        distance=25.0,
        angle=15.0
    )
    # Saved shot 2
    ev_s2 = Event(
        event_id='2024020001_3',
        game_id=g1.game_id,
        period=1,
        period_time='15:00',
        elapsed_game_seconds=900,
        event_type='shot-on-goal',
        team_id=1,
        primary_player_id=10
    )
    sh_s2 = Shot(
        shot_id='2024020001_3',
        game_id=g1.game_id,
        team_id=1,
        shooter_id=10,
        outcome='Saved',
        goal=False,
        xg=0.10,
        distance=35.0,
        angle=20.0
    )
    # Missed shot (unblocked attempt)
    ev_m = Event(
        event_id='2024020001_4',
        game_id=g1.game_id,
        period=1,
        period_time='18:00',
        elapsed_game_seconds=1080,
        event_type='missed-shot',
        team_id=1,
        primary_player_id=10
    )
    sh_m = Shot(
        shot_id='2024020001_4',
        game_id=g1.game_id,
        team_id=1,
        shooter_id=10,
        outcome='Missed',
        goal=False,
        xg=0.05,
        distance=40.0,
        angle=30.0
    )
    # Assist event (Backlund assists another goal)
    ev_a = Event(
        event_id='2024020001_5',
        game_id=g1.game_id,
        period=1,
        period_time='19:00',
        elapsed_game_seconds=1140,
        event_type='goal',
        team_id=1,
        primary_player_id=99,
        assist1_player_id=10
    )

    db.session.add_all([gp1, shift1, ev_goal, sh_goal, ev_s1, sh_s1, ev_s2, sh_s2, ev_m, sh_m, ev_a])
    db.session.commit()

    stats = PlayerSeasonService.get_skater_season_stats(player_id=10, season='20242025')
    assert stats is not None
    assert stats["gp"] == 1
    assert stats["goals"] == 1
    assert stats["assists"] == 1
    assert stats["points"] == 2
    assert stats["shots_on_goal"] == 3  # 1 Goal + 2 Saved
    assert stats["unblocked_attempts"] == 4  # 1 Goal + 2 Saved + 1 Missed
    
    # xG = 0.30 + 0.15 + 0.10 + 0.05 = 0.60
    assert pytest.approx(stats["xg"], 0.01) == 0.60
    # G - xG = 1 - 0.60 = +0.40
    assert pytest.approx(stats["goals_above_expected"], 0.01) == 0.40

    # TOI: 1200 seconds = 20 mins = 0.3333 hours
    assert stats["toi_seconds"] == 1200
    assert stats["toi_formatted"] == "20:00"

    # Rates per 60:
    # Goals/60 = 1 / (1200/3600) = 3.00
    assert pytest.approx(stats["goals_per_60"], 0.05) == 3.00
    # xG/60 = 0.60 / (1200/3600) = 1.80
    assert pytest.approx(stats["xg_per_60"], 0.05) == 1.80

    # Shooting % = Goals / SOG = 1 / 3 = 33.33%
    assert pytest.approx(stats["shooting_pct"], 0.1) == 33.33
    # Expected Conversion % = xG / Unblocked = 0.60 / 4 = 15.00%
    assert pytest.approx(stats["expected_conversion_pct"], 0.1) == 15.00
    # Shooting % - Expected Conversion % = 33.33 - 15.00 = +18.33%
    assert pytest.approx(stats["shooting_vs_expected_diff"], 0.1) == 18.33

    # Verify on-ice metrics exist and are explicitly segregated
    assert "on_ice_5v5" in stats
    assert "cf" in stats["on_ice_5v5"]
    assert "ff" in stats["on_ice_5v5"]


def test_skater_sample_thresholds_and_leaderboards(app, db):
    """
    Verify configurable minimum sample thresholds (min_gp, min_toi_seconds, min_unblocked_attempts)
    filter properly and do not produce misleading leaderboards.
    """
    team = Team(team_id=20, abbreviation='CGY', name='Calgary Flames')
    p_low = Player(player_id=1, first_name='Low', last_name='Sample', position='F')
    p_high = Player(player_id=2, first_name='High', last_name='Sample', position='F')
    db.session.add_all([team, p_low, p_high])
    db.session.commit()

    g = Game(
        game_id=2024020100, season='20242025', game_date=date(2024, 10, 15),
        game_type='R', home_team_id=20, away_team_id=20, home_score=2, away_score=1,
        nhl_game_state='FINAL'
    )
    db.session.add(g)
    db.session.flush()

    gp_l = GamePlayer(game_id=g.game_id, player_id=1, team_id=20, position='F')
    gp_h = GamePlayer(game_id=g.game_id, player_id=2, team_id=20, position='F')
    # Low sample player has 60s TOI, 1 shot, 1 goal (100% shooting pct)
    s_low = Shift(shift_id='s_low', game_id=g.game_id, player_id=1, period=1, start_time='00:00',
                  end_time='01:00', start_elapsed_seconds=0, end_elapsed_seconds=60, duration=60, team_id=20)
    ev_l = Event(event_id='e_l', game_id=g.game_id, period=1, period_time='00:30', elapsed_game_seconds=30,
                 event_type='goal', team_id=20, primary_player_id=1)
    sh_l = Shot(shot_id='e_l', game_id=g.game_id, team_id=20, shooter_id=1, outcome='Goal', goal=True, xg=0.08)

    # High sample player has 1200s TOI, 10 shots, 2 goals (20% shooting pct)
    s_high = Shift(shift_id='s_high', game_id=g.game_id, player_id=2, period=1, start_time='00:00',
                   end_time='20:00', start_elapsed_seconds=0, end_elapsed_seconds=1200, duration=1200, team_id=20)
    shots_h = []
    events_h = []
    for i in range(10):
        is_g = (i < 2)
        eid = f"e_h_{i}"
        ev = Event(event_id=eid, game_id=g.game_id, period=1, period_time=f"0{i}:00",
                   elapsed_game_seconds=i*60, event_type='goal' if is_g else 'shot-on-goal',
                   team_id=20, primary_player_id=2)
        sh = Shot(shot_id=eid, game_id=g.game_id, team_id=20, shooter_id=2,
                  outcome='Goal' if is_g else 'Saved', goal=is_g, xg=0.15)
        events_h.append(ev)
        shots_h.append(sh)

    db.session.add_all([gp_l, gp_h, s_low, ev_l, sh_l, s_high] + events_h + shots_h)
    db.session.commit()

    # Without threshold: low sample player leads shooting_pct (100% vs 20%)
    unfiltered = PlayerSeasonService.get_skater_leaderboards('20242025', sort_by='shooting_pct', min_unblocked_attempts=0)
    assert unfiltered[0]["player_id"] == 1

    # With threshold (min 5 unblocked attempts): high sample player is leader, low sample excluded!
    filtered = PlayerSeasonService.get_skater_leaderboards('20242025', sort_by='shooting_pct', min_unblocked_attempts=5)
    assert len(filtered) == 1
    assert filtered[0]["player_id"] == 2
