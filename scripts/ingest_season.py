import os
import sys
import argparse

# Ensure project root in sys.path so we can run from anywhere
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.append(project_root)

from app import create_app
from data_pipeline.orchestrator import PipelineOrchestrator

def main():
    parser = argparse.ArgumentParser(description="Ingest regular season games for an NHL team and season.")
    parser.add_argument("team", type=str, help="Three-letter team abbreviation (e.g. CGY)")
    parser.add_argument("season", type=str, help="NHL Season in YYYYYYYY format (e.g. 20232024)")
    parser.add_argument("--limit", type=int, default=None, help="Limit the number of games to ingest")
    parser.add_argument("--refresh", action="store_true", help="Force refresh of cached API files")
    args = parser.parse_args()

    app = create_app('development')
    with app.app_context():
        orchestrator = PipelineOrchestrator()
        results = orchestrator.ingest_season(
            args.team.upper(), 
            args.season, 
            limit=args.limit, 
            force_refresh=args.refresh
        )
        
        if "error" in results:
            print(f"\n[FAILURE] Ingestion failed: {results['error']}")
            return
            
        print(f"\n[SUMMARY] Ingestion complete for {args.team.upper()} ({args.season}):")
        print(f"Total Games in Schedule: {results['total_games']}")
        print(f"Processed Games: {results['processed_games']}")
        print(f"Successfully Ingested: {results['successful_games']}")
        print(f"Skipped or Failed: {results['failed_games']}")

if __name__ == '__main__':
    main()
