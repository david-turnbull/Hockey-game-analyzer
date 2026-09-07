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
    parser = argparse.ArgumentParser(description="Ingest regular season games for an NHL team or league and season.")
    # Optional flags as primary CLI interface
    parser.add_argument("--season", type=str, default=None, help="NHL Season in YYYYYYYY format (e.g. 20242025)")
    parser.add_argument("--team", type=str, default=None, help="Three-letter team abbreviation (e.g. CGY)")
    parser.add_argument("--all", action="store_true", help="Ingest games for all teams in the season")
    parser.add_argument("--limit", type=int, default=None, help="Limit the number of games to ingest")
    parser.add_argument("--refresh", action="store_true", help="Force refresh of cached API files")

    # Positional fallbacks for backward compatibility
    parser.add_argument("pos_team", nargs="?", default=None, help="Optional positional team abbreviation (e.g. CGY)")
    parser.add_argument("pos_season", nargs="?", default=None, help="Optional positional season (e.g. 20232024)")
    args = parser.parse_args()

    # Resolve season
    season = args.season or args.pos_season
    team = args.team or args.pos_team

    # If first positional argument is 8 digits, interpret as season
    if team and len(team) == 8 and team.isdigit() and not season:
        season = team
        team = None

    if not season:
        print("[ERROR] Missing required --season argument (e.g. --season 20242025)")
        sys.exit(1)

    if not team and not args.all:
        # Default to all or prompt team
        print("[INFO] No specific --team provided; running in --all mode for the entire season.")
        all_teams = True
    else:
        all_teams = args.all or (team and team.upper() == 'ALL')

    app = create_app('development')
    with app.app_context():
        orchestrator = PipelineOrchestrator()
        results = orchestrator.ingest_season(
            team_abbr=team.upper() if team else None,
            season=season,
            limit=args.limit,
            force_refresh=args.refresh,
            all_teams=all_teams
        )

        if "error" in results:
            print(f"\n[FAILURE] Ingestion failed: {results['error']}")
            sys.exit(1)

        print("\n" + "=" * 42)
        print("PuckLens Ingestion Validation Summary")
        print("=" * 42)
        print(f"season:                      {results['season']}")
        print(f"games requested:             {results['games_requested']}")
        print(f"games downloaded:            {results['games_downloaded']}")
        print(f"games cached:                {results['games_cached']}")
        print(f"games successfully ingested: {results['games_successfully_ingested']}")
        print(f"games skipped:               {results['games_skipped']}")
        print(f"games failed:                {results['games_failed']}")
        print(f"events:                      {results['events']}")
        print(f"shots:                       {results['shots']}")
        print(f"shifts:                      {results['shifts']}")
        print(f"players:                     {results['players']}")
        print("=" * 42)

if __name__ == '__main__':
    main()
