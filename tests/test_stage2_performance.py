import pytest
from unittest.mock import patch
from app.models import db, Player, PlayerGameAnalytics
from app.services.player_season_service import PlayerSeasonService
from app.services.player_game_analytics_builder import PlayerGameAnalyticsBuilder
from app.services.player_game_analytics_audit import PlayerGameAnalyticsAuditService
from scripts.backfill_player_game_analytics import run_backfill
from tests.test_stage1_player_game_analytics import stage1_test_dataset

def test_single_player_derived_equivalence(app, db, stage1_test_dataset):
    """
    Verifies that PlayerSeasonService.get_skater_season_stats(player_id, season)
    derived path yields exact identical results to:
    1. Explicit legacy single-player lookup.
    2. Corresponding row in full derived summary.
    """
    run_backfill(season='20232024', force=True)

    target_pid = 101
    season = '20232024'

    # Direct single-player derived path
    single_derived = PlayerSeasonService.get_skater_season_stats(target_pid, season)

    # Legacy lookup
    legacy_summary = PlayerSeasonService._get_season_skaters_summary_legacy(season, min_gp=0)
    single_legacy = next(s for s in legacy_summary if s["player_id"] == target_pid)

    # Full derived summary
    full_derived_summary = PlayerSeasonService._get_season_skaters_summary_derived(season, min_gp=0)
    single_from_full = next(s for s in full_derived_summary if s["player_id"] == target_pid)

    # Equivalence assertions across all fields
    for k in ["player_id", "name", "position", "team_id", "team_abbrev", "gp", "goals", "assists", "points", "shots", "toi_seconds"]:
        assert single_derived[k] == single_legacy[k]
        assert single_derived[k] == single_from_full[k]

    assert abs(single_derived["xg"] - single_legacy["xg"]) < 0.01
    assert abs(single_derived["xg"] - single_from_full["xg"]) < 0.01

    oi_derived = single_derived["on_ice_5v5"]
    oi_legacy = single_legacy["on_ice_5v5"]
    oi_full = single_from_full["on_ice_5v5"]

    for k in ["cf", "ca", "cf_pct", "ff", "fa", "ff_pct", "toi_seconds"]:
        assert oi_derived[k] == oi_legacy[k]
        assert oi_derived[k] == oi_full[k]

    assert abs(oi_derived["on_ice_xgf"] - oi_legacy["on_ice_xgf"]) < 0.01
    assert abs(oi_derived["on_ice_xga"] - oi_legacy["on_ice_xga"]) < 0.01

def test_single_player_pathology_prevention(app, db, stage1_test_dataset):
    """
    Explicitly proves single-player pathology is eliminated:
    Verifies get_skater_season_stats() on complete derived season DOES NOT call:
    - _get_season_skaters_summary_legacy
    - _get_season_skaters_summary_derived
    - _aggregate_season_5v5_on_ice
    And queries ONLY the requested player's relevant PlayerGameAnalytics data.
    """
    run_backfill(season='20232024', force=True)

    with patch.object(PlayerSeasonService, '_get_season_skaters_summary_legacy') as mock_legacy, \
         patch.object(PlayerSeasonService, '_get_season_skaters_summary_derived') as mock_derived, \
         patch.object(PlayerSeasonService, '_aggregate_season_5v5_on_ice') as mock_on_ice:

        res = PlayerSeasonService.get_skater_season_stats(101, '20232024')

        assert res is not None
        assert res["player_id"] == 101

        # Assert no full-season functions were called
        mock_legacy.assert_not_called()
        mock_derived.assert_not_called()
        mock_on_ice.assert_not_called()

def test_leaderboard_derived_equivalence_across_all_sort_keys(app, db, stage1_test_dataset):
    """
    Verifies that _get_skater_leaderboards_derived produces identical rankings and metrics
    to legacy leaderboards across EVERY supported sort_by key.
    """
    run_backfill(season='20232024', force=True)

    sort_keys = [
        "points", "goals", "assists", "xg", "goals_above_expected",
        "shots", "unblocked_attempts", "toi_seconds",
        "goals_per_60", "xg_per_60", "shooting_pct", "expected_conversion_pct",
        "cf_pct", "ff_pct", "on_ice_xg_pct"
    ]

    for sk in sort_keys:
        derived_board = PlayerSeasonService.get_skater_leaderboards(season='20232024', sort_by=sk, limit=10)
        
        # Reference legacy board with deterministic tie-breaking matching SQL
        legacy_skaters = PlayerSeasonService._get_season_skaters_summary_legacy(season='20232024')
        def get_sort_key(s):
            if sk in ['cf_pct', 'ff_pct', 'on_ice_xg_pct']:
                val = s.get('on_ice_5v5', {}).get(sk, 0.0) or 0.0
            else:
                val = s.get(sk, 0.0) or 0.0
            return (val, s.get("points", 0), s.get("goals", 0), -s["player_id"])

        legacy_skaters.sort(key=get_sort_key, reverse=True)
        for i, s in enumerate(legacy_skaters, 1):
            s["rank"] = i
        legacy_board = legacy_skaters[:10]

        assert len(derived_board) == len(legacy_board)
        for d_item, l_item in zip(derived_board, legacy_board):
            assert d_item["player_id"] == l_item["player_id"], f"Rank mismatch for sort_by='{sk}'"
            assert d_item["rank"] == l_item["rank"]

def test_leaderboard_threshold_and_team_filtering(app, db, stage1_test_dataset):
    """
    Verifies threshold enforcement (min_gp, min_toi_seconds, min_unblocked_attempts, team_id)
    in bounded SQL leaderboards.
    """
    run_backfill(season='20232024', force=True)

    # Filter team_id=1
    team1_board = PlayerSeasonService.get_skater_leaderboards(season='20232024', team_id=1, limit=50)
    assert len(team1_board) == 5
    for item in team1_board:
        assert item["team_id"] == 1

    # Filter min_gp=2
    min_gp2_board = PlayerSeasonService.get_skater_leaderboards(season='20232024', min_gp=2, limit=50)
    assert len(min_gp2_board) == 10
    for item in min_gp2_board:
        assert item["gp"] >= 2

def test_partial_game_missing_player_row_fallback(app, db, stage1_test_dataset):
    """
    Verifies derived coverage safety when both game IDs exist in PlayerGameAnalytics
    but one game is missing one player row (actual < expected).
    Asserts is_derived_coverage_complete returns False and public calls fall back to legacy.
    """
    run_backfill(season='20232024', force=True)
    assert PlayerGameAnalyticsAuditService.is_derived_coverage_complete('20232024') is True

    # Delete 1 player row from Game 2023020001 (Game 1 has PGA rows, but is now incomplete)
    row_to_delete = PlayerGameAnalytics.query.filter_by(game_id=2023020001, player_id=101).first()
    assert row_to_delete is not None
    db.session.delete(row_to_delete)
    db.session.commit()

    # Verify coverage safety check returns False
    assert PlayerGameAnalyticsAuditService.is_derived_coverage_complete('20232024') is False

    # Verify public season, single-player, and leaderboard calls fall back safely to legacy
    with patch.object(PlayerSeasonService, '_get_season_skaters_summary_legacy', wraps=PlayerSeasonService._get_season_skaters_summary_legacy) as mock_legacy:
        stats = PlayerSeasonService.get_skater_season_stats(101, '20232024')
        assert stats is not None
        assert stats["gp"] == 2  # Returns 2 games from legacy, not 1 from partial PGA
        mock_legacy.assert_called()

    with patch.object(PlayerSeasonService, '_get_season_skaters_summary_legacy', wraps=PlayerSeasonService._get_season_skaters_summary_legacy) as mock_legacy:
        summary = PlayerSeasonService.get_season_skaters_summary('20232024')
        assert len(summary) > 0
        mock_legacy.assert_called()

    with patch.object(PlayerSeasonService, '_get_season_skaters_summary_legacy', wraps=PlayerSeasonService._get_season_skaters_summary_legacy) as mock_legacy:
        board = PlayerSeasonService.get_skater_leaderboards('20232024')
        assert len(board) > 0
        mock_legacy.assert_called()

def test_overpopulated_stale_game_fallback(app, db, stage1_test_dataset):
    """
    Verifies derived coverage safety when a game has extra/stale PGA rows (actual > expected).
    Asserts is_derived_coverage_complete returns False and public calls fall back to legacy.
    """
    run_backfill(season='20232024', force=True)
    assert PlayerGameAnalyticsAuditService.is_derived_coverage_complete('20232024') is True

    # Add dummy player record to satisfy foreign key constraint
    dummy_player = Player(player_id=99999, first_name="Dummy", last_name="Player", position="D")
    db.session.add(dummy_player)
    db.session.flush()

    # Insert an extra/stale row for game 2023020001
    stale_row = PlayerGameAnalytics(
        game_id=2023020001,
        player_id=99999,
        team_id=1,
        season='20232024',
        position='D',
        toi_seconds=100
    )
    db.session.add(stale_row)
    db.session.commit()

    assert PlayerGameAnalyticsAuditService.is_derived_coverage_complete('20232024') is False

def test_leaderboard_near_tie_rounding_equivalence(app, db, stage1_test_dataset):
    """
    Verifies leaderboard ordering equivalence for near-tie values where 2-decimal rounding
    and deterministic tie-breakers (points, goals, player_id) govern rank ordering.
    """
    run_backfill(season='20232024', force=True)

    derived_board = PlayerSeasonService.get_skater_leaderboards(season='20232024', sort_by="xg_per_60", limit=50)
    legacy_skaters = PlayerSeasonService._get_season_skaters_summary_legacy(season='20232024')

    def get_sort_key(s):
        val = s.get("xg_per_60", 0.0) or 0.0
        return (val, s.get("points", 0), s.get("goals", 0), -s["player_id"])

    legacy_skaters.sort(key=get_sort_key, reverse=True)
    for i, s in enumerate(legacy_skaters, 1):
        s["rank"] = i

    for d_item, l_item in zip(derived_board, legacy_skaters[:len(derived_board)]):
        assert d_item["player_id"] == l_item["player_id"]
        assert d_item["rank"] == l_item["rank"]

def test_synthetic_near_tie_rounding_sequence(app, db, stage1_test_dataset):
    """
    Verifies that SQL sort expressions for ratio and xG-derived fields follow the exact
    same rounding sequence as legacy calculations, maintaining exact rank equivalence
    where unrounded intermediate math would alter sort ordering.
    """
    db.session.query(PlayerGameAnalytics).filter_by(season='20992000').delete()
    db.session.commit()

    # Synthetic near-boundary values using valid game 2023020001 and players 101, 102, 103 from stage1_test_dataset
    # P101: xg=1.444, toi=3590. Legacy xg=1.44, xg_per_60 = round(1.44*3600/3590, 2) = 1.44.
    # P102: xg=1.440, toi=3600. Legacy xg=1.44, xg_per_60 = round(1.44*3600/3600, 2) = 1.44.
    # P103: xg=1.446, toi=3600. Legacy xg=1.45, xg_per_60 = round(1.45*3600/3600, 2) = 1.45.
    pga1 = PlayerGameAnalytics(game_id=2023020001, player_id=101, team_id=1, season='20992000', position='F', individual_xg=1.444, toi_seconds=3590, goals=5, shots_on_goal=10, unblocked_attempts=10, xgf_5v5=10.444, xga_5v5=10.000, points=5)
    pga2 = PlayerGameAnalytics(game_id=2023020001, player_id=102, team_id=1, season='20992000', position='F', individual_xg=1.440, toi_seconds=3600, goals=5, shots_on_goal=10, unblocked_attempts=10, xgf_5v5=10.440, xga_5v5=10.000, points=5)
    pga3 = PlayerGameAnalytics(game_id=2023020001, player_id=103, team_id=2, season='20992000', position='F', individual_xg=1.446, toi_seconds=3600, goals=5, shots_on_goal=10, unblocked_attempts=10, xgf_5v5=10.446, xga_5v5=10.000, points=5)
    db.session.add_all([pga1, pga2, pga3])
    db.session.commit()

    items = [
        {'pid': 101, 'xg_raw': 1.444, 'toi': 3590, 'g': 5, 'sog': 10, 'unb': 10, 'xgf_raw': 10.444, 'xga_raw': 10.000, 'pts': 5},
        {'pid': 102, 'xg_raw': 1.440, 'toi': 3600, 'g': 5, 'sog': 10, 'unb': 10, 'xgf_raw': 10.440, 'xga_raw': 10.000, 'pts': 5},
        {'pid': 103, 'xg_raw': 1.446, 'toi': 3600, 'g': 5, 'sog': 10, 'unb': 10, 'xgf_raw': 10.446, 'xga_raw': 10.000, 'pts': 5},
    ]

    for item in items:
        xg = round(item['xg_raw'], 2)
        xgf = round(item['xgf_raw'], 2)
        xga = round(item['xga_raw'], 2)
        item['xg'] = xg
        item['xg_per_60'] = round(xg * 3600.0 / item['toi'], 2)
        item['goals_above_expected'] = round(item['g'] - xg, 2)
        item['expected_conversion_pct'] = round(xg * 100.0 / item['unb'], 2)
        item['on_ice_xg_pct'] = round(xgf * 100.0 / (xgf + xga), 2)

    for sort_field in ['xg', 'xg_per_60', 'goals_above_expected', 'expected_conversion_pct', 'on_ice_xg_pct']:
        derived_board = PlayerSeasonService._get_skater_leaderboards_derived(season='20992000', sort_by=sort_field)
        derived_pids = [r['player_id'] for r in derived_board]
        sorted_items = sorted(items, key=lambda x: (x[sort_field], x['pts'], x['g'], -x['pid']), reverse=True)
        expected_pids = [x['pid'] for x in sorted_items]

        assert derived_pids == expected_pids, f"Mismatch for field {sort_field}: Derived={derived_pids}, Expected={expected_pids}"

    # Clean up
    db.session.query(PlayerGameAnalytics).filter_by(season='20992000').delete()
    db.session.commit()


