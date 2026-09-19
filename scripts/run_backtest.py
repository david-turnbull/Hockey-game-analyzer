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
        results = engine.evaluate_active_registry_model('20242025')

        # Output Summary to stdout
        print("\n" + "=" * 75)
        print(" PuckLens v1.4.0 Authoritative Artifact-Bound Holdout Evaluation (2024-25)")
        print("=" * 75)
        print(f" Evaluation Timestamp: {results['evaluated_at']}")
        print(f" Run UUID:             {results['run_uuid']}")
        print(f" Git Commit SHA:       {results['git_commit_sha']}")
        print(f" Model Version:        {results['model_version']}")
        print(f" Model Artifact SHA:   {results['artifact_sha256']}")
        print(f" Feature Schema Ver:   {results['feature_schema_version']}")
        print("=" * 75)
        print(f" Protocol Split Configuration:")
        print(f"   Train:      2021-22  (Model candidate fitting)")
        print(f"   Select:     2022-23  (Model selection criterion)")
        print(f"   Refit:      2021-22 + 2022-23 (Combined training)")
        print(f"   Calibrate:  2023-24  (Isotonic Regression fitting)")
        print(f"   Holdout:    2024-25  (100% Untouched Test Split)")
        print("=" * 75)
        print(f"{'Split / Metric':<20} | {'Log Loss':<10} | {'Brier':<8} | {'Accuracy':<10} | {'ECE':<8}")
        print("-" * 75)

        # 2024-25 Test Holdout
        test_m = results["test_season_20242025_eval"]["calibrated_model"]
        elo_m = results["test_season_20242025_eval"]["elo_baseline"]
        print(f"{'2024-25 Test (Model)':<20} | {test_m['log_loss']:<10.4f} | {test_m['brier_score']:<8.4f} | {test_m['accuracy']:<9.2f}% | {test_m['ece']:<8.4f}")
        print(f"{'2024-25 Test (Elo)':<20} | {elo_m['log_loss']:<10.4f} | {elo_m['brier_score']:<8.4f} | {elo_m['accuracy']:<9.2f}% | {elo_m['ece']:<8.4f}")
        print(f"{'2024-25 Naive 50/50':<20} | {0.6931:<10.4f} | {0.2500:<8.4f} | {50.00:<9.2f}% | {0.0000:<8.4f}")
        print("-" * 75)

        # Save JSON & Markdown reports
        reports_dir = os.path.join(project_root, "reports")
        os.makedirs(reports_dir, exist_ok=True)
        json_path = os.path.join(reports_dir, "backtest_results_v1.4.0.json")
        md_path = os.path.join(reports_dir, "backtest_results_v1.4.0.md")

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)

        md_content = f"""# PuckLens v1.4.0 Authoritative Artifact-Bound Holdout Report (2024-25)

- **Evaluation Timestamp:** `{results['evaluated_at']}`
- **Run UUID:** `{results['run_uuid']}`
- **Git Commit SHA:** `{results['git_commit_sha']}`
- **Model Version:** `{results['model_version']}`
- **Model Artifact SHA-256:** `{results['artifact_sha256']}`
- **Feature Schema Version:** `{results['feature_schema_version']}`

## Protocol & Provenance Metadata

- **Candidate Training Split (2021-22):** Model candidate parameter fitting
- **Selection Split (2022-23):** Model selection criterion via Log Loss
- **Production Refit (2021-22 + 2022-23):** Selected model refitted on combined historical dataset
- **Calibration Split (2023-24):** Isotonic Regression calibrator fit on validation predictions
- **Authoritative Untouched Holdout (2024-25):** 100% untouched test evaluation using `ForecastModelRegistry.load_active_model()`

## Out-of-Time Performance Comparison (2024-25 Test Holdout)

| Model / Baseline | Log Loss | Brier Score | Accuracy (%) | ECE |
|---|---|---|---|---|
| **PuckLens v1.4.0 (Production Artifact)** | **{test_m['log_loss']:.4f}** | **{test_m['brier_score']:.4f}** | **{test_m['accuracy']:.2f}%** | **{test_m['ece']:.4f}** |
| Elo Baseline Model | {elo_m['log_loss']:.4f} | {elo_m['brier_score']:.4f} | {elo_m['accuracy']:.2f}% | {elo_m['ece']:.4f} |
| Naive 50/50 Baseline | 0.6931 | 0.2500 | 50.00% | 0.0000 |

## Score Projection Model Evaluation (2024-25)

- **Expected Total Goals MAE:** {results['test_season_20242025_eval']['score_projection']['expected_total_goals_mae']} goals
- **Home Goals MAE:** {results['test_season_20242025_eval']['score_projection']['home_goals_mae']} goals
- **Away Goals MAE:** {results['test_season_20242025_eval']['score_projection']['away_goals_mae']} goals
- **Exact (Top 1) Scoreline Coverage:** {results['test_season_20242025_eval']['score_projection']['exact_scoreline_coverage_pct']}% of games
- **Top 5 Exact Scoreline Coverage:** {results['test_season_20242025_eval']['score_projection']['top5_scoreline_coverage_pct']}% of games

> [!IMPORTANT]
> This evaluation strictly loads the active frozen production model artifact using `ForecastModelRegistry.load_active_model()`. Zero fitting, refitting, calibrating, or hyperparameter tuning was executed during this evaluation.
"""
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md_content)

        print(f"\nAuthoritative report saved to {json_path} and {md_path}")
        return results

if __name__ == "__main__":
    run()
