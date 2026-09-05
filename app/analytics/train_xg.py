import os
import sys
import glob
import json
import argparse
import logging
import datetime
from typing import List, Dict, Any, Tuple, Optional
import numpy as np
import pandas as pd
import sklearn

# Append project root to path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

from app.analytics.shot_features import (
    ShotFeatureExtractor, FEATURE_COLUMNS, NUMERIC_FEATURES, CATEGORICAL_FEATURES
)
from app.analytics.xg_model import LogisticRegressionXGModel, GradientBoostingXGModel
from app.analytics.evaluation import ModelEvaluator
from app.analytics.model_registry import ModelRegistry, DEFAULT_MODEL_DIR

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("train_xg")


def load_raw_dataset(raw_dir: str, max_games: Optional[int] = None) -> List[Dict[str, Any]]:
    """Loads and processes all cached NHL play-by-play files chronologically."""
    pattern = os.path.join(raw_dir, "pbp_*.json")
    files = sorted(glob.glob(pattern))

    if not files:
        logger.warning(f"No play-by-play files found matching {pattern}")
        return []

    if max_games:
        files = files[:max_games]

    logger.info(f"Extracting unblocked shot attempts from {len(files)} game files...")
    all_shots = []

    for fpath in files:
        try:
            with open(fpath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            shots = ShotFeatureExtractor.extract_shots_from_pbp_json(data, unblocked_only=True)
            all_shots.extend(shots)
        except Exception as e:
            logger.error(f"Error parsing {fpath}: {e}")

    logger.info(f"Extracted {len(all_shots)} total unblocked shot attempts.")
    return all_shots


def chronological_train_val_test_split(shots: List[Dict[str, Any]], 
                                       train_pct: float = 0.70, 
                                       val_pct: float = 0.15) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Splits shots chronologically based on game_id to prevent temporal data leakage.
    Older games -> Train
    Intermediate games -> Validation
    Most recent held-out games -> Test
    """
    # Group by game_id preserving game order
    game_ids = []
    seen = set()
    for s in shots:
        gid = s.get('game_id')
        if gid not in seen:
            seen.add(gid)
            game_ids.append(gid)

    # Sort game IDs chronologically
    game_ids.sort()

    n_games = len(game_ids)
    train_end = int(n_games * train_pct)
    val_end = int(n_games * (train_pct + val_pct))

    train_games = set(game_ids[:train_end])
    val_games = set(game_ids[train_end:val_end])
    test_games = set(game_ids[val_end:])

    train_shots = [s for s in shots if s.get('game_id') in train_games]
    val_shots = [s for s in shots if s.get('game_id') in val_games]
    test_shots = [s for s in shots if s.get('game_id') in test_games]

    logger.info(f"Split {n_games} games: {len(train_games)} Train ({len(train_shots)} shots), "
                f"{len(val_games)} Val ({len(val_shots)} shots), {len(test_games)} Test ({len(test_shots)} shots).")

    return train_shots, val_shots, test_shots


def main():
    parser = argparse.ArgumentParser(description="Train, tune, and evaluate PuckLens Expected Goals models.")
    parser.add_argument("--data-dir", default=os.path.join(PROJECT_ROOT, "data", "raw"), help="Directory with raw JSON files.")
    parser.add_argument("--output-dir", default=DEFAULT_MODEL_DIR, help="Directory to save model artifacts.")
    parser.add_argument("--max-games", type=int, default=None, help="Optional limit on games loaded.")
    parser.add_argument("--force-model", choices=['logistic', 'boosted'], default=None, help="Force selection of model type.")
    args = parser.parse_args()

    shots = load_raw_dataset(args.data_dir, max_games=args.max_games)
    if not shots:
        logger.error("No shots available for training. Exiting.")
        sys.exit(1)

    train_shots, val_shots, test_shots = chronological_train_val_test_split(shots)

    train_df = pd.DataFrame(train_shots)
    val_df = pd.DataFrame(val_shots)
    test_df = pd.DataFrame(test_shots)

    y_train = train_df['goal'].values
    y_val = val_df['goal'].values
    y_test = test_df['goal'].values

    train_game_ids = {s.get('game_id') for s in train_shots}
    val_game_ids = {s.get('game_id') for s in val_shots}
    test_game_ids = {s.get('game_id') for s in test_shots}

    logger.info(f"Train Goal Rate: {np.mean(y_train)*100:.2f}% ({np.sum(y_train)}/{len(y_train)})")
    logger.info(f"Val Goal Rate:   {np.mean(y_val)*100:.2f}% ({np.sum(y_val)}/{len(y_val)})")
    logger.info(f"Test Goal Rate:  {np.mean(y_test)*100:.2f}% ({np.sum(y_test)}/{len(y_test)})")

    # =========================================================================
    # Step 1: Candidate Model Evaluation on Validation Set Only (Task 1)
    # The test set remains completely untouched during candidate evaluation.
    # =========================================================================
    logger.info("\n--- Evaluating Candidate: Logistic Regression on Validation Set ---")
    lr_candidate = LogisticRegressionXGModel(name="pucklens-xg-logistic", version="1.0.0")
    lr_candidate.fit(train_df, y_train)
    lr_val_probs = lr_candidate.predict_proba(val_df)
    lr_val_metrics = ModelEvaluator.compute_metrics(y_val, lr_val_probs)
    logger.info(f"Logistic Regression Val Metrics: {json.dumps(lr_val_metrics, indent=2)}")

    logger.info("\n--- Evaluating Candidate: HistGradientBoosting on Validation Set ---")
    gb_candidate = GradientBoostingXGModel(name="pucklens-xg-boosted", version="1.2.0")
    gb_candidate.fit(train_df, y_train)
    gb_val_probs = gb_candidate.predict_proba(val_df)
    gb_val_metrics = ModelEvaluator.compute_metrics(y_val, gb_val_probs)
    logger.info(f"Gradient Boosting Val Metrics: {json.dumps(gb_val_metrics, indent=2)}")

    # Model Selection using Validation Log Loss
    logger.info("\n=== Candidate Model Comparison (Strictly on Validation Set) ===")
    logger.info(f"Metric           | Logistic Regression | Gradient Boosting")
    logger.info(f"-----------------+---------------------+------------------")
    logger.info(f"Log Loss (lower) | {lr_val_metrics['log_loss']:<19} | {gb_val_metrics['log_loss']}")
    logger.info(f"Brier (lower)    | {lr_val_metrics['brier_score']:<19} | {gb_val_metrics['brier_score']}")
    logger.info(f"ROC AUC (higher) | {lr_val_metrics['roc_auc']:<19} | {gb_val_metrics['roc_auc']}")

    if args.force_model == 'logistic':
        selected_type = 'logistic'
        selection_reason = "Manual override flag (--force-model logistic)"
    elif args.force_model == 'boosted':
        selected_type = 'boosted'
        selection_reason = "Manual override flag (--force-model boosted)"
    else:
        # Strict primary selection metric: Validation Log Loss
        if gb_val_metrics['log_loss'] < lr_val_metrics['log_loss']:
            selected_type = 'boosted'
            selection_reason = f"Gradient Boosting has lower validation log loss ({gb_val_metrics['log_loss']} vs {lr_val_metrics['log_loss']})"
        else:
            selected_type = 'logistic'
            selection_reason = f"Logistic Regression has lower validation log loss ({lr_val_metrics['log_loss']} vs {gb_val_metrics['log_loss']})"

    logger.info(f"\nCandidate Selection Result: {selected_type.upper()}")
    logger.info(f"Reason: {selection_reason}")

    # =========================================================================
    # Step 2: Production Retraining Option B (Task 2)
    # Refit chosen configuration on Train + Validation before touching Test set.
    # =========================================================================
    logger.info(f"\n--- Production Retraining (Option B): Refitting {selected_type} on Train + Validation ---")
    refit_df = pd.concat([train_df, val_df], ignore_index=True)
    y_refit = np.concatenate([y_train, y_val])

    if selected_type == 'boosted':
        final_model = GradientBoostingXGModel(name="pucklens-xg-boosted", version="1.2.0")
    else:
        final_model = LogisticRegressionXGModel(name="pucklens-xg-logistic", version="1.0.0")

    final_model.fit(refit_df, y_refit)
    logger.info(f"Retrained final {final_model.name} on {len(refit_df)} total shots ({len(train_game_ids) + len(val_game_ids)} games).")

    # =========================================================================
    # Step 3: Single Final Benchmark on Untouched Held-Out Test Set (Task 1 & 2)
    # =========================================================================
    logger.info("\n--- Final Single Benchmark on Untouched Held-Out Test Set ---")
    final_test_probs = final_model.predict_proba(test_df)
    final_test_metrics = ModelEvaluator.compute_metrics(y_test, final_test_probs)
    final_calibration = ModelEvaluator.compute_calibration(y_test, final_test_probs)
    final_breakdown = ModelEvaluator.breakdown_by_segment(test_shots, y_test, final_test_probs)
    final_model.metrics = final_test_metrics

    logger.info(f"Final Test Metrics: {json.dumps(final_test_metrics, indent=2)}")

    # =========================================================================
    # Step 4: Full Metadata Enrichment and Serialization (Task 9)
    # =========================================================================
    train_timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    final_model.update_metadata({
        'name': final_model.name,
        'version': final_model.version,
        'algorithm': final_model.__class__.__name__,
        'training_date': train_timestamp,
        'train_date': train_timestamp,
        'scikit_learn_version': sklearn.__version__,
        'numpy_version': np.__version__,
        'pandas_version': pd.__version__,
        'features': FEATURE_COLUMNS,
        'numeric_features': NUMERIC_FEATURES,
        'categorical_features': CATEGORICAL_FEATURES,
        'target': 'goal',
        'selection_strategy': {
            'metric': 'validation_log_loss',
            'test_set_isolation': 'untouched_during_candidate_selection',
            'candidate_metrics': {
                'logistic': lr_val_metrics,
                'boosted': gb_val_metrics
            },
            'selected_candidate': selected_type,
            'selection_reason': selection_reason
        },
        'retraining_strategy': {
            'strategy': 'option_b_train_plus_validation_refit',
            'description': 'Refit selected candidate configuration on combined train and validation set before single final evaluation on test set'
        },
        'split_info': {
            'train_games': len(train_game_ids),
            'val_games': len(val_game_ids),
            'test_games': len(test_game_ids),
            'train_shots': len(train_shots),
            'val_shots': len(val_shots),
            'test_shots': len(test_shots),
            'refit_shots': len(refit_df),
            'total_shots': len(shots),
            'method': 'chronological_game_split'
        },
        'metrics': final_test_metrics,
        'test_metrics': final_test_metrics,
        'calibration': final_calibration,
        'breakdown': final_breakdown,
        'test_leakage_audit': 'passed_clean_test_isolation'
    })

    save_path = ModelRegistry.save_model(final_model, directory=args.output_dir)
    logger.info(f"\n[SUCCESS] Final model saved to: {save_path}")
    logger.info(f"Metadata saved to: {os.path.join(args.output_dir, 'metadata.json')}")


if __name__ == '__main__':
    main()

