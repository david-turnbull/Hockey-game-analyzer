import os
import sys
import glob
import json
import argparse
import logging
from typing import List, Dict, Any, Tuple, Optional
import numpy as np
import pandas as pd

# Append project root to path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

from app.analytics.shot_features import ShotFeatureExtractor
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
    Splits shots chronologically based on game_id / game_date to prevent temporal data leakage.
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
    parser = argparse.ArgumentParser(description="Train and evaluate PuckLens Expected Goals models.")
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

    logger.info(f"Train Goal Rate: {np.mean(y_train)*100:.2f}% ({np.sum(y_train)}/{len(y_train)})")
    logger.info(f"Val Goal Rate:   {np.mean(y_val)*100:.2f}% ({np.sum(y_val)}/{len(y_val)})")
    logger.info(f"Test Goal Rate:  {np.mean(y_test)*100:.2f}% ({np.sum(y_test)}/{len(y_test)})")

    # 1. Train Baseline Logistic Regression
    logger.info("\n--- Training Baseline Logistic Regression ---")
    lr_model = LogisticRegressionXGModel(name="pucklens-xg-logistic", version="1.0.0")
    lr_model.fit(train_df, y_train)

    lr_test_probs = lr_model.predict_proba(test_df)
    lr_metrics = ModelEvaluator.compute_metrics(y_test, lr_test_probs)
    lr_calib = ModelEvaluator.compute_calibration(y_test, lr_test_probs)
    lr_model.metrics = lr_metrics
    logger.info(f"Logistic Regression Test Metrics: {json.dumps(lr_metrics, indent=2)}")

    # 2. Train Gradient Boosting Model
    logger.info("\n--- Training HistGradientBoosting Model ---")
    gb_model = GradientBoostingXGModel(name="pucklens-xg-boosted", version="1.2.0")
    gb_model.fit(train_df, y_train)

    gb_test_probs = gb_model.predict_proba(test_df)
    gb_metrics = ModelEvaluator.compute_metrics(y_test, gb_test_probs)
    gb_calib = ModelEvaluator.compute_calibration(y_test, gb_test_probs)
    gb_model.metrics = gb_metrics
    logger.info(f"Gradient Boosting Test Metrics: {json.dumps(gb_metrics, indent=2)}")

    # 3. Model Comparison
    logger.info("\n=== Model Comparison on Held-Out Test Set ===")
    logger.info(f"Metric           | Logistic Regression | Gradient Boosting")
    logger.info(f"-----------------+---------------------+------------------")
    logger.info(f"Log Loss (lower) | {lr_metrics['log_loss']:<19} | {gb_metrics['log_loss']}")
    logger.info(f"Brier (lower)    | {lr_metrics['brier_score']:<19} | {gb_metrics['brier_score']}")
    logger.info(f"ROC AUC (higher) | {lr_metrics['roc_auc']:<19} | {gb_metrics['roc_auc']}")

    # Select production model
    selected_model: BaseXGModel
    if args.force_model == 'logistic':
        selected_model = lr_model
        logger.info("Selection: Forced Logistic Regression.")
    elif args.force_model == 'boosted':
        selected_model = gb_model
        logger.info("Selection: Forced Gradient Boosting.")
    else:
        # Prioritize lower Log Loss and higher ROC AUC if calibration is sound
        if gb_metrics['log_loss'] <= lr_metrics['log_loss'] and gb_metrics['roc_auc'] >= lr_metrics['roc_auc']:
            selected_model = gb_model
            logger.info("Selection: Gradient Boosting selected due to superior Log Loss and ROC AUC.")
        else:
            selected_model = lr_model
            logger.info("Selection: Logistic Regression selected for parsimony and calibration.")

    # Compute detailed segment breakdown for selected model
    breakdown = ModelEvaluator.breakdown_by_segment(
        test_shots, y_test, selected_model.predict_proba(test_df)
    )

    selected_model.metadata['split_info'] = {
        'train_shots': len(train_shots),
        'val_shots': len(val_shots),
        'test_shots': len(test_shots),
        'total_shots': len(shots),
        'method': 'chronological_game_split'
    }
    selected_model.metadata['calibration'] = gb_calib if selected_model == gb_model else lr_calib
    selected_model.metadata['breakdown'] = breakdown
    selected_model.metadata['comparison'] = {
        'logistic_metrics': lr_metrics,
        'boosted_metrics': gb_metrics
    }

    # Save to disk
    save_path = ModelRegistry.save_model(selected_model, directory=args.output_dir)
    logger.info(f"\n[SUCCESS] Production Expected Goals model saved to: {save_path}")
    logger.info(f"Metadata saved to: {os.path.join(args.output_dir, 'metadata.json')}")


if __name__ == '__main__':
    main()
