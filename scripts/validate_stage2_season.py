import os
import sys
import json
import argparse
import time
from typing import Dict, Any, List
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath("."))

from app import create_app
from app.services.player_season_service import PlayerSeasonService
from app.services.player_game_analytics_audit import PlayerGameAnalyticsAuditService
from scripts.backfill_player_game_analytics import run_backfill

def run_season_validation(season: str = "20212022") -> int:
    app = create_app()
    with app.app_context():
        print(f"==================================================")
        print(f" STAGE 2 PRODUCTION VALIDATION RUNNER: {season}")
        print(f"==================================================")

        # 1. Backfill and Audit
        print("\n[Step 1] Verifying Backfill & Audit Completeness...")
        backfill_summary = run_backfill(season=season, force=False)
        
        audit_res = PlayerGameAnalyticsAuditService.audit_game_analytics(season=season)
        complete_games = len(audit_res["complete"])
        incomplete_games = len(audit_res["incomplete"])
        missing_games = len(audit_res["missing"])
        total_games = complete_games + incomplete_games + missing_games

        print(f"Total Season Games:    {total_games}")
        print(f"  Complete Games:      {complete_games}")
        print(f"  Incomplete Games:    {incomplete_games}")
        print(f"  Missing Games:       {missing_games}")

        has_audit_error = (incomplete_games > 0 or missing_games > 0 or complete_games == 0)
        if has_audit_error:
            print(f"ERROR: Season {season} is not 100% complete!")

        # 2. Benchmark Explicit Legacy Method
        print("\n[Step 2] Executing Explicit Legacy Method...")
        t0 = time.time()
        legacy_skaters = PlayerSeasonService._get_season_skaters_summary_legacy(season=season, include_on_ice_5v5=True)
        t_legacy = time.time() - t0
        print(f"Legacy Execution Time: {t_legacy:.3f} seconds ({len(legacy_skaters)} skaters loaded)")

        # 3. Benchmark Explicit Derived Method
        print("\n[Step 3] Executing Explicit Derived SQL Method...")
        t1 = time.time()
        derived_skaters = PlayerSeasonService._get_season_skaters_summary_derived(season=season, include_on_ice_5v5=True)
        t_derived = time.time() - t1
        print(f"Derived Execution Time: {t_derived:.4f} seconds ({len(derived_skaters)} skaters loaded)")

        speedup = t_legacy / t_derived if t_derived > 0 else 0.0
        print(f"\n>>> SPEEDUP FACTOR: {speedup:.1f}x faster ({t_legacy:.2f}s vs {t_derived:.4f}s)")

        # 4. 1-to-1 Player Equivalence Check
        print("\n[Step 4] Performing 1-to-1 Player Equivalence Comparison...")
        legacy_map = {s["player_id"]: s for s in legacy_skaters}
        derived_map = {s["player_id"]: s for s in derived_skaters}

        all_pids = set(legacy_map.keys()) | set(derived_map.keys())
        mismatches = []

        metrics_to_check = [
            ("gp", 0),
            ("goals", 0),
            ("assists", 0),
            ("points", 0),
            ("shots", 0),
            ("unblocked_attempts", 0),
            ("xg", 0.01),
            ("toi_seconds", 0),
            ("toi_5v5_seconds", 0),
            ("cf", 0),
            ("ca", 0),
            ("ff", 0),
            ("fa", 0),
            ("on_ice_xgf", 0.01),
            ("on_ice_xga", 0.01)
        ]

        for pid in sorted(all_pids):
            leg = legacy_map.get(pid)
            der = derived_map.get(pid)

            if not leg:
                mismatches.append({"player_id": pid, "error": "Present in derived layer but missing in legacy"})
                continue
            if not der:
                mismatches.append({"player_id": pid, "name": leg.get("name"), "error": "Present in legacy layer but missing in derived"})
                continue

            name = leg.get("name", f"ID {pid}")
            leg_oi = leg.get("on_ice_5v5", {})
            der_oi = der.get("on_ice_5v5", {})

            leg_vals = {
                "gp": leg.get("gp", 0),
                "goals": leg.get("goals", 0),
                "assists": leg.get("assists", 0),
                "points": leg.get("points", 0),
                "shots": leg.get("shots", 0),
                "unblocked_attempts": leg.get("unblocked_attempts", 0),
                "xg": round(float(leg.get("xg", 0.0)), 4),
                "toi_seconds": leg.get("toi_seconds", 0),
                "toi_5v5_seconds": leg_oi.get("toi_seconds", 0),
                "cf": leg_oi.get("cf", 0),
                "ca": leg_oi.get("ca", 0),
                "ff": leg_oi.get("ff", 0),
                "fa": leg_oi.get("fa", 0),
                "on_ice_xgf": round(float(leg_oi.get("on_ice_xgf", 0.0)), 4),
                "on_ice_xga": round(float(leg_oi.get("on_ice_xga", 0.0)), 4),
            }

            der_vals = {
                "gp": der.get("gp", 0),
                "goals": der.get("goals", 0),
                "assists": der.get("assists", 0),
                "points": der.get("points", 0),
                "shots": der.get("shots", 0),
                "unblocked_attempts": der.get("unblocked_attempts", 0),
                "xg": round(float(der.get("xg", 0.0)), 4),
                "toi_seconds": der.get("toi_seconds", 0),
                "toi_5v5_seconds": der_oi.get("toi_seconds", 0),
                "cf": der_oi.get("cf", 0),
                "ca": der_oi.get("ca", 0),
                "ff": der_oi.get("ff", 0),
                "fa": der_oi.get("fa", 0),
                "on_ice_xgf": round(float(der_oi.get("on_ice_xgf", 0.0)), 4),
                "on_ice_xga": round(float(der_oi.get("on_ice_xga", 0.0)), 4),
            }

            player_diffs = {}
            for metric_key, tolerance in metrics_to_check:
                v_leg = leg_vals[metric_key]
                v_der = der_vals[metric_key]
                if tolerance > 0:
                    if round(abs(v_leg - v_der), 4) > tolerance:
                        player_diffs[metric_key] = {"legacy": v_leg, "derived": v_der}
                else:
                    if v_leg != v_der:
                        player_diffs[metric_key] = {"legacy": v_leg, "derived": v_der}

            if player_diffs:
                mismatches.append({
                    "player_id": pid,
                    "name": name,
                    "differentials": player_diffs
                })

        print(f"\nTotal Players Evaluated: {len(all_pids)}")
        print(f"Total Mismatches Found:  {len(mismatches)}")

        # 5. Output Reports
        report_dir = os.path.join("reports", "v1.5")
        os.makedirs(report_dir, exist_ok=True)

        json_path = os.path.join(report_dir, f"stage2_validation_{season}.json")
        md_path = os.path.join(report_dir, f"stage2_validation_{season}.md")

        report_data = {
            "season": season,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "audit": {
                "total_games": total_games,
                "complete_games": complete_games,
                "incomplete_games": incomplete_games,
                "missing_games": missing_games,
                "is_100_percent_complete": not has_audit_error
            },
            "benchmark": {
                "legacy_seconds": round(t_legacy, 4),
                "derived_seconds": round(t_derived, 4),
                "speedup_factor": round(speedup, 1),
                "legacy_skaters_count": len(legacy_skaters),
                "derived_skaters_count": len(derived_skaters)
            },
            "equivalence": {
                "total_players_evaluated": len(all_pids),
                "mismatch_count": len(mismatches),
                "is_perfect_equivalence": len(mismatches) == 0,
                "mismatches": mismatches
            }
        }

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(report_data, f, indent=2)

        md_content = f"""# Stage 2 Validation Report: Season {season}

> **Generated:** `{report_data['timestamp_utc']}`  
> **Status:** `{'PASSED' if (not has_audit_error and len(mismatches) == 0) else 'FAILED'}`

## 1. Audit & Backfill Completeness
* **Total Season Games:** `{total_games}`
* **Complete Games:** `{complete_games}`
* **Incomplete Games:** `{incomplete_games}`
* **Missing Games:** `{missing_games}`
* **Audit Result:** `{'100% COMPLETE' if not has_audit_error else 'INCOMPLETE'}`

## 2. Performance Benchmark
| Engine | Execution Time | Skaters Loaded | Speedup |
| :--- | :--- | :--- | :--- |
| **Legacy `_get_season_skaters_summary_legacy`** | `{t_legacy:.3f} s` | `{len(legacy_skaters)}` | Baseline (1.0x) |
| **Derived `_get_season_skaters_summary_derived`** | `{t_derived:.4f} s` | `{len(derived_skaters)}` | **{speedup:.1f}x Faster** |

## 3. Player Equivalence Summary
* **Total Players Evaluated:** `{len(all_pids)}`
* **Mismatches Found:** `{len(mismatches)}`
* **Equivalence Result:** `{'PERFECT 100% MATCH' if len(mismatches) == 0 else 'MISMATCHES DETECTED'}`

### Verified Metrics
- Games Played (`gp`), Goals (`goals`), Assists (`assists`), Points (`points`)
- Shots on Goal (`shots`), Unblocked Attempts (`unblocked_attempts`)
- Individual Expected Goals (`xg`)
- Total Time on Ice (`toi_seconds`), 5v5 Time on Ice (`toi_5v5_seconds`)
- 5v5 Corsi For / Against (`cf`, `ca`), 5v5 Fenwick For / Against (`ff`, `fa`)
- 5v5 Expected Goals For / Against (`on_ice_xgf`, `on_ice_xga`)
"""
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md_content)

        print(f"\nWrote validation reports:")
        print(f"  - JSON: {json_path}")
        print(f"  - MD:   {md_path}")

        if has_audit_error or len(mismatches) > 0:
            print(f"\n[FAILURE] Validation check failed for season {season}.")
            return 1

        print(f"\n[SUCCESS] Phase 2 Validation passed cleanly for season {season}!")
        return 0

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PuckLens Stage 2 Production Season Validation Runner")
    parser.add_argument("--season", type=str, default="20212022", help="Target season (default: 20212022)")
    args = parser.parse_args()

    exit_code = run_season_validation(season=args.season)
    sys.exit(exit_code)
