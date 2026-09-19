import os
import sys
import logging

# Ensure project root in sys.path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.append(project_root)

from app import create_app
from data_pipeline.orchestrator import PipelineOrchestrator

logging.basicConfig(level=logging.INFO)

def reingest_seasons():
    app = create_app('development')
    with app.app_context():
        orchestrator = PipelineOrchestrator()
        for season in ['20212022', '20222023']:
            print(f"\n==========================================================================")
            print(f" Re-ingesting Season {season} from Official NHL API...")
            print(f"==========================================================================")
            results = orchestrator.ingest_season(season, all_teams=True, force_refresh=True)
            print(f"Season {season} Ingestion Results: {results}")

if __name__ == "__main__":
    reingest_seasons()
