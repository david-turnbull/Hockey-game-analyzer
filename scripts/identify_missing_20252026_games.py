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

def identify_missing_games(season: str = '20252026'):
    app = create_app('development')
    with app.app_context():
        print("\n" + "=" * 75)
        print(f" PuckLens v1.4.0 Missing Games Diagnostic Audit ({season[:4]}-{season[6:]})")
        print("=" * 75)

        orchestrator = PipelineOrchestrator()
        teams = [
            'ANA', 'BOS', 'BUF', 'CAR', 'CBJ', 'CGY', 'CHI', 'COL',
            'DAL', 'DET', 'EDM', 'FLA', 'LAK', 'MIN', 'MTL', 'NJD',
            'NSH', 'NYI', 'NYR', 'OTT', 'PHI', 'PIT', 'SEA', 'SJS',
            'STL', 'TBL', 'TOR', 'UTA', 'VAN', 'VGK', 'WPG', 'WSH'
        ]

        print(f"Force-refreshing official NHL schedule across all {len(teams)} teams...")
        official_schedule_games = {}

        for team in teams:
            sched = orchestrator.api_client.get_season_schedule(team, season, force_refresh=True)
            if sched and "games" in sched:
                for g in sched["games"]:
                    if g.get("gameType") == 2:  # Regular season
                        official_schedule_games[g["id"]] = g

        total_official_count = len(official_schedule_games)
        print(f"Official NHL Schedule Total Regular Season Games Found: {total_official_count}")

        # Fetch DB games for season
        db_games = Game.query.filter(Game.season == season, Game.game_type == 'R').all()
        db_game_map = {g.game_id: g for g in db_games}

        print(f"Database Current Regular Season Games Found:            {len(db_game_map)}")

        missing_game_ids = sorted(set(official_schedule_games.keys()) - set(db_game_map.keys()))
        missing_count = len(missing_game_ids)

        print(f"Missing Games Count:                                    {missing_count}")
        print("=" * 75)

        missing_details = []
        state_counts = {}

        for gid in missing_game_ids:
            sched_g = official_schedule_games[gid]
            game_date = sched_g.get("gameDate", "N/A")
            home_team = sched_g.get("homeTeam", {}).get("abbrev", "UNK")
            away_team = sched_g.get("awayTeam", {}).get("abbrev", "UNK")
            game_state = sched_g.get("gameState", "UNKNOWN")

            state_counts[game_state] = state_counts.get(game_state, 0) + 1

            missing_details.append({
                "game_id": gid,
                "game_date": game_date,
                "home_team": home_team,
                "away_team": away_team,
                "schedule_game_state": game_state
            })

        print(f"\nMissing Games Schedule State Breakdown:")
        for state, count in sorted(state_counts.items()):
            print(f"  - {state}: {count} games")

        summary = {
            "audited_at": datetime.now(timezone.utc).isoformat(),
            "season": season,
            "official_schedule_regular_season_games": total_official_count,
            "database_regular_season_games": len(db_game_map),
            "missing_games_count": missing_count,
            "schedule_state_breakdown": state_counts,
            "missing_games": missing_details
        }

        # Write reports
        reports_dir = os.path.join(project_root, "reports")
        os.makedirs(reports_dir, exist_ok=True)
        json_path = os.path.join(reports_dir, f"stage4_missing_games_{season}.json")
        md_path = os.path.join(reports_dir, f"stage4_missing_games_{season}.md")

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)

        md_content = f"""# Stage 4: {season[:4]}-{season[6:]} Missing Games Diagnostic Report

**Audited At:** `{summary['audited_at']}`  
**Official Schedule Games:** `{total_official_count}`  
**Database Games:** `{len(db_game_map)}`  
**Missing Games Count:** `{missing_count}`  

## Missing Games Schedule State Breakdown

"""
        for state, count in sorted(state_counts.items()):
            md_content += f"- **State `{state}`:** {count} games\n"

        md_content += f"""
## Missing Games Detailed Listing

| Game ID | Game Date | Home Team | Away Team | Schedule Game State |
|---|---|---|---|---|
"""
        for g in missing_details:
            md_content += f"| `{g['game_id']}` | {g['game_date']} | {g['home_team']} | {g['away_team']} | `{g['schedule_game_state']}` |\n"

        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md_content)

        print(f"\nMissing games reports saved to {json_path} and {md_path}")
        return summary

if __name__ == "__main__":
    identify_missing_games()
