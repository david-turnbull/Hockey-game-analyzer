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

def run(season: str = '20252026', skip_gate: bool = False):
    app = create_app('development')
    with app.app_context():
        print("\n" + "=" * 80)
        print(f" PuckLens v1.4.0 Stage 4 External Season Validation ({season[:4]}-{season[6:]})")
        print("=" * 80)

        engine = BacktestEngine()
        results = engine.evaluate_external_season(season=season, skip_gate=skip_gate)

        eval_key = f"external_season_{season}_eval"
        ext_m = results[eval_key]["calibrated_model"]
        ext_elo = results[eval_key]["elo_baseline"]
        holdout_m = results["holdout_season_20242025_eval"]["calibrated_model"]

        print(f" Evaluated At:               {results['evaluated_at']}")
        print(f" Run UUID:                   {results['run_uuid']}")
        print(f" Model Version:              {results['model_version']}")
        print(f" Model Training Git SHA:     {results['model_training_git_sha']}")
        print(f" Evaluation Git SHA:         {results['evaluation_git_sha']}")
        print(f" Artifact SHA-256:           {results['artifact_sha256']}")
        print(f" Feature Schema Version:     {results['feature_schema_version']}")
        print(f" Data Audit Snapshot Hash:   {results['data_audit_snapshot_hash']}")
        print("=" * 80)
        print(f"{'Split / Model':<30} | {'Log Loss':<10} | {'Brier':<8} | {'Accuracy':<10} | {'ECE':<8}")
        print("-" * 80)
        print(f"{'2024-25 Holdout (Model)':<30} | {holdout_m['log_loss']:<10.4f} | {holdout_m['brier_score']:<8.4f} | {holdout_m['accuracy']:<9.2f}% | {holdout_m['ece']:<8.4f}")
        print(f"{f'{season[:4]}-{season[6:]} External (Model)':<30} | {ext_m['log_loss']:<10.4f} | {ext_m['brier_score']:<8.4f} | {ext_m['accuracy']:<9.2f}% | {ext_m['ece']:<8.4f}")
        print(f"{f'{season[:4]}-{season[6:]} External (Elo)':<30} | {ext_elo['log_loss']:<10.4f} | {ext_elo['brier_score']:<8.4f} | {ext_elo['accuracy']:<9.2f}% | {ext_elo['ece']:<8.4f}")
        print(f"{f'{season[:4]}-{season[6:]} Naive 50/50':<30} | {0.6931:<10.4f} | {0.2500:<8.4f} | {50.00:<9.2f}% | {0.0000:<8.4f}")
        print("-" * 80)

        deltas = results["generalization_delta_metrics"]
        print(f" Generalization Deltas ({season} vs 2024-25 Holdout):")
        print(f"   Delta Log Loss:    {deltas['delta_log_loss']:+.4f}")
        print(f"   Delta Brier Score: {deltas['delta_brier_score']:+.4f}")
        print(f"   Delta ECE:         {deltas['delta_ece']:+.4f}")
        print("=" * 80)


        # Save JSON & Markdown reports
        reports_dir = os.path.join(project_root, "reports")
        os.makedirs(reports_dir, exist_ok=True)
        json_path = os.path.join(reports_dir, f"stage4_external_validation_{season}.json")
        md_path = os.path.join(reports_dir, f"stage4_external_validation_{season}.md")

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)

        # Build Markdown Report
        md_content = f"""# Stage 4: {season[:4]}-{season[6:]} External Season Validation Report

**Evaluated At:** `{results['evaluated_at']}`  
**Run UUID:** `{results['run_uuid']}`  
**Model Version:** `{results['model_version']}`  
**Model Training Git SHA:** `{results['model_training_git_sha']}`  
**Evaluation Git SHA:** `{results['evaluation_git_sha']}`  
**Artifact SHA-256:** `{results['artifact_sha256']}`  
**Feature Schema Version:** `{results['feature_schema_version']}`  
**Data Audit Snapshot Hash:** `{results['data_audit_snapshot_hash']}`  

## Provenance & Protocol Summary

- **Candidate Training:** `20212022` fit candidate architectures
- **Model Selection:** `20222023` select via Log Loss
- **Combined Production Refit:** `20212022 + 20222023`
- **Isotonic Calibration:** `20232024`
- **Frozen Holdout Baseline:** `20242025`
- **External Untouched Season:** `{season}` (`{season[:4]}-{season[6:]}`)

> [!NOTE]
> Evaluation loaded the frozen production model artifact using `ForecastModelRegistry.load_active_model()`. Zero fitting, refitting, calibrating, or hyperparameter tuning was executed.

## Out-of-Time Performance Comparison

| Dataset / Model | Log Loss | Brier Score | Accuracy (%) | ECE |
|---|---|---|---|---|
| **2024-25 Frozen Holdout (Model)** | **{holdout_m['log_loss']:.4f}** | **{holdout_m['brier_score']:.4f}** | **{holdout_m['accuracy']:.2f}%** | **{holdout_m['ece']:.4f}** |
| **{season[:4]}-{season[6:]} External Season (Model)** | **{ext_m['log_loss']:.4f}** | **{ext_m['brier_score']:.4f}** | **{ext_m['accuracy']:.2f}%** | **{ext_m['ece']:.4f}** |
| {season[:4]}-{season[6:]} Continuous Elo Baseline | {ext_elo['log_loss']:.4f} | {ext_elo['brier_score']:.4f} | {ext_elo['accuracy']:.2f}% | {ext_elo['ece']:.4f} |
| Naive 50/50 Baseline | 0.6931 | 0.2500 | 50.00% | 0.0000 |

## Generalization Delta Analysis ({season[:4]}-{season[6:]} vs 2024-25 Holdout)

- **Δ Log Loss:** `{deltas['delta_log_loss']:+.4f}`
- **Δ Brier Score:** `{deltas['delta_brier_score']:+.4f}`
- **Δ Expected Calibration Error (ECE):** `{deltas['delta_ece']:+.4f}`

## 10 Probability Calibration Bins ({season[:4]}-{season[6:]})

| Bin Range | Sample Count | Avg Pred Prob | Actual Win Rate | Abs Calib Error | Bin Brier Score |
|---|---|---|---|---|---|
"""
        for b in results[eval_key].get("calibration_bins", []):
            md_content += f"| `{b['bin_range']}` | {b['count']} | {b['avg_predicted_prob']:.4f} | {b['actual_win_rate']:.4f} | {b['abs_calibration_error']:.4f} | {b['bin_brier_score']:.4f} |\n"

        md_content += f"""
## Timeline Season Splits ({season[:4]}-{season[6:]})

| Season Segment | Games | Log Loss | Brier Score | Accuracy (%) | ECE |
|---|---|---|---|---|---|
"""
        for seg_name, seg_data in results[eval_key].get("season_timeline_splits", {}).items():
            m = seg_data["metrics"]
            disp_name = seg_name.replace("_", " ").title()
            md_content += f"| **{disp_name}** | {seg_data['game_count']} | {m['log_loss']:.4f} | {m['brier_score']:.4f} | {m['accuracy']:.2f}% | {m['ece']:.4f} |\n"

        md_content += f"""
## Bootstrap 95% Confidence Intervals (Model vs Elo Difference on {season[:4]}-{season[6:]})

- **Log Loss Difference (Model - Elo):** `{results['bootstrap_confidence_intervals'].get('log_loss_difference', {}).get('mean_diff', 0.0):+.4f}` (95% CI: `[{results['bootstrap_confidence_intervals'].get('log_loss_difference', {}).get('ci_95_lower', 0.0):+.4f}, {results['bootstrap_confidence_intervals'].get('log_loss_difference', {}).get('ci_95_upper', 0.0):+.4f}]`, SE: `{results['bootstrap_confidence_intervals'].get('log_loss_difference', {}).get('std_error', 0.0):.4f}`)
- **Brier Score Difference (Model - Elo):** `{results['bootstrap_confidence_intervals'].get('brier_score_difference', {}).get('mean_diff', 0.0):+.4f}` (95% CI: `[{results['bootstrap_confidence_intervals'].get('brier_score_difference', {}).get('ci_95_lower', 0.0):+.4f}, {results['bootstrap_confidence_intervals'].get('brier_score_difference', {}).get('ci_95_upper', 0.0):+.4f}]`, SE: `{results['bootstrap_confidence_intervals'].get('brier_score_difference', {}).get('std_error', 0.0):.4f}`)


## Score Projection Evaluation ({season[:4]}-{season[6:]})

- **Expected Total Goals MAE:** {results[eval_key]['score_projection']['expected_total_goals_mae']} goals
- **Home Goals MAE:** {results[eval_key]['score_projection']['home_goals_mae']} goals
- **Away Goals MAE:** {results[eval_key]['score_projection']['away_goals_mae']} goals
- **Top 1 Exact Scoreline Coverage:** {results[eval_key]['score_projection']['exact_scoreline_coverage_pct']}%
- **Top 5 Exact Scoreline Coverage:** {results[eval_key]['score_projection']['top5_scoreline_coverage_pct']}%
"""

        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md_content)

        print(f"\nStage 4 Reports saved to {json_path} and {md_path}\n")
        return results

if __name__ == "__main__":
    run()
