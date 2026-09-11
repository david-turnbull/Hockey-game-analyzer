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
from app.models import db, Game, Event, Shot, Shift

TARGET_SEASONS = ['20212022', '20222023', '20232024', '20242025']
EXPECTED_GAMES_PER_SEASON = 1312  # 32 teams * 82 games / 2
MIN_COMPLETE_SEASONS = 3

def audit_season_data(app=None):
    """
    Performs a strict feature-level completeness and data-provenance audit per season.
    Returns:
        summary (dict): Full audit report containing per-season metrics and hard gate status.
    """
    if app is None:
        try:
            from flask import has_app_context, current_app
            if has_app_context():
                app = current_app._get_current_object()
            else:
                app = create_app('development')
        except Exception:
            app = create_app('development')

    results = {}
    total_complete_seasons = 0
    total_synthetic_games = 0

    with app.app_context():
        db.create_all()

        for season in TARGET_SEASONS:
            games_q = Game.query.filter(Game.season == season, Game.game_type == 'R')
            all_games = games_q.all()
            actual_games_count = len(all_games)

            completed_games = [g for g in all_games if g.nhl_game_state in ['OFF', 'FINAL', 'OVER']]
            completed_count = len(completed_games)

            game_ids = [g.game_id for g in all_games]
            unique_ids_count = len(set(game_ids))
            duplicate_ids_count = actual_games_count - unique_ids_count

            nhl_api_count = sum(1 for g in all_games if getattr(g, 'data_source', None) == 'nhl_api')
            synthetic_count = sum(1 for g in all_games if getattr(g, 'data_source', None) == 'synthetic_test')
            unknown_prov_count = actual_games_count - (nhl_api_count + synthetic_count)
            total_synthetic_games += synthetic_count

            with_start_time = sum(1 for g in all_games if g.start_time_utc is not None)
            start_time_cov = round((with_start_time / actual_games_count * 100.0), 2) if actual_games_count > 0 else 0.0

            first_date = min((g.game_date for g in all_games), default=None)
            last_date = max((g.game_date for g in all_games), default=None)

            if game_ids:
                # Query event & shot & shift metrics
                events_per_game = db.session.query(Event.game_id, func.count(Event.event_id))\
                    .filter(Event.game_id.in_(game_ids)).group_by(Event.game_id).all()
                game_event_map = dict(events_per_game)
                total_events = sum(game_event_map.values())
                games_with_events = len(game_event_map)

                shots_per_game = db.session.query(Shot.game_id, func.count(Shot.shot_id))\
                    .filter(Shot.game_id.in_(game_ids)).group_by(Shot.game_id).all()
                game_shot_map = dict(shots_per_game)
                total_shots = sum(game_shot_map.values())
                games_with_shots = len(game_shot_map)

                unblocked_per_game = db.session.query(Shot.game_id, func.count(Shot.shot_id))\
                    .filter(Shot.game_id.in_(game_ids), Shot.outcome.in_(['Goal', 'Saved', 'Missed']))\
                    .group_by(Shot.game_id).all()
                game_unblocked_map = dict(unblocked_per_game)
                total_unblocked = sum(game_unblocked_map.values())
                games_with_unblocked = len(game_unblocked_map)

                xg_per_game = db.session.query(Shot.game_id, func.count(Shot.shot_id))\
                    .filter(Shot.game_id.in_(game_ids), Shot.xg.isnot(None))\
                    .group_by(Shot.game_id).all()
                game_xg_map = dict(xg_per_game)
                games_with_xg = len(game_xg_map)

                shifts_per_game = db.session.query(Shift.game_id, func.count(Shift.shift_id))\
                    .filter(Shift.game_id.in_(game_ids)).group_by(Shift.game_id).all()
                game_shift_map = dict(shifts_per_game)
                total_shifts = sum(game_shift_map.values())
                games_with_shifts = len(game_shift_map)
            else:
                total_events = 0
                games_with_events = 0
                total_shots = 0
                games_with_shots = 0
                total_unblocked = 0
                games_with_unblocked = 0
                games_with_xg = 0
                total_shifts = 0
                games_with_shifts = 0

            pbp_cov = round((games_with_events / actual_games_count * 100.0), 2) if actual_games_count > 0 else 0.0
            event_cov = round((games_with_events / actual_games_count * 100.0), 2) if actual_games_count > 0 else 0.0
            shot_cov = round((games_with_shots / actual_games_count * 100.0), 2) if actual_games_count > 0 else 0.0
            xg_cov = round((games_with_xg / actual_games_count * 100.0), 2) if actual_games_count > 0 else 0.0
            shift_cov = round((games_with_shifts / actual_games_count * 100.0), 2) if actual_games_count > 0 else 0.0

            # Determine Season Audit Status
            reasons = []
            if synthetic_count > 0:
                reasons.append(f"Contains {synthetic_count} synthetic test games")
            if unknown_prov_count > 0:
                reasons.append(f"Contains {unknown_prov_count} unknown provenance games")
            if duplicate_ids_count > 0:
                reasons.append(f"Contains {duplicate_ids_count} duplicate game IDs")
            if actual_games_count != EXPECTED_GAMES_PER_SEASON:
                reasons.append(f"Game count mismatch ({actual_games_count}/{EXPECTED_GAMES_PER_SEASON})")
            if completed_count != EXPECTED_GAMES_PER_SEASON:
                reasons.append(f"Incomplete games ({completed_count}/{EXPECTED_GAMES_PER_SEASON} completed)")
            if start_time_cov < 99.0:
                reasons.append(f"Low timestamp coverage ({start_time_cov}%)")
            if pbp_cov < 99.0:
                reasons.append(f"Low PBP coverage ({pbp_cov}%)")

            if synthetic_count > 0 or unknown_prov_count > 0 or duplicate_ids_count > 0:
                status = "INVALID"
            elif actual_games_count == EXPECTED_GAMES_PER_SEASON and completed_count == EXPECTED_GAMES_PER_SEASON and start_time_cov >= 99.0 and pbp_cov >= 99.0:
                status = "COMPLETE"
                total_complete_seasons += 1
            elif actual_games_count > 0:
                status = "PARTIAL"
            else:
                status = "INVALID"

            results[season] = {
                "season": season,
                "expected_regular_season_games": EXPECTED_GAMES_PER_SEASON,
                "actual_regular_season_games": actual_games_count,
                "completed_regular_season_games": completed_count,
                "unique_game_ids": unique_ids_count,
                "duplicate_game_ids": duplicate_ids_count,
                "nhl_api_games": nhl_api_count,
                "synthetic_games": synthetic_count,
                "unknown_provenance_games": unknown_prov_count,
                "games_with_start_time_utc": with_start_time,
                "start_time_coverage_pct": start_time_cov,
                "games_with_pbp": games_with_events,
                "pbp_coverage_pct": pbp_cov,
                "total_events": total_events,
                "games_with_events": games_with_events,
                "event_coverage_pct": event_cov,
                "total_shots": total_shots,
                "games_with_shots": games_with_shots,
                "shot_coverage_pct": shot_cov,
                "total_unblocked_attempts": total_unblocked,
                "games_with_unblocked_attempts": games_with_unblocked,
                "games_with_xg": games_with_xg,
                "xg_coverage_pct": xg_cov,
                "total_shifts": total_shifts,
                "games_with_shifts": games_with_shifts,
                "shift_coverage_pct": shift_cov,  # Reported separately
                "first_game_date": first_date.strftime("%Y-%m-%d") if first_date else None,
                "last_game_date": last_date.strftime("%Y-%m-%d") if last_date else None,
                "fatal_ingestion_failures": actual_games_count - games_with_events,
                "optional_data_failures": actual_games_count - games_with_shifts,
                "status": status,
                "status_reasons": reasons
            }

        hard_gate_passed = (total_complete_seasons >= MIN_COMPLETE_SEASONS) and (total_synthetic_games == 0)

        gate_reasons = []
        if total_synthetic_games > 0:
            gate_reasons.append(f"Synthetic data detected ({total_synthetic_games} synthetic games in database)")
        if total_complete_seasons < MIN_COMPLETE_SEASONS:
            gate_reasons.append(f"Insufficient complete real seasons ({total_complete_seasons}/{MIN_COMPLETE_SEASONS} required)")

        summary = {
            "audited_at": datetime.now(timezone.utc).isoformat(),
            "target_seasons": TARGET_SEASONS,
            "min_complete_seasons_required": MIN_COMPLETE_SEASONS,
            "complete_seasons_found": total_complete_seasons,
            "total_synthetic_games": total_synthetic_games,
            "hard_gate_passed": hard_gate_passed,
            "gate_reasons": gate_reasons,
            "production_forecast_data_gate": {
                "pass": hard_gate_passed,
                "reasons": gate_reasons
            },
            "seasons": results
        }

        # Print audit output summary
        print("=" * 70)
        print(" PuckLens v1.4.0 Historical Data Provenance & Coverage Audit")
        print("=" * 70)
        print(f"{'Season':<10} | {'Actual':<6} | {'Real API':<8} | {'Synth':<6} | {'UTC %':<7} | {'PBP %':<7} | {'Shift %':<7} | {'Status':<10}")
        print("-" * 70)
        for season, d in results.items():
            print(f"{season:<10} | {d['actual_regular_season_games']:<6} | {d['nhl_api_games']:<8} | {d['synthetic_games']:<6} | {d['start_time_coverage_pct']:<7.1f} | {d['pbp_coverage_pct']:<7.1f} | {d['shift_coverage_pct']:<7.1f} | {d['status']:<10}")
        print("=" * 70)
        print(f"Complete Real Seasons Found: {total_complete_seasons} / {MIN_COMPLETE_SEASONS} Required")
        print(f"Synthetic Games in DB:       {total_synthetic_games}")
        if hard_gate_passed:
            print("PRODUCTION FORECAST DATA GATE: PASSED")
        else:
            print("PRODUCTION FORECAST TRAINING BLOCKED")
            for r in gate_reasons:
                print(f"  - {r}")
        print("=" * 70)

        # Write JSON and Markdown reports
        reports_dir = os.path.join(project_root, "reports")
        os.makedirs(reports_dir, exist_ok=True)
        json_path = os.path.join(reports_dir, "historical_data_coverage.json")
        md_path = os.path.join(reports_dir, "historical_data_coverage.md")

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)

        status_text = "PASSED" if hard_gate_passed else "FAILED (PRODUCTION FORECAST TRAINING BLOCKED)"
        md_content = f"""# Historical Data Provenance & Coverage Audit Report

**Audited At:** `{summary['audited_at']}`  
**Production Gate Status:** `{status_text}`  
**Complete Real Seasons:** {total_complete_seasons}/{MIN_COMPLETE_SEASONS}  
**Synthetic Games Detected:** {total_synthetic_games}  

## Season Breakdown

| Season | Expected | Actual | Real NHL API | Synthetic | Start Time UTC % | PBP % | xG % | Shift % (Optional) | Status |
|---|---|---|---|---|---|---|---|---|---|
"""
        for season, d in results.items():
            st_icon = "✅ COMPLETE" if d['status'] == 'COMPLETE' else ("⚠️ PARTIAL" if d['status'] == 'PARTIAL' else "❌ INVALID")
            md_content += f"| {season} | {d['expected_regular_season_games']} | {d['actual_regular_season_games']} | {d['nhl_api_games']} | {d['synthetic_games']} | {d['start_time_coverage_pct']:.1f}% | {d['pbp_coverage_pct']:.1f}% | {d['xg_coverage_pct']:.1f}% | {d['shift_coverage_pct']:.1f}% | {st_icon} |\n"

        if not hard_gate_passed:
            md_content += f"\n> [!CAUTION]\n> **PRODUCTION FORECAST TRAINING BLOCKED**\n> Reasons:\n"
            for r in gate_reasons:
                md_content += f"> - {r}\n"
        else:
            md_content += f"\n> [!NOTE]\n> Production data gate passed. All target seasons contain genuine NHL API data with no synthetic contamination.\n"

        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md_content)

        print(f"Audit reports saved to {json_path} and {md_path}")
        return summary

def audit_seasons():
    return audit_season_data()

if __name__ == "__main__":
    audit_seasons()
