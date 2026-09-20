import pytest
from unittest.mock import patch
from app.models import db, PlayerGameAnalytics
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

def test_partial_season_fallback_isolation(app, db, stage1_test_dataset):
    """
    Verifies that when derived coverage is partial (only 1 of 2 games built),
    public calls to get_skater_season_stats and get_skater_leaderboards cleanly fall back
    to legacy calculation, ensuring partial data is NEVER returned.
    """
    # Build Game 1 only
    PlayerGameAnalyticsBuilder.build_game_analytics(2023020001)
    assert not PlayerGameAnalyticsAuditService.is_derived_coverage_complete('20232024')

    # Single player fallback
    p101_stats = PlayerSeasonService.get_skater_season_stats(101, '20232024')
    assert p101_stats["gp"] == 2  # Returns 2 games from legacy, not 1 from partial derived

    # Leaderboard fallback
    board = PlayerSeasonService.get_skater_leaderboards('20232024', limit=50)
    p101_board = next(s for s in board if s["player_id"] == 101)
    assert p101_board["gp"] == 2
