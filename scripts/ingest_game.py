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
    parser = argparse.ArgumentParser(description="Ingest a single NHL game's data.")
    parser.add_argument("game_id", type=int, help="NHL Game ID (e.g. 2023020007)")
    parser.add_argument("--refresh", action="store_true", help="Force refresh of cached API files")
    args = parser.parse_args()

    app = create_app('development')
    with app.app_context():
        orchestrator = PipelineOrchestrator()
        success, summary = orchestrator.ingest_game(args.game_id, force_refresh=args.refresh)
        
        if success:
            print(f"\n[SUCCESS] Game {args.game_id} successfully ingested and loaded!")
            print(f"Total Ingested Records: {summary.get('records_ingested')}")
            print(f"Rejected Records: {summary.get('records_rejected')}")
            print(f"Warnings Emitted: {summary.get('warnings_count')}")
            
            if summary.get('warnings_count', 0) > 0:
                print("\nSample Warnings:")
                # Show up to 5 warnings
                for warn in summary.get('warnings', [])[:5]:
                    ref = f" (Record {warn['record_id']})" if warn.get('record_id') else ""
                    print(f"  - [{warn['category']}] {warn['message']}{ref}")
        else:
            print(f"\n[FAILURE] Ingestion of game {args.game_id} failed!")
            if "error" in summary:
                print(f"Reason: {summary['error']}")

if __name__ == '__main__':
    main()
