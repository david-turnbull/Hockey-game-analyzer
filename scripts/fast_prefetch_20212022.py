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

def prefetch_and_ingest():
    app = create_app('development')
    with app.app_context():
        orchestrator = PipelineOrchestrator()
        season = '20212022'
        
        # 1. Collect schedule
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
        print(f"Total regular-season games to pre-fetch for {season}: {len(sorted_game_ids)}")
        
        def fetch_game_files(gid):
            try:
                orchestrator.api_client.get_play_by_play(gid)
                orchestrator.api_client.get_boxscore(gid)
                orchestrator.api_client.get_shifts(gid)
                return True
            except Exception as e:
                print(f"Error prefetching {gid}: {e}")
                return False

        print("Pre-fetching play-by-play, boxscore, and shifts via ThreadPoolExecutor...")
        completed = 0
        with ThreadPoolExecutor(max_workers=16) as executor:
            futures = [executor.submit(fetch_game_files, gid) for gid in sorted_game_ids]
            for f in as_completed(futures):
                if f.result():
                    completed += 1
                if completed % 100 == 0:
                    print(f"Pre-fetched raw files for {completed}/{len(sorted_game_ids)} games...")

        print(f"Pre-fetch complete: {completed}/{len(sorted_game_ids)} games cached locally.")

        print("\nIngesting season from local raw cache into SQLite database...")
        results = orchestrator.ingest_season(season, all_teams=True, force_refresh=False)
        print(f"Season {season} Ingestion Results: {results}")

if __name__ == "__main__":
    prefetch_and_ingest()
