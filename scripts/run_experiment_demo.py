"""
Demonstration Script for Stage 5 Modelling & Experiment Foundation.

Runs end-to-end classification and regression experiments on real database games:
1. Game-level Classification Experiment (Home Win Prediction).
2. Game-level Regression Experiment (Total Goals Prediction).
"""

import sys
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

# Add project root to sys.path
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from app import create_app
from app.models import db, Game
from app.services.pregame_feature_service import PregameFeatureService
from app.analytics.experiments.point_in_time import PointInTimeAdapter, TemporalLeakageError
from app.analytics.experiments.experiment_config import ExperimentConfig, TASK_CLASSIFICATION, TASK_REGRESSION
from app.analytics.experiments.runner import ExperimentRunner

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("run_experiment_demo")


def build_demo_dataset(limit_per_season: int = 100):
    """
    Constructs point-in-time dataset from completed database games across 2021-22 and 2022-23.
    """
    logger.info("Preloading pregame feature service stats...")
    PregameFeatureService.preload_all_stats()

    games = Game.query.filter(
        Game.game_type == 'R',
        Game.data_source == 'nhl_api',
        Game.nhl_game_state.in_(['OFF', 'FINAL', 'OVER'])
    ).order_by(
        Game.season.asc(),
        Game.game_id.asc()
    ).all()

    dataset_clf = []
    dataset_reg = []

    season_counts = {}
    for g in games:
        s = g.season
        if s not in ['20212022', '20222023']:
            continue

        season_counts[s] = season_counts.get(s, 0) + 1
        if season_counts[s] > limit_per_season:
            continue

        # Extract point-in-time features with explicit cutoff auditing
        try:
            feats, cutoff = PointInTimeAdapter.extract_game_features_with_cutoff(g)
        except TemporalLeakageError as e:
            # Skip games that have no prior source game history in the database
            continue

        g_start = cutoff.prediction_cutoff_time

        # Classification target (Home Win)
        target_clf = 1 if g.home_score > g.away_score else 0

        # Regression target (Total Goals)
        target_reg = float(g.home_score + g.away_score)

        record_clf = {
            "game_id": g.game_id,
            "season": g.season,
            "timestamp": g_start,
            "target": target_clf,
            "features": feats,
            "point_in_time_cutoff": cutoff.to_dict()
        }

        record_reg = {
            "game_id": g.game_id,
            "season": g.season,
            "timestamp": g_start,
            "target": target_reg,
            "features": feats,
            "point_in_time_cutoff": cutoff.to_dict()
        }

        dataset_clf.append(record_clf)
        dataset_reg.append(record_reg)

    return dataset_clf, dataset_reg


def main():
    app = create_app()
    with app.app_context():
        logger.info("Starting Stage 5 Demonstration Experiments...")
        dataset_clf, dataset_reg = build_demo_dataset(limit_per_season=50)

        feature_set = ["home_l10_gf_per_game", "away_l10_gf_per_game", "home_l10_ga_per_game", "away_l10_ga_per_game"]

        # 1. Classification Experiment
        config_clf = ExperimentConfig(
            experiment_id="exp_stage5_win_logistic_v1",
            name="Stage 5 Game Win Classification Baseline",
            task_type=TASK_CLASSIFICATION,
            target="home_win",
            feature_set=feature_set,
            train_window={"seasons": ["20212022"]},
            validation_window={"seasons": ["20222023"]},
            model_type="simple_logistic",
            hyperparameters={"C": 1.0},
            seed=42
        )

        result_clf = ExperimentRunner.run_experiment(config_clf, dataset_clf)

        # 2. Regression Experiment
        config_reg = ExperimentConfig(
            experiment_id="exp_stage5_total_goals_ridge_v1",
            name="Stage 5 Total Goals Regression Baseline",
            task_type=TASK_REGRESSION,
            target="total_goals",
            feature_set=feature_set,
            train_window={"seasons": ["20212022"]},
            validation_window={"seasons": ["20222023"]},
            model_type="simple_linear",
            hyperparameters={"alpha": 1.0},
            seed=42
        )

        result_reg = ExperimentRunner.run_experiment(config_reg, dataset_reg)

        print("\n" + "=" * 80)
        print("STAGE 5 CLASSIFICATION EXPERIMENT RESULT JSON:")
        print("=" * 80)
        print(result_clf.to_json())

        print("\n" + "=" * 80)
        print("STAGE 5 REGRESSION EXPERIMENT RESULT JSON:")
        print("=" * 80)
        print(result_reg.to_json())

        print("\nStage 5 Demonstration Complete.")


if __name__ == "__main__":
    main()
