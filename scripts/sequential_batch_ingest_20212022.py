import os
import sys
import logging

# Ensure project root in sys.path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.append(project_root)

from app import create_app
from data_pipeline.orchestrator import PipelineOrchestrator

logging.basicConfig(level=logging.WARNING)

def sequential_ingest():
    app = create_app('development')
    with app.app_context():
        orchestrator = PipelineOrchestrator()
        season = '20212022'

        print(f"Fetching official schedule for {season}...")
        teams = [
            'ANA', 'ARI', 'BOS', 'BUF', 'CAR', 'CBJ', 'CGY', 'CHI',
            'COL', 'DAL', 'DET', 'EDM', 'FLA', 'LAK', 'MIN', 'MTL',
            'NJD', 'NSH', 'NYI', 'NYR', 'OTT', 'PHI', 'PIT', 'SEA',
            'SJS', 'STL', 'TBL', 'TOR', 'VAN', 'VGK', 'WPG', 'WSH'
        ]

        game_ids = set()
        for t in teams:
            sched = orchestrator.api_client.get_season_schedule(t, season)
            if sched and "games" in sched:
                for g in sched["games"]:
                    if g.get("gameType") == 2:
                        game_ids.add(g["id"])

        sorted_game_ids = sorted(game_ids)
        print(f"Total regular-season games to ingest for {season}: {len(sorted_game_ids)}")

        completed = 0
        success_count = 0

        for gid in sorted_game_ids:
            try:
                succ, _ = orchestrator.ingest_game(gid, force_refresh=False)
                if succ:
                    success_count += 1
            except Exception as e:
                print(f"Failed game {gid}: {e}")
            completed += 1
            if completed % 100 == 0 or completed == len(sorted_game_ids):
                print(f"Ingested {completed}/{len(sorted_game_ids)} games into database...")

        print(f"Batch ingestion complete: {success_count}/{len(sorted_game_ids)} successful.")

if __name__ == "__main__":
    sequential_ingest()
