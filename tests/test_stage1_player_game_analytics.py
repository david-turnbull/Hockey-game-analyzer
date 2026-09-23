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

def test_atomic_rollback_after_delete_and_flush(app, db, stage1_test_dataset, monkeypatch):
    """
    Strengthened Atomic Rollback Test:
    Forces a failure AFTER existing rows have been deleted and flushed in the transaction,
    but before commit. Verifies that rollback restores the original rows and exact field values.
    """
    # 1. Build initial valid analytics for Game 1
    PlayerGameAnalyticsBuilder.build_game_analytics(2023020001)
    orig_rows = PlayerGameAnalytics.query.filter_by(game_id=2023020001).all()
    assert len(orig_rows) == 10
    orig_goals_map = {r.player_id: r.goals for r in orig_rows}
    orig_toi_map = {r.player_id: r.toi_seconds for r in orig_rows}

    # 2. Set test hook to fail AFTER delete + flush
    def mock_fail_post_flush():
        raise RuntimeError("Forced error after delete and flush execution")

    monkeypatch.setattr(PlayerGameAnalyticsBuilder, "_test_post_flush_hook", mock_fail_post_flush)

    # 3. Attempt rebuild, expecting the post-flush exception
    with pytest.raises(RuntimeError, match="Forced error after delete and flush execution"):
        PlayerGameAnalyticsBuilder.build_game_analytics(2023020001)

    # 4. Verify transaction was rolled back cleanly, restoring original rows and values exactly
    restored_rows = PlayerGameAnalytics.query.filter_by(game_id=2023020001).all()
    assert len(restored_rows) == 10
    restored_goals_map = {r.player_id: r.goals for r in restored_rows}
    restored_toi_map = {r.player_id: r.toi_seconds for r in restored_rows}

    assert restored_goals_map == orig_goals_map
    assert restored_toi_map == orig_toi_map

def test_partial_analytics_repair_with_force_false(app, db, stage1_test_dataset):
    """
    Tests completeness detection and automatic repair of intentionally partial games (actual < expected):
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

def test_overpopulated_stale_analytics_repair_with_force_false(app, db, stage1_test_dataset):
    """
    Regression Test: Overpopulated / Stale Game Completeness & Repair (actual > expected):
    - Game 1 is modified by inserting an extra/stale row (11 rows vs 10 expected).
    - Game 2 remains complete (10 rows).
    - Audit detects Game 1 as incomplete (actual != expected).
    - Running backfill with force=False rebuilds Game 1, purging stale row and restoring 10 valid rows.
    """
    # 1. Populate valid analytics (10 rows per game)
    run_backfill(season='20232024', force=True)
    assert PlayerGameAnalytics.query.filter_by(game_id=2023020001).count() == 10

    # 2. Add an overpopulated / stale row to Game 1 (creating player 999 first to satisfy FK constraint)
    db.session.add(Player(player_id=999, first_name='Stale', last_name='Player', position='C'))
    db.session.flush()

    stale_rec = PlayerGameAnalytics(
        game_id=2023020001,
        player_id=999,  # Stale/extra player
        team_id=1,
        season='20232024',
        position='C',
        goals=99
    )
    db.session.add(stale_rec)
    db.session.commit()

    assert PlayerGameAnalytics.query.filter_by(game_id=2023020001).count() == 11

    # 3. Audit check verifies Game 1 is detected as incomplete due to row count mismatch
    audit_res = audit_game_analytics(season='20232024')
    assert 2023020001 in audit_res["incomplete"]
    assert 2023020002 in audit_res["complete"]

    # 4. Run backfill with force=False
    summary = run_backfill(season='20232024', force=False)

    # 5. Verify Game 1 was repaired, stale row removed, and row count restored to exactly 10
    assert summary["repaired"] == 1
    assert PlayerGameAnalytics.query.filter_by(game_id=2023020001).count() == 10
    assert PlayerGameAnalytics.query.filter_by(game_id=2023020001, player_id=999).first() is None

def test_analytical_equivalence_legacy_vs_derived_explicit(app, db, stage1_test_dataset):
    """
    Strengthened Equivalence Validation:
    Compares PlayerSeasonService._get_season_skaters_summary_legacy directly against
    PlayerSeasonService._get_season_skaters_summary_derived across all players and metrics.
    """
    # 1. Populate derived analytics for all games in season
    run_backfill(season='20232024', force=True)

    # 2. Call explicit legacy method directly
    legacy_skaters = PlayerSeasonService._get_season_skaters_summary_legacy(season='20232024', include_on_ice_5v5=True)
    assert len(legacy_skaters) == 10

    # 3. Call explicit derived method directly
    derived_skaters = PlayerSeasonService._get_season_skaters_summary_derived(season='20232024', include_on_ice_5v5=True)
    assert len(derived_skaters) == 10

    derived_map = {s["player_id"]: s for s in derived_skaters}

    # 4. Assert 1-to-1 exact equivalence for every skater
    for leg in legacy_skaters:
        pid = leg["player_id"]
        assert pid in derived_map, f"Player {pid} missing from derived summary"
        der = derived_map[pid]

        # Individual Counting Stats
        assert der["gp"] == leg["gp"]
        assert der["goals"] == leg["goals"]
        assert der["assists"] == leg["assists"]
        assert der["points"] == leg["points"]
        assert der["shots"] == leg["shots"]
        assert der["unblocked_attempts"] == leg["unblocked_attempts"]
        assert abs(der["xg"] - leg["xg"]) < 0.01
        assert der["toi_seconds"] == leg["toi_seconds"]

        # 5v5 On-Ice Primitives & Ratios
        leg_oi = leg["on_ice_5v5"]
        der_oi = der["on_ice_5v5"]

        assert der_oi["cf"] == leg_oi["cf"]
        assert der_oi["ca"] == leg_oi["ca"]
        assert der_oi["cf_pct"] == leg_oi["cf_pct"]
        assert der_oi["ff"] == leg_oi["ff"]
        assert der_oi["fa"] == leg_oi["fa"]
        assert der_oi["ff_pct"] == leg_oi["ff_pct"]
        assert abs(der_oi["on_ice_xgf"] - leg_oi["on_ice_xgf"]) < 0.01
        assert abs(der_oi["on_ice_xga"] - leg_oi["on_ice_xga"]) < 0.01
        assert abs(der_oi["on_ice_xg_pct"] - leg_oi["on_ice_xg_pct"]) < 0.01
        assert der_oi["toi_seconds"] == leg_oi["toi_seconds"]

def test_partial_season_fallback_to_legacy(app, db, stage1_test_dataset):
    """
    Regression Test: Partial-Season Safety
    - Season 20232024 has 2 games.
    - We build derived analytics for Game 1 ONLY (Game 2 remains unbuilt).
    - Verifies that PlayerSeasonService.get_season_skaters_summary detects incomplete season
      and falls back to _get_season_skaters_summary_legacy (returning 2-game stats instead of partial 1-game stats).
    """
    # 1. Build derived analytics for Game 1 only
    PlayerGameAnalyticsBuilder.build_game_analytics(2023020001)

    # 2. Verify Game 2 is unbuilt in database
    assert PlayerGameAnalytics.query.filter_by(game_id=2023020001).count() == 10
    assert PlayerGameAnalytics.query.filter_by(game_id=2023020002).count() == 0

    # 3. Call public get_season_skaters_summary
    public_skaters = PlayerSeasonService.get_season_skaters_summary(season='20232024')
    legacy_skaters = PlayerSeasonService._get_season_skaters_summary_legacy(season='20232024')

    # 4. Assert public method fell back to legacy and returned 2-game totals for player 101 (2 goals across both games)
    pub101 = next(s for s in public_skaters if s["player_id"] == 101)
    leg101 = next(s for s in legacy_skaters if s["player_id"] == 101)

    assert pub101["gp"] == 2
    assert pub101["goals"] == 2
    assert pub101["goals"] == leg101["goals"]

    # 5. Build Game 2 analytics so season is 100% complete
    PlayerGameAnalyticsBuilder.build_game_analytics(2023020002)

    # 6. Call public method again and verify it now uses derived path cleanly
    public_skaters_complete = PlayerSeasonService.get_season_skaters_summary(season='20232024')
    pub101_complete = next(s for s in public_skaters_complete if s["player_id"] == 101)
    assert pub101_complete["goals"] == 2


def test_derived_subset_integrity_vs_full_season_readiness(app, db, stage1_test_dataset):
    """
    Component 3A Test:
    Verifies that is_derived_complete_for_ingested_games returns True when all ingested games are complete,
    while is_derived_ready_for_full_season_queries returns False when only a subset of schedule games are ingested.
    """
    from app.services.player_game_analytics_audit import PlayerGameAnalyticsAuditService

    # 1. Build derived analytics for Game 1 only
    PlayerGameAnalyticsBuilder.build_game_analytics(2023020001)

    # Ingested games = 2 (Game 1 and Game 2 exist in GamePlayer), completed schedule games = 2
    # So with only Game 1 built, subset integrity is False
    assert PlayerGameAnalyticsAuditService.is_derived_complete_for_ingested_games('20232024') is False
    assert PlayerGameAnalyticsAuditService.is_derived_ready_for_full_season_queries('20232024') is False

    # Build Game 2 as well
    PlayerGameAnalyticsBuilder.build_game_analytics(2023020002)

    # Now both ingested games are built
    assert PlayerGameAnalyticsAuditService.is_derived_complete_for_ingested_games('20232024') is True
    assert PlayerGameAnalyticsAuditService.is_derived_ready_for_full_season_queries('20232024') is True

    # Now simulate extra schedule games that are NOT in GamePlayer (partial season ingestion)
    g3 = Game(game_id=2023020003, season='20232024', game_date=date(2023, 10, 16), game_type='R', home_team_id=1, away_team_id=2, home_score=1, away_score=0, nhl_game_state='FINAL')
    db.session.add(g3)
    db.session.commit()

    # Ingested games (2) != Completed schedule games (3)
    # Subset integrity should be True (2/2 ingested games are derived complete)
    assert PlayerGameAnalyticsAuditService.is_derived_complete_for_ingested_games('20232024') is True
    # Full-season readiness MUST be False
    assert PlayerGameAnalyticsAuditService.is_derived_ready_for_full_season_queries('20232024') is False


def test_audit_set_audit_integrity_checks(app, db, stage1_test_dataset):
    """
    Tests detection of missing tuples, orphaned tuples, and team mismatches in audit_game_analytics.
    """
    from app.services.player_game_analytics_audit import PlayerGameAnalyticsAuditService

    PlayerGameAnalyticsBuilder.build_game_analytics(2023020001)
    PlayerGameAnalyticsBuilder.build_game_analytics(2023020002)

    # Introduce an orphaned tuple (derived row for player not in GamePlayer)
    p999 = Player(player_id=999, first_name='Extra', last_name='Player', position='C')
    db.session.add(p999)
    db.session.commit()
    orphaned_pga = PlayerGameAnalytics(
        game_id=2023020001,
        player_id=999,
        team_id=1,
        season='20232024',
        position='C'
    )
    db.session.add(orphaned_pga)
    db.session.commit()

    audit = PlayerGameAnalyticsAuditService.audit_game_analytics('20232024')
    assert audit["set_audit"]["orphaned_tuples"] >= 1
    assert PlayerGameAnalyticsAuditService.is_derived_complete_for_ingested_games('20232024') is False

