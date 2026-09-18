import os
import sys
import json
from datetime import datetime, timezone

# Ensure project root in sys.path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.append(project_root)

from app import create_app
from app.models import db, Game
from data_pipeline.orchestrator import PipelineOrchestrator
from scripts.audit_seasons import audit_season_data, audit_stage4_external_season_gate

def reingest_missing_games(season: str = '20252026'):
    app = create_app('development')
    with app.app_context():
        print("\n" + "=" * 75)
        print(f" PuckLens v1.4.0 Re-ingesting Missing Games ({season[:4]}-{season[6:]})")
        print("=" * 75)

        orchestrator = PipelineOrchestrator()

        # Load missing games JSON report
        json_path = os.path.join(project_root, "reports", f"stage4_missing_games_{season}.json")
        if not os.path.exists(json_path):
            from scripts.identify_missing_20252026_games import identify_missing_games
            identify_missing_games(season)

        with open(json_path, "r", encoding="utf-8") as f:
            missing_report = json.load(f)

        missing_games = missing_report.get("missing_games", [])
        missing_count = len(missing_games)
        print(f"Targeting {missing_count} missing games for re-ingestion...")

        successful = 0
        failed = 0

        for idx, item in enumerate(missing_games, 1):
            gid = item["game_id"]
            print(f"[{idx}/{missing_count}] Ingesting Missing Game ID: {gid} ({item['home_team']} vs {item['away_team']})...")
            success, summary = orchestrator.ingest_game(gid, force_refresh=True)

            if success:
                successful += 1
                print(f"  -> SUCCESS ({summary.get('events_count', 0)} events, {summary.get('shots_count', 0)} shots)")
            else:
                failed += 1
                print(f"  -> FAILED: {summary.get('error', 'Unknown ingestion failure')}")

        print("\n" + "=" * 75)
        print(f" Re-ingestion Completed: {successful} successful, {failed} failed out of {missing_count}")
        print("=" * 75)

        # Rerun audit
        print("\nRunning post-reingestion Stage 4 audit gate...")
        passed, gate_reasons, snapshot_hash = audit_stage4_external_season_gate(season)

        print("\n" + "=" * 75)
        print(" Stage 4 Data Audit Gate Results")
        print("=" * 75)
        print(f" Gate Passed:            {passed}")
        print(f" Snapshot Hash:          {snapshot_hash}")
        if not passed:
            print(" Reasons for failure:")
            for r in gate_reasons:
                print(f"   - {r}")
        else:
            print(" PRODUCTION DATA GATE: COMPLETE & PASSED (1,312/1,312 Games)")
        print("=" * 75 + "\n")

        audit_season_data()
        return passed

if __name__ == "__main__":
    reingest_missing_games()
