import os
import sys
import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

# Ensure project root in sys.path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.append(project_root)

from app import create_app
from data_pipeline.orchestrator import PipelineOrchestrator

logging.basicConfig(level=logging.INFO)

def fast_batch_ingest():
    app = create_app('development')
    with app.app_context():
        orchestrator = PipelineOrchestrator()
        season = '20212022'

        # Fetch official schedule for 20212022
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

        # Parallel normalization helper
        def process_and_normalize(gid):
            try:
                # Ingest game from local raw cache
                success, summary = orchestrator.ingest_game(gid, force_refresh=False)
                return gid, success
            except Exception as e:
                print(f"Error ingesting game {gid}: {e}")
                return gid, False

        print("Executing fast batch ingestion...")
        completed = 0
        success_count = 0

        # Run with max_workers=8 for fast execution
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(process_and_normalize, gid) for gid in sorted_game_ids]
            for f in as_completed(futures):
                gid, succ = f.result()
                completed += 1
                if succ:
                    success_count += 1
                if completed % 100 == 0:
                    print(f"Ingested {completed}/{len(sorted_game_ids)} games into database...")

        print(f"Batch ingestion complete: {success_count}/{len(sorted_game_ids)} successful.")

if __name__ == "__main__":
    fast_batch_ingest()
