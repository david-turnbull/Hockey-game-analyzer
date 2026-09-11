import os
import sys
import json
from datetime import datetime, timezone

# Ensure project root in sys.path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.append(project_root)

from app import create_app
from app.analytics.forecasting.backtest_engine import BacktestEngine

def run():
    app = create_app('development')
    with app.app_context():
        engine = BacktestEngine()
        results = engine.run_full_backtest()

        # Output Summary to stdout
        print("\n" + "=" * 70)
        print(" PuckLens v1.4.0 Historical Out-of-Time Backtest Results")
        print("=" * 70)
        print(f" Protocol Split Configuration:")
        print(f"   Train:      2021-22  (Model candidate fitting)")
        print(f"   Select:     2022-23  (Model selection criterion)")
        print(f"   Refit:      2021-22 + 2022-23 (Combined training)")
        print(f"   Calibrate:  2023-24  (Isotonic Regression fitting)")
        print(f"   Test:       2024-25  (100% Untouched Holdout)")
        print("=" * 70)
        print(f" Selected Model: {results['model_selection']['selected_model']}")
        print(f" Selection Log Loss (2022-23): Logistic={results['model_selection']['logistic_regression_log_loss']:.4f}, HGB={results['model_selection']['hgb_log_loss']:.4f}")
        print("-" * 70)

        print(f"{'Split / Metric':<20} | {'Log Loss':<10} | {'Brier':<8} | {'Accuracy':<10} | {'ECE':<8}")
        print("-" * 70)

        # 2024-25 Test Holdout
        test_m = results["test_season_20242025_eval"]["calibrated_model"]
        elo_m = results["test_season_20242025_eval"]["elo_baseline"]
        print(f"{'2024-25 Test (Model)':<20} | {test_m['log_loss']:<10.4f} | {test_m['brier_score']:<8.4f} | {test_m['accuracy']:<9.2f}% | {test_m['ece']:<8.4f}")
        print(f"{'2024-25 Test (Elo)':<20} | {elo_m['log_loss']:<10.4f} | {elo_m['brier_score']:<8.4f} | {elo_m['accuracy']:<9.2f}% | {elo_m['ece']:<8.4f}")
        print(f"{'2024-25 Naive 50/50':<20} | {0.6931:<10.4f} | {0.2500:<8.4f} | {50.00:<9.2f}% | {0.0000:<8.4f}")
        print("-" * 70)

        # Save JSON & Markdown reports
        reports_dir = os.path.join(project_root, "reports")
        os.makedirs(reports_dir, exist_ok=True)
        json_path = os.path.join(reports_dir, "backtest_results_v1.4.0.json")
        md_path = os.path.join(reports_dir, "backtest_results_v1.4.0.md")

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)

        md_content = f"""# PuckLens v1.4.0 Historical Out-of-Time Backtest Report

**Run Timestamp:** {results['backtest_run_at']}  
**Selected Model Architecture:** `{results['model_selection']['selected_model']}`

## Protocol & Temporal Splits

- **Train Split (2021-22):** Model candidate parameter fitting
- **Model Selection Split (2022-23):** Candidate selection via Log Loss (`LogisticRegression` vs `HistGradientBoosting`)
- **Combined Refit (2021-22 + 2022-23):** Winner refitted on combined historical data
- **Calibration Split (2023-24):** Isotonic Regression calibrator fit on 2023-24 validation predictions
- **Final Out-of-Time Test (2024-25):** 100% untouched holdout evaluation

## Out-of-Time Performance Comparison (2024-25 Test Holdout)

| Model / Baseline | Log Loss | Brier Score | Accuracy (%) | ECE |
|---|---|---|---|---|
| **PuckLens v1.4.0 (Calibrated Model)** | **{test_m['log_loss']:.4f}** | **{test_m['brier_score']:.4f}** | **{test_m['accuracy']:.2f}%** | **{test_m['ece']:.4f}** |
| Elo Baseline Model | {elo_m['log_loss']:.4f} | {elo_m['brier_score']:.4f} | {elo_m['accuracy']:.2f}% | {elo_m['ece']:.4f} |
| Naive 50/50 Baseline | 0.6931 | 0.2500 | 50.00% | 0.0000 |

## Score Projection Model Evaluation (2024-25)

- **Total Goals MAE:** {results['test_season_20242025_eval']['score_projection']['total_goals_mae']} goals
- **Top 5 Exact Scoreline Coverage:** {results['test_season_20242025_eval']['score_projection']['top5_scoreline_coverage_pct']}% of games

> [!NOTE]
> All pregame features enforce the strict temporal invariant (`start_time_utc < target_game.start_time_utc`), guaranteeing zero future leakage.
"""
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md_content)

        print(f"\nReports saved to {json_path} and {md_path}")
        return results

if __name__ == "__main__":
    run()
