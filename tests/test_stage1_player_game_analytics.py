import pytest
from datetime import date
from sqlalchemy import func

from app.models import db, Team, Player, Game, Event, Shot, Shift, GamePlayer, PlayerGameAnalytics
from app.services.player_game_analytics_builder import PlayerGameAnalyticsBuilder
from app.services.player_season_service import PlayerSeasonService
from scripts.backfill_player_game_analytics import run_backfill, audit_game_analytics

@pytest.fixture
def stage1_test_dataset(db):
    """
    Sets up a 2-game deterministic season dataset with full lineups (12 players)
    and controlled events/shots/shifts to validate Stage 1 derived analytics & equivalence.
    """
    # Teams
    t1 = Team(team_id=1, abbreviation='CGY', name='Calgary Flames')
    t2 = Team(team_id=2, abbreviation='EDM', name='Edmonton Oilers')
    db.session.add_all([t1, t2])

    # Players
    cgy_c  = Player(player_id=101, first_name='Mikael', last_name='Backlund', position='C')
    cgy_lw = Player(player_id=102, first_name='Blake', last_name='Coleman', position='LW')
    cgy_rw = Player(player_id=103, first_name='Jonathan', last_name='Huberdeau', position='RW')
    cgy_ld = Player(player_id=104, first_name='Rasmus', last_name='Andersson', position='D')
    cgy_rd = Player(player_id=105, first_name='Mackenzie', last_name='Weegar', position='D')
    cgy_g  = Player(player_id=106, first_name='Jacob', last_name='Markstrom', position='G')

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

    # Games
    g1 = Game(game_id=2023020001, season='20232024', game_date=date(2023, 10, 12), game_type='R', home_team_id=1, away_team_id=2, home_score=2, away_score=1, nhl_game_state='FINAL')
    g2 = Game(game_id=2023020002, season='20232024', game_date=date(2023, 10, 14), game_type='R', home_team_id=2, away_team_id=1, home_score=3, away_score=2, nhl_game_state='FINAL')
    db.session.add_all([g1, g2])
    db.session.commit()

    # Populate GamePlayer and Shifts for both games
    for g in [g1, g2]:
        gp_list = [GamePlayer(game_id=g.game_id, player_id=p.player_id, team_id=1 if p in [cgy_c, cgy_lw, cgy_rw, cgy_ld, cgy_rd, cgy_g] else 2, position=p.position) for p in all_players]
        db.session.add_all(gp_list)

        shift_list = [
            Shift(
                shift_id=f'{g.game_id}_{p.player_id}_1_0',
                game_id=g.game_id,
                player_id=p.player_id,
                period=1,
                start_time='00:00',
                end_time='10:00',
                start_elapsed_seconds=0,
                end_elapsed_seconds=600,
                duration=600,
                team_id=1 if p in [cgy_c, cgy_lw, cgy_rw, cgy_ld, cgy_rd, cgy_g] else 2,
                is_anomaly=False
            )
            for p in all_players
        ]
        db.session.add_all(shift_list)

    # Game 1 Events: Goal by 101 (ast 102, xg 0.35), Saved by 201 (xg 0.21)
    ev1 = Event(event_id='2023020001_10', game_id=2023020001, period=1, period_time='02:00', elapsed_game_seconds=120, event_type='goal', team_id=1, primary_player_id=101, assist1_player_id=102, raw_situation_code='1551', home_skaters=5, away_skaters=5, team_strength_state='5v5', manpower_state='EV')
    sh1 = Shot(shot_id='2023020001_10', game_id=2023020001, shooter_id=101, team_id=1, outcome='Goal', xg=0.35)
    ev2 = Event(event_id='2023020001_20', game_id=2023020001, period=1, period_time='05:00', elapsed_game_seconds=300, event_type='shot-on-goal', team_id=2, primary_player_id=201, raw_situation_code='1551', home_skaters=5, away_skaters=5, team_strength_state='5v5', manpower_state='EV')
    sh2 = Shot(shot_id='2023020001_20', game_id=2023020001, shooter_id=201, team_id=2, outcome='Saved', xg=0.21)
    db.session.add_all([ev1, sh1, ev2, sh2])

    # Game 2 Events: Goal by 101 (ast 103, xg 0.40), Goal by 201 (xg 0.50)
    ev3 = Event(event_id='2023020002_10', game_id=2023020002, period=1, period_time='03:00', elapsed_game_seconds=180, event_type='goal', team_id=1, primary_player_id=101, assist1_player_id=103, raw_situation_code='1551', home_skaters=5, away_skaters=5, team_strength_state='5v5', manpower_state='EV')
    sh3 = Shot(shot_id='2023020002_10', game_id=2023020002, shooter_id=101, team_id=1, outcome='Goal', xg=0.40)
    ev4 = Event(event_id='2023020002_20', game_id=2023020002, period=1, period_time='07:00', elapsed_game_seconds=420, event_type='goal', team_id=2, primary_player_id=201, raw_situation_code='1551', home_skaters=5, away_skaters=5, team_strength_state='5v5', manpower_state='EV')
    sh4 = Shot(shot_id='2023020002_20', game_id=2023020002, shooter_id=201, team_id=2, outcome='Goal', xg=0.50)
    db.session.add_all([ev3, sh3, ev4, sh4])

    db.session.commit()

def test_builder_deterministic_game_analytics(app, db, stage1_test_dataset):
    """
    Tests that PlayerGameAnalyticsBuilder generates accurate per-game records for a game.
    """
    records = PlayerGameAnalyticsBuilder.build_game_analytics(2023020001)
    assert len(records) == 10, "Should create analytics records for all 10 skaters"

    rec101 = next(r for r in records if r.player_id == 101)
    assert rec101.game_id == 2023020001
    assert rec101.player_id == 101
    assert rec101.team_id == 1
    assert rec101.season == '20232024'
    assert rec101.goals == 1
    assert rec101.assists == 0
    assert rec101.points == 1
    assert rec101.shots_on_goal == 1
    assert rec101.unblocked_attempts == 1
    assert rec101.individual_xg == 0.35
    assert rec101.toi_seconds == 600
    assert rec101.toi_5v5_seconds == 600
    assert rec101.cf_5v5 == 1
    assert rec101.ca_5v5 == 1
    assert rec101.ff_5v5 == 1
    assert rec101.fa_5v5 == 1
    assert rec101.xgf_5v5 == 0.35
    assert rec101.xga_5v5 == 0.21

def test_builder_idempotency_and_incremental_rebuild(app, db, stage1_test_dataset):
    """
    Tests that building game analytics twice is idempotent and does not duplicate database rows.
    """
    records1 = PlayerGameAnalyticsBuilder.build_game_analytics(2023020001)
    cnt1 = PlayerGameAnalytics.query.filter_by(game_id=2023020001).count()
    assert cnt1 == 10

    # Build again for same game
    records2 = PlayerGameAnalyticsBuilder.build_game_analytics(2023020001)
    cnt2 = PlayerGameAnalytics.query.filter_by(game_id=2023020001).count()
    assert cnt2 == 10, "Idempotent rebuild must replace rows without duplication"

def test_atomic_rebuild_transaction_on_failure(app, db, stage1_test_dataset, monkeypatch):
    """
    Verifies atomic rebuild behavior:
    If building analytics raises an exception during calculation or persistence,
    the transaction is rolled back so pre-existing analytics rows remain intact.
    """
    # 1. Build initial valid analytics for Game 1 (10 rows)
    PlayerGameAnalyticsBuilder.build_game_analytics(2023020001)
    initial_count = PlayerGameAnalytics.query.filter_by(game_id=2023020001).count()
    assert initial_count == 10

    # 2. Monkeypatch _compute_game_5v5_on_ice to simulate a calculation error mid-process
    def mock_failing_compute(*args, **kwargs):
        raise RuntimeError("Simulated mid-build calculation error")

    monkeypatch.setattr(PlayerGameAnalyticsBuilder, "_compute_game_5v5_on_ice", mock_failing_compute)

    # 3. Attempt rebuild and assert exception is raised
    with pytest.raises(RuntimeError, match="Simulated mid-build calculation error"):
        PlayerGameAnalyticsBuilder.build_game_analytics(2023020001)

    # 4. Assert transaction was rolled back and original 10 rows remain untouched
    after_error_count = PlayerGameAnalytics.query.filter_by(game_id=2023020001).count()
    assert after_error_count == 10, "Atomic rollback must preserve original analytics rows when rebuild fails"

def test_partial_analytics_repair_with_force_false(app, db, stage1_test_dataset):
    """
    Tests completeness detection and automatic repair of intentionally partial games:
    - Game 1 is modified to be partial (delete 2 skater rows out of 10).
    - Game 2 remains complete (10 rows).
    - Running backfill with force=False skips Game 2, detects Game 1 as incomplete, and repairs Game 1.
    """
    # 1. Build full analytics for both games (20 rows total)
    run_backfill(season='20232024', force=True)
    assert PlayerGameAnalytics.query.filter_by(season='20232024').count() == 20

    # 2. Intentionally delete 2 rows from Game 1 (leaving 8 out of 10 expected)
    PlayerGameAnalytics.query.filter_by(game_id=2023020001, player_id=101).delete()
    PlayerGameAnalytics.query.filter_by(game_id=2023020001, player_id=102).delete()
    db.session.commit()

    assert PlayerGameAnalytics.query.filter_by(game_id=2023020001).count() == 8
    assert PlayerGameAnalytics.query.filter_by(game_id=2023020002).count() == 10

    # 3. Audit check verifies Game 1 is incomplete and Game 2 is complete
    audit_res = audit_game_analytics(season='20232024')
    assert 2023020001 in audit_res["incomplete"]
    assert 2023020002 in audit_res["complete"]

    # 4. Run backfill with force=False
    summary = run_backfill(season='20232024', force=False)

    # 5. Verify Game 2 was skipped (complete_initial = 1), Game 1 was repaired (repaired = 1), and full 20 rows are restored
    assert summary["complete_initial"] == 1
    assert summary["incomplete_initial"] == 1
    assert summary["repaired"] == 1
    assert summary["skipped"] == 1
    assert PlayerGameAnalytics.query.filter_by(game_id=2023020001).count() == 10
    assert PlayerGameAnalytics.query.filter_by(season='20232024').count() == 20

def test_analytical_equivalence_v14_vs_derived_layer(app, db, stage1_test_dataset):
    """
    Crucial Stage 1 Equivalence Validation:
    Aggregates player_game_analytics additive primitives in SQL across the season
    and compares results against trusted v1.4 PlayerSeasonService outputs.
    """
    # 1. Populate derived analytics for all games
    run_backfill(season='20232024', force=True)

    # 2. Get trusted v1.4 skater summary
    trusted_skaters = PlayerSeasonService.get_season_skaters_summary(season='20232024', include_on_ice_5v5=True)
    assert len(trusted_skaters) == 10

    # 3. Aggregate derived layer using SQL SUM() grouped by player_id
    derived_rows = (
        db.session.query(
            PlayerGameAnalytics.player_id,
            func.count(PlayerGameAnalytics.game_id).label("gp"),
            func.sum(PlayerGameAnalytics.goals).label("goals"),
            func.sum(PlayerGameAnalytics.assists).label("assists"),
            func.sum(PlayerGameAnalytics.points).label("points"),
            func.sum(PlayerGameAnalytics.shots_on_goal).label("shots"),
            func.sum(PlayerGameAnalytics.unblocked_attempts).label("unblocked"),
            func.sum(PlayerGameAnalytics.individual_xg).label("xg"),
            func.sum(PlayerGameAnalytics.toi_seconds).label("toi_seconds"),
            func.sum(PlayerGameAnalytics.toi_5v5_seconds).label("toi_5v5_seconds"),
            func.sum(PlayerGameAnalytics.cf_5v5).label("cf"),
            func.sum(PlayerGameAnalytics.ca_5v5).label("ca"),
            func.sum(PlayerGameAnalytics.ff_5v5).label("ff"),
            func.sum(PlayerGameAnalytics.fa_5v5).label("fa"),
            func.sum(PlayerGameAnalytics.xgf_5v5).label("xgf"),
            func.sum(PlayerGameAnalytics.xga_5v5).label("xga")
        )
        .filter(PlayerGameAnalytics.season == '20232024')
        .group_by(PlayerGameAnalytics.player_id)
        .all()
    )

    derived_map = {r.player_id: r for r in derived_rows}

    # 4. Assert exact numerical equivalence for every skater
    for trusted in trusted_skaters:
        pid = trusted["player_id"]
        assert pid in derived_map, f"Player {pid} missing from derived analytics aggregation"
        der = derived_map[pid]

        # Individual Counting Stats Equivalence
        assert der.gp == trusted["gp"]
        assert der.goals == trusted["goals"]
        assert der.assists == trusted["assists"]
        assert der.points == trusted["points"]
        assert der.shots == trusted["shots"]
        assert der.unblocked == trusted["unblocked_attempts"]
        assert abs(der.xg - trusted["xg"]) < 0.01
        assert der.toi_seconds == trusted["toi_seconds"]

        # 5v5 On-Ice Primitives Equivalence
        oi = trusted["on_ice_5v5"]
        assert der.cf == oi["cf"]
        assert der.ca == oi["ca"]
        assert der.ff == oi["ff"]
        assert der.fa == oi["fa"]
        assert abs(der.xgf - oi["on_ice_xgf"]) < 0.01
        assert abs(der.xga - oi["on_ice_xga"]) < 0.01
        assert der.toi_5v5_seconds == oi["toi_seconds"]

        # Aggregated Ratio Equivalence
        tot_c = der.cf + der.ca
        derived_cf_pct = round((der.cf / tot_c * 100), 2) if tot_c > 0 else 50.0
        assert abs(derived_cf_pct - oi["cf_pct"]) < 0.01

        tot_f = der.ff + der.fa
        derived_ff_pct = round((der.ff / tot_f * 100), 2) if tot_f > 0 else 50.0
        assert abs(derived_ff_pct - oi["ff_pct"]) < 0.01

        tot_xg = der.xgf + der.xga
        derived_xg_pct = round((der.xgf / tot_xg * 100), 2) if tot_xg > 0 else 50.0
        assert abs(derived_xg_pct - oi["on_ice_xg_pct"]) < 0.01
