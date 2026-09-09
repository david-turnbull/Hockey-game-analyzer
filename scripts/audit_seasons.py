import os
import sys
import json
from datetime import datetime, timezone
from sqlalchemy import func

# Ensure project root in sys.path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.append(project_root)

from app import create_app
from app.models import db, Game, Event, Shift

TARGET_SEASONS = ['20212022', '20222023', '20232024', '20242025']
MIN_GAMES_PER_SEASON = 1200
MIN_COMPLETE_SEASONS = 3

def audit_seasons():
    app = create_app('development')
    results = {}
    total_complete_seasons = 0

    with app.app_context():
        # Ensure database tables exist (including new columns/tables)
        db.create_all()

        for season in TARGET_SEASONS:
            games_q = Game.query.filter(Game.season == season, Game.game_type == 'R')
            total_games = games_q.count()

            completed_games = games_q.filter(Game.nhl_game_state.in_(['OFF', 'FINAL', 'OVER'])).count()
            with_start_time = games_q.filter(Game.start_time_utc.isnot(None)).count()

            # Event and shift counts for this season
            game_ids = [g.game_id for g in games_q.all()]
            if game_ids:
                event_count = db.session.query(func.count(Event.event_id)).filter(Event.game_id.in_(game_ids)).scalar() or 0
                shift_count = db.session.query(func.count(Shift.shift_id)).filter(Shift.game_id.in_(game_ids)).scalar() or 0
            else:
                event_count = 0
                shift_count = 0

            is_complete = completed_games >= MIN_GAMES_PER_SEASON and event_count > 0
            if is_complete:
                total_complete_seasons += 1

            results[season] = {
                "total_games": total_games,
                "completed_games": completed_games,
                "with_start_time_utc": with_start_time,
                "events_count": event_count,
                "shifts_count": shift_count,
                "is_complete_season": is_complete
            }

        hard_gate_passed = total_complete_seasons >= MIN_COMPLETE_SEASONS

        summary = {
            "audited_at": datetime.now(timezone.utc).isoformat(),
            "target_seasons": TARGET_SEASONS,
            "min_complete_seasons_required": MIN_COMPLETE_SEASONS,
            "complete_seasons_found": total_complete_seasons,
            "hard_gate_passed": hard_gate_passed,
            "seasons": results
        }

        # Print report summary
        print("=" * 60)
        print(" PuckLens v1.4.0 Historical Data Coverage Audit")
        print("=" * 60)
        print(f"{'Season':<12} | {'Total':<7} | {'Completed':<9} | {'With UTC':<9} | {'Events':<10} | {'Status':<10}")
        print("-" * 60)
        for season, d in results.items():
            status_str = "COMPLETE" if d["is_complete_season"] else "INCOMPLETE"
            print(f"{season:<12} | {d['total_games']:<7} | {d['completed_games']:<9} | {d['with_start_time_utc']:<9} | {d['events_count']:<10} | {status_str:<10}")
        print("=" * 60)
        print(f"Complete Seasons Found: {total_complete_seasons} / {MIN_COMPLETE_SEASONS} Required")
        print(f"Production Gate Status: {'PASSED' if hard_gate_passed else 'FAILED (Hard Gate Blocked)'}")
        print("=" * 60)

        # Write reports
        os.makedirs(os.path.join(project_root, "reports"), exist_ok=True)
        json_path = os.path.join(project_root, "reports", "historical_data_coverage.json")
        md_path = os.path.join(project_root, "reports", "historical_data_coverage.md")

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)

        md_content = f"""# Historical Data Coverage Audit Report

**Audited At:** {summary['audited_at']}  
**Production Gate Status:** `{'PASSED' if hard_gate_passed else 'FAILED'}` ({total_complete_seasons}/{MIN_COMPLETE_SEASONS} complete regular seasons available)

## Season Breakdown

| Season | Total Games | Completed Games | Games with `start_time_utc` | Total Events | Status |
|---|---|---|---|---|---|
"""
        for season, d in results.items():
            status_str = "✅ Complete" if d["is_complete_season"] else "❌ Incomplete"
            md_content += f"| {season} | {d['total_games']} | {d['completed_games']} | {d['with_start_time_utc']} | {d['events_count']} | {status_str} |\n"

        md_content += f"\n> [!NOTE]\n> Production forecast model training and official backtesting require at least 3 complete NHL regular seasons (>= {MIN_GAMES_PER_SEASON} games each with play-by-play events).\n"

        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md_content)

        print(f"Reports saved to {json_path} and {md_path}")
        return summary

if __name__ == "__main__":
    audit_seasons()
