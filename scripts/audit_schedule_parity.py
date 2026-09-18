import os
import sys
import json
from datetime import datetime, timezone
from typing import Dict, Any, List, Tuple, Set

# Ensure project root in sys.path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.append(project_root)

from app import create_app
from app.models import db, Game, Team
from data_pipeline.orchestrator import PipelineOrchestrator

TARGET_SEASONS = ['20212022', '20222023', '20232024', '20242025', '20252026']
EXPECTED_GAMES_PER_SEASON = 1312
EXPECTED_GAMES_PER_TEAM = 82

# Alias mapping helper for franchise relocations / abbreviations
TEAM_ALIAS = {
    'ARI': 'UTA',
    'UTA': 'ARI'
}

def get_season_teams(season: str) -> List[str]:
    """Returns 32 active NHL team abbreviations for given season."""
    if int(season[:4]) >= 2024:
        return [
            'ANA', 'BOS', 'BUF', 'CAR', 'CBJ', 'CGY', 'CHI', 'COL',
            'DAL', 'DET', 'EDM', 'FLA', 'LAK', 'MIN', 'MTL', 'NJD',
            'NSH', 'NYI', 'NYR', 'OTT', 'PHI', 'PIT', 'SEA', 'SJS',
            'STL', 'TBL', 'TOR', 'UTA', 'VAN', 'VGK', 'WPG', 'WSH'
        ]
    else:
        return [
            'ANA', 'ARI', 'BOS', 'BUF', 'CAR', 'CBJ', 'CGY', 'CHI',
            'COL', 'DAL', 'DET', 'EDM', 'FLA', 'LAK', 'MIN', 'MTL',
            'NJD', 'NSH', 'NYI', 'NYR', 'OTT', 'PHI', 'PIT', 'SEA',
            'SJS', 'STL', 'TBL', 'TOR', 'VAN', 'VGK', 'WPG', 'WSH'
        ]

def audit_schedule_parity(app=None, save_report: bool = True, force_refresh_schedule: bool = False) -> Tuple[bool, Dict[str, Any]]:
    """
    Performs schedule parity auditing across target seasons (2021-22 to 2025-26).
    Compares official NHL regular-season schedule against database Game records.
    Verifies:
      - Exactly 1,312 official unique games per season.
      - Exactly 1,312 database unique games per season.
      - 0 missing games (official_ids - db_ids == empty).
      - 0 unexpected games (db_ids - official_ids == empty).
      - 0 duplicate game IDs in DB.
      - Exact match for home team, away team, and game date.
      - 100% NHL API provenance (data_source == 'nhl_api').
      - Per-team completeness: exactly 82 games per team (32 teams).
    """
    if app is None:
        try:
            from flask import has_app_context, current_app
            if has_app_context():
                app = current_app._get_current_object()
                # If app was passed implicitly from context, check if we should save report
            else:
                app = create_app('development')
        except Exception:
            app = create_app('development')

    orchestrator = PipelineOrchestrator()

    season_results = {}
    overall_passed = True
    all_gate_reasons = []

    with app.app_context():
        # Build Team ID -> Abbreviation map from DB
        teams_in_db = Team.query.all()
        team_id_map = {t.team_id: t.abbreviation for t in teams_in_db}

        for season in TARGET_SEASONS:
            teams = get_season_teams(season)
            official_schedule_games = {}
            team_official_game_ids = {t: set() for t in teams}

            for team in teams:
                sched = orchestrator.api_client.get_season_schedule(team, season, force_refresh=force_refresh_schedule)
                if sched and "games" in sched:
                    for g in sched["games"]:
                        if g.get("gameType") == 2:  # Regular season
                            gid = g["id"]
                            official_schedule_games[gid] = g
                            home_abbr = g.get("homeTeam", {}).get("abbrev")
                            away_abbr = g.get("awayTeam", {}).get("abbrev")
                            if home_abbr in team_official_game_ids:
                                team_official_game_ids[home_abbr].add(gid)
                            if away_abbr in team_official_game_ids:
                                team_official_game_ids[away_abbr].add(gid)

            official_count = len(official_schedule_games)
            official_ids = set(official_schedule_games.keys())

            # Fetch DB games for season
            db_games = Game.query.filter(Game.season == season, Game.game_type == 'R').all()
            db_game_ids_list = [g.game_id for g in db_games]
            db_ids = set(db_game_ids_list)
            db_count = len(db_games)
            duplicate_db_ids = db_count - len(db_ids)

            missing_ids = sorted(official_ids - db_ids)
            unexpected_ids = sorted(db_ids - official_ids)

            # Metadata & provenance mismatches
            date_mismatches = []
            home_team_mismatches = []
            away_team_mismatches = []
            non_nhl_api_games = []

            # Per-team DB game counts
            team_db_game_ids = {t: set() for t in teams}

            for g in db_games:
                if getattr(g, 'data_source', None) != 'nhl_api':
                    non_nhl_api_games.append(g.game_id)

                home_abbr = team_id_map.get(g.home_team_id, "UNK")
                away_abbr = team_id_map.get(g.away_team_id, "UNK")

                if home_abbr in team_db_game_ids:
                    team_db_game_ids[home_abbr].add(g.game_id)
                elif TEAM_ALIAS.get(home_abbr) in team_db_game_ids:
                    team_db_game_ids[TEAM_ALIAS[home_abbr]].add(g.game_id)

                if away_abbr in team_db_game_ids:
                    team_db_game_ids[away_abbr].add(g.game_id)
                elif TEAM_ALIAS.get(away_abbr) in team_db_game_ids:
                    team_db_game_ids[TEAM_ALIAS[away_abbr]].add(g.game_id)

                # Match against official schedule if present
                if g.game_id in official_schedule_games:
                    sched_g = official_schedule_games[g.game_id]
                    sched_date = sched_g.get("gameDate")
                    db_date = g.game_date.strftime("%Y-%m-%d") if hasattr(g.game_date, "strftime") else str(g.game_date)
                    if sched_date and db_date != sched_date:
                        date_mismatches.append({"game_id": g.game_id, "db_date": db_date, "official_date": sched_date})

                    sched_home = sched_g.get("homeTeam", {}).get("abbrev")
                    if sched_home and home_abbr != sched_home and TEAM_ALIAS.get(home_abbr) != sched_home:
                        home_team_mismatches.append({"game_id": g.game_id, "db_home": home_abbr, "official_home": sched_home})

                    sched_away = sched_g.get("awayTeam", {}).get("abbrev")
                    if sched_away and away_abbr != sched_away and TEAM_ALIAS.get(away_abbr) != sched_away:
                        away_team_mismatches.append({"game_id": g.game_id, "db_away": away_abbr, "official_away": sched_away})

            # Per-team completeness calculation
            team_breakdown = {}
            incomplete_teams = []

            for team in teams:
                off_team_cnt = len(team_official_game_ids[team])
                db_team_cnt = len(team_db_game_ids[team])
                team_missing_cnt = len(team_official_game_ids[team] - team_db_game_ids[team])

                team_breakdown[team] = {
                    "official_games": off_team_cnt,
                    "database_games": db_team_cnt,
                    "missing_games": team_missing_cnt,
                    "complete": (off_team_cnt == EXPECTED_GAMES_PER_TEAM and db_team_cnt == EXPECTED_GAMES_PER_TEAM and team_missing_cnt == 0)
                }

                if off_team_cnt != EXPECTED_GAMES_PER_TEAM or db_team_cnt != EXPECTED_GAMES_PER_TEAM or team_missing_cnt != 0:
                    incomplete_teams.append(team)

            # Gate evaluations for this season
            season_reasons = []
            if official_count != EXPECTED_GAMES_PER_SEASON:
                season_reasons.append(f"Official schedule game count mismatch ({official_count}/{EXPECTED_GAMES_PER_SEASON})")
            if db_count != EXPECTED_GAMES_PER_SEASON:
                season_reasons.append(f"Database game count mismatch ({db_count}/{EXPECTED_GAMES_PER_SEASON})")
            if len(missing_ids) > 0:
                season_reasons.append(f"{len(missing_ids)} missing game IDs")
            if len(unexpected_ids) > 0:
                season_reasons.append(f"{len(unexpected_ids)} unexpected DB game IDs")
            if duplicate_db_ids > 0:
                season_reasons.append(f"{duplicate_db_ids} duplicate DB game IDs")
            if len(non_nhl_api_games) > 0:
                season_reasons.append(f"{len(non_nhl_api_games)} non-NHL-API provenance games")
            if len(date_mismatches) > 0:
                season_reasons.append(f"{len(date_mismatches)} game date mismatches")
            if len(home_team_mismatches) > 0:
                season_reasons.append(f"{len(home_team_mismatches)} home team mismatches")
            if len(away_team_mismatches) > 0:
                season_reasons.append(f"{len(away_team_mismatches)} away team mismatches")
            if len(incomplete_teams) > 0:
                season_reasons.append(f"{len(incomplete_teams)} teams with incomplete 82-game schedules: {', '.join(incomplete_teams)}")

            season_passed = (len(season_reasons) == 0)
            if not season_passed:
                overall_passed = False
                all_gate_reasons.append(f"Season {season}: " + "; ".join(season_reasons))

            season_results[season] = {
                "season": season,
                "official_schedule_games": official_count,
                "database_games": db_count,
                "missing_games_count": len(missing_ids),
                "unexpected_games_count": len(unexpected_ids),
                "duplicate_db_games_count": duplicate_db_ids,
                "non_nhl_api_games_count": len(non_nhl_api_games),
                "date_mismatches_count": len(date_mismatches),
                "home_team_mismatches_count": len(home_team_mismatches),
                "away_team_mismatches_count": len(away_team_mismatches),
                "incomplete_teams_count": len(incomplete_teams),
                "status": "PASSED" if season_passed else "FAILED",
                "gate_reasons": season_reasons,
                "team_breakdown": team_breakdown,
                "missing_game_ids": missing_ids,
                "unexpected_game_ids": unexpected_ids
            }

    summary = {
        "audited_at": datetime.now(timezone.utc).isoformat(),
        "target_seasons": TARGET_SEASONS,
        "schedule_parity_gate_passed": overall_passed,
        "gate_reasons": all_gate_reasons,
        "seasons": season_results
    }

    # Console Report
    print("=" * 78)
    print(" PuckLens v1.4.0 Schedule Parity & Per-Team Completeness Audit")
    print("=" * 78)
    print(f"{'Season':<10} | {'Official':<8} | {'Database':<8} | {'Missing':<7} | {'Extra':<6} | {'Team OK':<8} | {'Status':<8}")
    print("-" * 78)
    for season, s in season_results.items():
        teams_ok = "32/32" if s['incomplete_teams_count'] == 0 else f"{32 - s['incomplete_teams_count']}/32"
        print(f"{season:<10} | {s['official_schedule_games']:<8} | {s['database_games']:<8} | {s['missing_games_count']:<7} | {s['unexpected_games_count']:<6} | {teams_ok:<8} | {s['status']:<8}")
    print("=" * 78)
    if overall_passed:
        print(" SCHEDULE PARITY GATE: PASSED (1,312 Official / 1,312 DB across all 5 seasons)")
    else:
        print(" SCHEDULE PARITY GATE: FAILED")
        for r in all_gate_reasons:
            print(f"  - {r}")
    print("=" * 78)

    # Save reports if save_report is True
    if save_report:
        reports_dir = os.path.join(project_root, "reports")
        os.makedirs(reports_dir, exist_ok=True)
        json_path = os.path.join(reports_dir, "schedule_parity.json")
        md_path = os.path.join(reports_dir, "schedule_parity.md")

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)

        md_status = "PASSED" if overall_passed else "FAILED"
        md_content = f"""# Schedule Parity & Per-Team Completeness Audit Report

**Audited At:** `{summary['audited_at']}`  
**Schedule Parity Gate Status:** `{md_status}`  

## Season Summary

| Season | Official Schedule Games | Database Games | Missing Games | Unexpected Games | Duplicate Game IDs | Per-Team Completeness (82 games) | Status |
|---|---|---|---|---|---|---|---|
"""
        for season, s in season_results.items():
            st_icon = "✅ PASSED" if s['status'] == 'PASSED' else "❌ FAILED"
            teams_ok = "32/32 Teams (100%)" if s['incomplete_teams_count'] == 0 else f"{32 - s['incomplete_teams_count']}/32 Teams"
            md_content += f"| {season} | {s['official_schedule_games']} | {s['database_games']} | {s['missing_games_count']} | {s['unexpected_games_count']} | {s['duplicate_db_games_count']} | {teams_ok} | {st_icon} |\n"

        if not overall_passed:
            md_content += f"\n> [!CAUTION]\n> **SCHEDULE PARITY AUDIT FAILED**\n> Reasons:\n"
            for r in all_gate_reasons:
                md_content += f"> - {r}\n"
        else:
            md_content += f"\n> [!NOTE]\n> Schedule parity gate passed. All 5 seasons contain exactly 1,312 genuine NHL API regular-season games matching official schedules, with 0 missing games and 82 games for all 32 teams.\n"

        md_content += f"\n## Per-Team Completeness Breakdown (2025-26 Season)\n\n"
        md_content += f"| Team | Official Games | Database Games | Missing Games | Completeness Status |\n"
        md_content += f"|---|---|---|---|---|\n"
        t_2025 = season_results['20252026']['team_breakdown']
        for team, tb in sorted(t_2025.items()):
            c_icon = "✅ 82/82 Complete" if tb['complete'] else f"❌ {tb['database_games']}/82 Incomplete"
            md_content += f"| `{team}` | {tb['official_games']} | {tb['database_games']} | {tb['missing_games']} | {c_icon} |\n"

        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md_content)

        print(f"Schedule parity reports saved to {json_path} and {md_path}")

    return overall_passed, summary

if __name__ == "__main__":
    audit_schedule_parity(save_report=True)
