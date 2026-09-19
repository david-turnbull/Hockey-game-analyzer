import os
import sys
import argparse
from datetime import datetime, timezone

# Ensure project root in sys.path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.append(project_root)

from app import create_app
from data_pipeline.orchestrator import PipelineOrchestrator
from scripts.audit_seasons import audit_season_data

DEFAULT_SEASONS = ['20212022', '20222023', '20232024', '20242025']

def main():
    parser = argparse.ArgumentParser(description="Multi-season regular-season ingestion wrapper for PuckLens historical dataset.")
    parser.add_argument("--seasons", nargs="+", default=DEFAULT_SEASONS, help="List of seasons to ingest (e.g. 20212022 20222023)")
    parser.add_argument("--refresh", action="store_true", help="Force refresh of cached API files")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of games to ingest per season (for testing)")
    args = parser.parse_args()

    seasons = args.seasons

    print("\n" + "=" * 60)
    print(" PuckLens Historical Forecast Dataset Ingestion")
    print("=" * 60)
    print(f"Target Seasons: {', '.join(seasons)}")
    print(f"Force Refresh:  {args.refresh}")
    if args.limit:
        print(f"Limit per season: {args.limit}")
    print("=" * 60 + "\n")

    app = create_app('development')
    with app.app_context():
        orchestrator = PipelineOrchestrator()

        for season in seasons:
            print(f"\n>>> Starting Ingestion for Season {season} <<<")
            results = orchestrator.ingest_season(
                season=season,
                limit=args.limit,
                force_refresh=args.refresh,
                all_teams=True
            )

            if "error" in results:
                print(f"[WARNING] Season {season} ingestion produced an error: {results['error']}")
            else:
                print(f"[{season}] Completed: {results['games_successfully_ingested']} | Cached: {results['games_cached']} | Downloaded: {results['games_downloaded']} | Failed: {results['games_failed']}")

        print("\n" + "=" * 60)
        print(" Running Post-Ingestion Historical Data Coverage Audit...")
        print("=" * 60 + "\n")

        audit_summary = audit_season_data()

        print("\n" + "=" * 60)
        print(" PuckLens Historical Forecast Dataset Summary")
        print("=" * 60)
        for season, s_data in audit_summary.get("seasons", {}).items():
            print(f"{season[:4]}-{season[6:]}: {s_data.get('status', 'UNKNOWN')}")
        print("-" * 60)
        
        tot_expected = sum(s.get("expected_regular_season_games", 0) for s in audit_summary.get("seasons", {}).values())
        tot_actual = sum(s.get("actual_regular_season_games", 0) for s in audit_summary.get("seasons", {}).values())
        tot_synth = sum(s.get("synthetic_games", 0) for s in audit_summary.get("seasons", {}).values())
        tot_dups = sum(s.get("duplicate_game_ids", 0) for s in audit_summary.get("seasons", {}).values())

        pbp_pcts = [s.get("pbp_coverage_pct", 0) for s in audit_summary.get("seasons", {}).values()]
        time_pcts = [s.get("start_time_coverage_pct", 0) for s in audit_summary.get("seasons", {}).values()]
        xg_pcts = [s.get("xg_coverage_pct", 0) for s in audit_summary.get("seasons", {}).values()]
        shift_pcts = [s.get("shift_coverage_pct", 0) for s in audit_summary.get("seasons", {}).values()]

        avg_pbp = sum(pbp_pcts)/len(pbp_pcts) if pbp_pcts else 0
        avg_time = sum(time_pcts)/len(time_pcts) if time_pcts else 0
        avg_xg = sum(xg_pcts)/len(xg_pcts) if xg_pcts else 0
        avg_shift = sum(shift_pcts)/len(shift_pcts) if shift_pcts else 0

        print(f"Games expected: {tot_expected:,}")
        print(f"Games available: {tot_actual:,}")
        print(f"Synthetic games: {tot_synth}")
        print(f"Duplicate games: {tot_dups}")
        print(f"PBP coverage: {avg_pbp:.2f}%")
        print(f"Timestamp coverage: {avg_time:.2f}%")
        print(f"xG coverage: {avg_xg:.2f}%")
        print(f"Shift coverage: {avg_shift:.2f}%")
        print("-" * 60)
        gate_status = "PASSED" if audit_summary.get("hard_gate_passed") else "FAILED (Hard Gate Blocked)"
        print(f"PRODUCTION FORECAST DATA GATE: {gate_status}")
        print("=" * 60 + "\n")

if __name__ == '__main__':
    main()
