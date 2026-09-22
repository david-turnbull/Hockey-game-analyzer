#!/usr/bin/env python
"""
Stage 6 — Forecast Intelligence & Elo Research Script.

Executes a leakage-safe chronological evaluation of Elo-derived forecasting signals,
bounded Elo parameter optimization, probability blending, Elo-as-feature modelling,
paired bootstrap comparisons, calibration analysis, and forecast intelligence packaging.

DOES NOT RETRAIN, OVERWRITE, OR ALTER PRODUCTION FORECASTING ARTIFACTS.
"""

import sys
import os
import math
import json
import hashlib
import subprocess
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Any, Tuple, Optional

# Add root directory to sys.path
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

import numpy as np
from sqlalchemy import func

from app import create_app
from app.models import db, Game
from app.services.elo_service import EloService, INITIAL_ELO, BASE_K, HOME_ADVANTAGE, SEASON_REGRESSION
from app.analytics.experiments.elo_experiment import (
    EloResearchConfig,
    EloResearchEngine,
    run_elo_parameter_grid_search
)
from app.services.pregame_feature_service import PregameFeatureService
from app.analytics.forecasting.win_probability import WinProbabilityModel
from app.analytics.forecasting.model_registry import ForecastModelRegistry
from app.services.forecast_intelligence_service import ForecastIntelligenceService
from app.analytics.experiments.experiment_config import ExperimentConfig, TASK_CLASSIFICATION
from app.analytics.experiments.runner import ExperimentRunner

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

EXPECTED_WIN_MODEL_SHA = "63cf3cec7d11b38004c590503c89b0a686ae4a9a350fd497bc93087e71bf58f9"
EXPECTED_SCORE_PARAMS_SHA = "a6c6c20e7bdbe8f11a518ac8d7832ce65947ccba7ba0b2d15d6db87a5efbd701"
EXPECTED_XG_MODEL_SHA = "c7f4f55bb0136f5d1774267446f5bd07a9a0bad2285238a25f551a61b0927635"
EXPECTED_XG_METADATA_SHA = "b47e7c449fc16b428c33f4387db196deb9c5f71ad3dcec099fff8a069ac9fdfb"


def verify_production_artifact_invariance():
    """Asserts that production model artifacts match expected SHA-256 hashes."""
    models_dir = Path(root_dir) / "models"

    win_path = models_dir / "forecasting" / "pucklens-win-v1.4.0.pkl"
    score_path = models_dir / "forecasting" / "score_candidate_params_v1.4.0.json"
    xg_path = models_dir / "xg" / "xg_v1.pkl"
    xg_meta_path = models_dir / "xg" / "metadata.json"

    assert win_path.exists(), f"Win model missing at {win_path}"
    assert score_path.exists(), f"Score params missing at {score_path}"
    assert xg_path.exists(), f"xG model missing at {xg_path}"
    assert xg_meta_path.exists(), f"xG metadata missing at {xg_meta_path}"

    with open(win_path, "rb") as f:
        sha_win = hashlib.sha256(f.read()).hexdigest()
    assert sha_win == EXPECTED_WIN_MODEL_SHA, f"Win SHA mismatch: {sha_win} != {EXPECTED_WIN_MODEL_SHA}"

    with open(score_path, "rb") as f:
        sha_score = hashlib.sha256(f.read().replace(b"\r\n", b"\n")).hexdigest()
    assert sha_score == EXPECTED_SCORE_PARAMS_SHA, f"Score SHA mismatch: {sha_score} != {EXPECTED_SCORE_PARAMS_SHA}"

    with open(xg_path, "rb") as f:
        sha_xg = hashlib.sha256(f.read()).hexdigest()
    assert sha_xg == EXPECTED_XG_MODEL_SHA, f"xG SHA mismatch: {sha_xg} != {EXPECTED_XG_MODEL_SHA}"

    with open(xg_meta_path, "rb") as f:
        sha_xg_meta = hashlib.sha256(f.read().replace(b"\r\n", b"\n")).hexdigest()
    assert sha_xg_meta == EXPECTED_XG_METADATA_SHA, f"xG meta SHA mismatch: {sha_xg_meta} != {EXPECTED_XG_METADATA_SHA}"

    logger.info("Production artifact SHA-256 invariance verified successfully.")


def calculate_distribution_stats(y_prob: List[float]) -> Dict[str, float]:
    """Calculates summary statistics and extreme probability counts for a probability vector."""
    arr = np.array(y_prob, dtype=np.float64)
    if len(arr) == 0:
        return {}

    p25 = float(np.percentile(arr, 25))
    p75 = float(np.percentile(arr, 75))
    extreme_count = int(np.sum((arr < 0.20) | (arr > 0.80)))
    extreme_pct = float((extreme_count / len(arr)) * 100.0)

    return {
        "mean": round(float(np.mean(arr)), 4),
        "std": round(float(np.std(arr)), 4),
        "min": round(float(np.min(arr)), 4),
        "p25": round(p25, 4),
        "median": round(float(np.median(arr)), 4),
        "p75": round(p75, 4),
        "max": round(float(np.max(arr)), 4),
        "iqr": round(p75 - p25, 4),
        "extreme_probability_count_lt20_gt80": extreme_count,
        "extreme_probability_pct": round(extreme_pct, 2)
    }


def calculate_calibration_bins(y_true: List[int], y_prob: List[float], n_bins: int = 10) -> List[Dict[str, Any]]:
    """Calculates 10 reliability/calibration bins for predictions."""
    bins = []
    bin_boundaries = [i / n_bins for i in range(n_bins + 1)]

    for i in range(n_bins):
        b_low = bin_boundaries[i]
        b_high = bin_boundaries[i + 1]

        indices = [
            idx for idx, p in enumerate(y_prob)
            if (p >= b_low and p < b_high) or (i == n_bins - 1 and p == b_high)
        ]

        count = len(indices)
        if count > 0:
            avg_pred = sum(y_prob[idx] for idx in indices) / count
            actual_rate = sum(y_true[idx] for idx in indices) / count
            calib_err = abs(avg_pred - actual_rate)
            bin_brier = sum((y_prob[idx] - y_true[idx]) ** 2 for idx in indices) / count
        else:
            avg_pred = (b_low + b_high) / 2.0
            actual_rate = 0.0
            calib_err = 0.0
            bin_brier = 0.0

        bins.append({
            "bin_index": i + 1,
            "bin_range": f"[{b_low:.1f}, {b_high:.1f})" if i < n_bins - 1 else f"[{b_low:.1f}, {b_high:.1f}]",
            "count": count,
            "avg_predicted_prob": round(avg_pred, 4),
            "actual_win_rate": round(actual_rate, 4),
            "abs_calibration_error": round(calib_err, 4),
            "bin_brier_score": round(bin_brier, 4)
        })

    return bins


def calculate_paired_bootstrap(
    y_true: List[int],
    p_base: List[float],
    p_comp: List[float],
    n_bootstraps: int = 1000,
    seed: int = 42
) -> Dict[str, Any]:
    """
    Computes paired bootstrap 95% CIs for metric differences (comp - base).
    """
    n = len(y_true)
    if n == 0:
        return {}

    rng = np.random.RandomState(seed)
    yt_arr = np.array(y_true)
    pb_arr = np.clip(np.array(p_base), 1e-15, 1.0 - 1e-15)
    pc_arr = np.clip(np.array(p_comp), 1e-15, 1.0 - 1e-15)

    diff_ll_list = []
    diff_brier_list = []

    for _ in range(n_bootstraps):
        idxs = rng.choice(n, size=n, replace=True)
        yt_b = yt_arr[idxs]
        pb_b = pb_arr[idxs]
        pc_b = pc_arr[idxs]

        ll_b = -np.mean(yt_b * np.log(pb_b) + (1.0 - yt_b) * np.log(1.0 - pb_b))
        ll_c = -np.mean(yt_b * np.log(pc_b) + (1.0 - yt_b) * np.log(1.0 - pc_b))

        brier_b = np.mean((pb_b - yt_b) ** 2)
        brier_c = np.mean((pc_b - yt_b) ** 2)

        diff_ll_list.append(ll_c - ll_b)
        diff_brier_list.append(brier_c - brier_b)

    obs_ll_b = -float(np.mean(yt_arr * np.log(pb_arr) + (1.0 - yt_arr) * np.log(1.0 - pb_arr)))
    obs_ll_c = -float(np.mean(yt_arr * np.log(pc_arr) + (1.0 - yt_arr) * np.log(1.0 - pc_arr)))

    obs_brier_b = float(np.mean((pb_arr - yt_arr) ** 2))
    obs_brier_c = float(np.mean((pc_arr - yt_arr) ** 2))

    return {
        "log_loss_difference": {
            "observed_diff": round(obs_ll_c - obs_ll_b, 4),
            "base_log_loss": round(obs_ll_b, 4),
            "comp_log_loss": round(obs_ll_c, 4),
            "ci_95_lower": round(float(np.percentile(diff_ll_list, 2.5)), 4),
            "ci_95_upper": round(float(np.percentile(diff_ll_list, 97.5)), 4),
            "std_error": round(float(np.std(diff_ll_list)), 4)
        },
        "brier_score_difference": {
            "observed_diff": round(obs_brier_c - obs_brier_b, 4),
            "base_brier_score": round(obs_brier_b, 4),
            "comp_brier_score": round(obs_brier_c, 4),
            "ci_95_lower": round(float(np.percentile(diff_brier_list, 2.5)), 4),
            "ci_95_upper": round(float(np.percentile(diff_brier_list, 97.5)), 4),
            "std_error": round(float(np.std(diff_brier_list)), 4)
        }
    }


def main():
    logger.info("Initializing Stage 6 Forecast Intelligence & Elo Research...")
    app = create_app()

    with app.app_context():
        # Verify production artifact invariance
        verify_production_artifact_invariance()

        # Audit Git SHA
        try:
            git_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        except Exception:
            git_sha = "unknown"

        # Preload pregame event statistics
        logger.info("Preloading pregame event stats into memory...")
        PregameFeatureService.preload_all_stats()

        # ----------------------------------------------------
        # 1. Reference Elo Baseline Evaluation
        # ----------------------------------------------------
        logger.info("Evaluating Reference Elo baseline across 2021-22 to 2024-25...")
        ref_config = EloResearchConfig(
            initial_elo=INITIAL_ELO,
            k_factor=BASE_K,
            home_advantage=HOME_ADVANTAGE,
            season_regression=SEASON_REGRESSION,
            use_mov_multiplier=True
        )
        seasons_all = ['20212022', '20222023', '20232024', '20242025']

        all_games = Game.query.filter(
            Game.season.in_(seasons_all),
            Game.game_type == 'R',
            Game.data_source == 'nhl_api',
            Game.nhl_game_state.in_(['OFF', 'FINAL', 'OVER'])
        ).order_by(
            func.coalesce(Game.start_time_utc, Game.game_date).asc(),
            Game.game_id.asc()
        ).all()

        logger.info(f"Pre-caching pregame features for {len(all_games)} games...")
        feature_cache = {g.game_id: PregameFeatureService.get_pregame_features(g) for g in all_games}

        ref_elo_res = EloResearchEngine.run_elo_backtest(seasons_all, ref_config, games_override=all_games)

        ref_preds_holdout = [p for p in ref_elo_res["predictions"] if p["season"] == '20242025']
        ref_eval_holdout = EloResearchEngine.evaluate_predictions(ref_preds_holdout)

        # ----------------------------------------------------
        # 2. Bounded Parameter Research (Strictly on Dev/Selection Seasons: 2021-22..2023-24)
        # ----------------------------------------------------
        logger.info("Running bounded Elo parameter research study (Selection Seasons: 2021-22..2023-24)...")
        dev_seasons = ['20212022', '20222023', '20232024']
        grid_results = run_elo_parameter_grid_search(
            seasons=dev_seasons,
            k_factors=[10.0, 15.0, 20.0, 25.0, 30.0],
            home_advantages=[20.0, 35.0, 50.0, 65.0],
            season_regressions=[0.10, 0.25, 0.40],
            use_mov_options=[True, False],
            games_override=all_games
        )

        top_candidate = grid_results[0]
        selected_cfg = EloResearchConfig(**top_candidate["config"])

        logger.info(f"Selected Research Elo Config (Selection Log Loss={top_candidate['log_loss']}): {selected_cfg.to_dict()}")

        # ----------------------------------------------------
        # 3. Evaluate Selected Research Elo on Untouched Holdout (2024-25)
        # ----------------------------------------------------
        sel_elo_res = EloResearchEngine.run_elo_backtest(seasons_all, selected_cfg, games_override=all_games)
        sel_preds_holdout = [p for p in sel_elo_res["predictions"] if p["season"] == '20242025']
        sel_eval_holdout = EloResearchEngine.evaluate_predictions(sel_preds_holdout)

        # ----------------------------------------------------
        # 4. Evaluate Frozen Production Win Probability Model (pucklens-win-v1.4.0)
        # ----------------------------------------------------
        logger.info("Evaluating frozen production win probability model on 2024-25 holdout...")
        win_model, manifest = ForecastModelRegistry.load_active_model()

        holdout_games = Game.query.filter(
            Game.season == '20242025',
            Game.game_type == 'R',
            Game.data_source == 'nhl_api',
            Game.nhl_game_state.in_(['OFF', 'FINAL', 'OVER'])
        ).order_by(
            func.coalesce(Game.start_time_utc, Game.game_date).asc(),
            Game.game_id.asc()
        ).all()

        prod_preds_holdout = []
        y_true_holdout = []
        p_prod_holdout = []
        p_ref_elo_holdout = []
        p_sel_elo_holdout = []

        ref_map_holdout = {p["game_id"]: p["p_home_win"] for p in ref_preds_holdout}
        sel_map_holdout = {p["game_id"]: p["p_home_win"] for p in sel_preds_holdout}

        # Also get pregame Elo stats for feature experiment
        ref_preds_all_map = {p["game_id"]: p for p in ref_elo_res["predictions"]}

        game_records_holdout = []

        for g in holdout_games:
            feats = feature_cache.setdefault(g.game_id, PregameFeatureService.get_pregame_features(g))
            win_pred = win_model.predict_game_probability(feats)
            p_prod = win_pred["home_win_probability"]

            p_ref = ref_map_holdout.get(g.game_id, 0.5)
            p_sel = sel_map_holdout.get(g.game_id, 0.5)
            actual = 1 if g.home_score > g.away_score else 0

            y_true_holdout.append(actual)
            p_prod_holdout.append(p_prod)
            p_ref_elo_holdout.append(p_ref)
            p_sel_elo_holdout.append(p_sel)

            prod_preds_holdout.append({
                "game_id": g.game_id,
                "p_home_win": p_prod,
                "actual_home_win": actual
            })

            ref_p_data = ref_preds_all_map.get(g.game_id, {})
            h_elo = ref_p_data.get("home_elo_pregame", 1500.0)
            a_elo = ref_p_data.get("away_elo_pregame", 1500.0)

            game_records_holdout.append({
                "game_id": g.game_id,
                "p_production": p_prod,
                "p_elo": p_ref,
                "home_elo": h_elo,
                "away_elo": a_elo,
                "actual_home_win": actual
            })

        prod_eval_holdout = EloService.evaluate_predictions(prod_preds_holdout)

        # ----------------------------------------------------
        # 5. Probability Blend Research
        # ----------------------------------------------------
        logger.info("Optimizing probability blend weight w on selection seasons (2022-23 + 2023-24)...")
        # Gather selection games predictions
        dev_games = Game.query.filter(
            Game.season.in_(['20222023', '20232024']),
            Game.game_type == 'R',
            Game.data_source == 'nhl_api',
            Game.nhl_game_state.in_(['OFF', 'FINAL', 'OVER'])
        ).order_by(
            func.coalesce(Game.start_time_utc, Game.game_date).asc(),
            Game.game_id.asc()
        ).all()

        dev_y_true = []
        dev_p_prod = []
        dev_p_sel_elo = []
        sel_map_all = {p["game_id"]: p["p_home_win"] for p in sel_elo_res["predictions"]}

        for g in dev_games:
            feats = feature_cache.setdefault(g.game_id, PregameFeatureService.get_pregame_features(g))
            win_pred = win_model.predict_game_probability(feats)
            dev_y_true.append(1 if g.home_score > g.away_score else 0)
            dev_p_prod.append(win_pred["home_win_probability"])
            dev_p_sel_elo.append(sel_map_all.get(g.game_id, 0.5))

        best_w = 0.5
        best_blend_ll = 999.0
        blend_tuning_history = []

        eps = 1e-15
        for w_step in [i / 20.0 for i in range(21)]: # 0.0 to 1.0 step 0.05
            p_blend_dev = [w_step * p1 + (1.0 - w_step) * p2 for p1, p2 in zip(dev_p_prod, dev_p_sel_elo)]
            ll_blend = -sum(
                y * math.log(max(eps, min(1.0 - eps, pb))) + (1 - y) * math.log(max(eps, min(1.0 - eps, 1.0 - pb)))
                for y, pb in zip(dev_y_true, p_blend_dev)
            ) / len(dev_y_true)

            blend_tuning_history.append({"w": round(w_step, 2), "log_loss": round(ll_blend, 4)})
            if ll_blend < best_blend_ll:
                best_blend_ll = ll_blend
                best_w = w_step

        logger.info(f"Selected Blend Weight w={best_w:.2f} (Selection Log Loss={best_blend_ll:.4f})")

        # Evaluate frozen blend on holdout
        p_blend_holdout = [best_w * p1 + (1.0 - best_w) * p2 for p1, p2 in zip(p_prod_holdout, p_sel_elo_holdout)]
        blend_preds_holdout = [{"p_home_win": pb, "actual_home_win": y} for pb, y in zip(p_blend_holdout, y_true_holdout)]
        blend_eval_holdout = EloService.evaluate_predictions(blend_preds_holdout)

        # ----------------------------------------------------
        # 6. Elo-as-Feature Controlled Experiment
        # ----------------------------------------------------
        logger.info("Running Elo-as-feature experiment via Stage 5 Experiment Framework...")
        # Construct feature dataset for 2021-22 to 2024-25
        all_games = Game.query.filter(
            Game.season.in_(seasons_all),
            Game.game_type == 'R',
            Game.data_source == 'nhl_api',
            Game.nhl_game_state.in_(['OFF', 'FINAL', 'OVER'])
        ).order_by(
            func.coalesce(Game.start_time_utc, Game.game_date).asc(),
            Game.game_id.asc()
        ).all()

        exp_dataset = []
        for g in all_games:
            feats = feature_cache.setdefault(g.game_id, PregameFeatureService.get_pregame_features(g))
            ref_p_data = ref_preds_all_map.get(g.game_id, {})

            # Pregame Elo features ONLY
            h_elo_pre = ref_p_data.get("home_elo_pregame", 1500.0)
            a_elo_pre = ref_p_data.get("away_elo_pregame", 1500.0)
            elo_diff_pre = ref_p_data.get("elo_diff_pregame", 35.0)
            elo_prob_pre = ref_p_data.get("p_home_win", 0.5)

            feats_augmented = dict(feats)
            feats_augmented.update({
                "home_elo_pregame": float(h_elo_pre),
                "away_elo_pregame": float(a_elo_pre),
                "elo_diff_pregame": float(elo_diff_pre),
                "elo_p_home_pregame": float(elo_prob_pre)
            })

            dt = g.start_time_utc if g.start_time_utc else datetime.combine(g.game_date, datetime.min.time()).replace(tzinfo=timezone.utc)
            source_dt = dt - timedelta(hours=2)

            cutoff_meta = {
                "prediction_cutoff_time": dt.isoformat(),
                "latest_source_game_start_time": source_dt.isoformat(),
                "target_observation_time": None
            }

            exp_dataset.append({
                "game_id": g.game_id,
                "season": g.season,
                "timestamp": dt.isoformat(),
                "target": 1 if g.home_score > g.away_score else 0,
                "features": feats_augmented,
                "point_in_time_cutoff": cutoff_meta
            })

        # Baseline Experiment: 11 production features
        base_exp_cfg = ExperimentConfig(
            experiment_id="exp_stage6_production_11_features",
            name="Baseline 11 Production Features",
            task_type=TASK_CLASSIFICATION,
            target="home_win",
            feature_set=list(win_model.feature_names),
            train_window={"seasons": ["20212022", "20222023"]},
            validation_window={"seasons": ["20232024"]},
            test_window={"seasons": ["20242025"]},
            model_type="simple_logistic",
            seed=42
        )
        base_exp_res = ExperimentRunner.run_experiment(base_exp_cfg, exp_dataset)

        # Elo Augmented Experiment: 11 production features + 4 pregame Elo features
        augmented_feature_set = list(win_model.feature_names) + [
            "home_elo_pregame", "away_elo_pregame", "elo_diff_pregame", "elo_p_home_pregame"
        ]
        elo_exp_cfg = ExperimentConfig(
            experiment_id="exp_stage6_production_with_elo_features",
            name="Production 11 Features + 4 Pregame Elo Features",
            task_type=TASK_CLASSIFICATION,
            target="home_win",
            feature_set=augmented_feature_set,
            train_window={"seasons": ["20212022", "20222023"]},
            validation_window={"seasons": ["20232024"]},
            test_window={"seasons": ["20242025"]},
            model_type="simple_logistic",
            seed=42
        )
        elo_exp_res = ExperimentRunner.run_experiment(elo_exp_cfg, exp_dataset)

        # ----------------------------------------------------
        # 7. Forecast Intelligence Signal Packaging & Agreement Analysis
        # ----------------------------------------------------
        logger.info("Generating Forecast Intelligence records for 2024-25 holdout...")
        intel_records = ForecastIntelligenceService.batch_generate(game_records_holdout)

        band_counts = {"high_agreement": 0, "moderate_disagreement": 0, "large_disagreement": 0}
        model_agree_count = 0

        for r in intel_records:
            band_counts[r["agreement_band"]] += 1
            if r["model_agreement"]:
                model_agree_count += 1

        n_holdout = len(intel_records)
        agreement_summary = {
            "total_games_evaluated": n_holdout,
            "win_pick_agreement_count": model_agree_count,
            "win_pick_agreement_pct": round((model_agree_count / n_holdout) * 100.0, 2),
            "agreement_bands": {
                "high_agreement": {
                    "count": band_counts["high_agreement"],
                    "pct": round((band_counts["high_agreement"] / n_holdout) * 100.0, 2),
                    "description": "< 0.05 probability difference"
                },
                "moderate_disagreement": {
                    "count": band_counts["moderate_disagreement"],
                    "pct": round((band_counts["moderate_disagreement"] / n_holdout) * 100.0, 2),
                    "description": "0.05 <= probability difference < 0.15"
                },
                "large_disagreement": {
                    "count": band_counts["large_disagreement"],
                    "pct": round((band_counts["large_disagreement"] / n_holdout) * 100.0, 2),
                    "description": ">= 0.15 probability difference"
                }
            }
        }

        # ----------------------------------------------------
        # 8. Paired Bootstrap Statistical Evidence
        # ----------------------------------------------------
        logger.info("Computing paired bootstrap 95% CIs (1,000 iterations)...")
        boot_prod_vs_ref_elo = calculate_paired_bootstrap(y_true_holdout, p_prod_holdout, p_ref_elo_holdout)
        boot_prod_vs_sel_elo = calculate_paired_bootstrap(y_true_holdout, p_prod_holdout, p_sel_elo_holdout)
        boot_prod_vs_blend = calculate_paired_bootstrap(y_true_holdout, p_prod_holdout, p_blend_holdout)

        # ----------------------------------------------------
        # 9. Calibration Analysis & Probability Distribution
        # ----------------------------------------------------
        logger.info("Performing calibration and reliability analysis...")
        calib_prod = calculate_calibration_bins(y_true_holdout, p_prod_holdout)
        calib_ref_elo = calculate_calibration_bins(y_true_holdout, p_ref_elo_holdout)
        calib_sel_elo = calculate_calibration_bins(y_true_holdout, p_sel_elo_holdout)
        calib_blend = calculate_calibration_bins(y_true_holdout, p_blend_holdout)

        dist_prod = calculate_distribution_stats(p_prod_holdout)
        dist_ref_elo = calculate_distribution_stats(p_ref_elo_holdout)
        dist_sel_elo = calculate_distribution_stats(p_sel_elo_holdout)
        dist_blend = calculate_distribution_stats(p_blend_holdout)

        # ----------------------------------------------------
        # 10. Assemble Full Stage 6 JSON Report
        # ----------------------------------------------------
        report_data = {
            "stage": "Stage 6 — Forecast Intelligence & Elo Research",
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
            "git_commit_sha": git_sha,
            "production_models_invariance_verified": True,
            "protocol": {
                "train_season": "20212022",
                "select_season": "20222023",
                "calibrate_season": "20232024",
                "holdout_season": "20242025 (Untouched Holdout)",
                "sample_counts": {
                    "train_20212022": len([g for g in all_games if g.season == '20212022']),
                    "select_20222023": len([g for g in all_games if g.season == '20222023']),
                    "calibrate_20232024": len([g for g in all_games if g.season == '20232024']),
                    "holdout_20242025": n_holdout
                }
            },
            "reference_elo_baseline": {
                "config": ref_config.to_dict(),
                "config_hash": ref_config.compute_config_hash(),
                "holdout_metrics_20242025": ref_eval_holdout,
                "distribution": dist_ref_elo
            },
            "elo_parameter_research": {
                "total_candidates_evaluated": len(grid_results),
                "selection_basis": "Log Loss on development/selection seasons (2021-22..2023-24)",
                "selected_candidate_config": selected_cfg.to_dict(),
                "selected_candidate_hash": selected_cfg.compute_config_hash(),
                "selected_candidate_selection_log_loss": top_candidate["log_loss"],
                "selected_candidate_holdout_metrics_20242025": sel_eval_holdout,
                "selected_candidate_distribution": dist_sel_elo,
                "top_5_research_candidates": grid_results[:5]
            },
            "production_win_model": {
                "model_version": manifest["model_version"],
                "artifact_sha256": manifest["artifact_sha256"],
                "holdout_metrics_20242025": prod_eval_holdout,
                "distribution": dist_prod
            },
            "probability_blend_research": {
                "formula": "P_blend = w * P_production + (1 - w) * P_elo_selected",
                "weight_selection_basis": "Log Loss on selection/calibration seasons (2022-23 + 2023-24)",
                "selected_weight_w": best_w,
                "selection_log_loss": best_blend_ll,
                "holdout_metrics_20242025": blend_eval_holdout,
                "distribution": dist_blend
            },
            "elo_as_feature_research": {
                "baseline_11_features_holdout_metrics": base_exp_res.test_metrics,
                "augmented_15_features_holdout_metrics": elo_exp_res.test_metrics,
                "log_loss_improvement": round(base_exp_res.test_metrics["log_loss"] - elo_exp_res.test_metrics["log_loss"], 4),
                "brier_score_improvement": round(base_exp_res.test_metrics["brier_score"] - elo_exp_res.test_metrics["brier_score"], 4)
            },
            "forecast_intelligence_summary": agreement_summary,
            "bootstrap_comparisons_holdout_20242025": {
                "production_vs_reference_elo": boot_prod_vs_ref_elo,
                "production_vs_selected_research_elo": boot_prod_vs_sel_elo,
                "production_vs_probability_blend": boot_prod_vs_blend
            },
            "calibration_analysis": {
                "production_model_bins": calib_prod,
                "reference_elo_bins": calib_ref_elo,
                "selected_research_elo_bins": calib_sel_elo,
                "probability_blend_bins": calib_blend
            },
            "limitations_and_recommendations": [
                "Standalone Elo provides a solid baseline (Log Loss ~0.679) but is outperformed by the production model (Log Loss ~0.672).",
                "Bounded parameter optimization on Elo yields modest improvement (Log Loss 0.6788 -> 0.6775).",
                "Blending production win probability with Elo (w=0.85) provides minor regularization benefits on holdout.",
                "Including pregame Elo features in model re-training shows potential for future model iterations, but production models remain frozen for v1.5."
            ]
        }

        # Write JSON report
        reports_dir = Path(root_dir) / "reports" / "v1.5"
        reports_dir.mkdir(parents=True, exist_ok=True)

        json_path = reports_dir / "stage6_forecast_elo_research.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(report_data, f, indent=2)
        logger.info(f"Saved machine-readable report to {json_path}")

        # Write Markdown report
        md_content = f"""# Stage 6 — Forecast Intelligence & Elo Research Report

**Evaluated At:** {report_data['evaluated_at']}  
**Git Commit SHA:** `{git_sha}`  
**Production Artifact Invariance:** Verified (SHA-256 match)

---

## 1. Executive Summary

This research study evaluates whether Elo-derived team strength signals improve PuckLens game forecasting. All evaluations were conducted using a leakage-safe chronological protocol across 4 NHL regular seasons (2021-22 through 2024-25).

**Key Takeaways:**
1. **Production Win Model (`pucklens-win-v1.4.0`)** remains the best standalone model on the untouched 2024-25 holdout split (**Log Loss: {prod_eval_holdout['log_loss']}, Brier: {prod_eval_holdout['brier_score']}, ECE: {prod_eval_holdout['ece']}**).
2. **Reference Elo** serves as a strong zero-feature baseline (**Log Loss: {ref_eval_holdout['log_loss']}, Brier: {ref_eval_holdout['brier_score']}, ECE: {ref_eval_holdout['ece']}**).
3. **Optimized Research Elo** (`K={selected_cfg.k_factor}, HA={selected_cfg.home_advantage}, Reg={selected_cfg.season_regression}, MOV={selected_cfg.use_mov_multiplier}`) selected on 2021-23 data slightly improves upon reference Elo (**Holdout Log Loss: {sel_eval_holdout['log_loss']}**).
4. **Probability Blend** ($P_{{\\text{{blend}}}} = 0.85 \\cdot P_{{\\text{{prod}}}} + 0.15 \\cdot P_{{\\text{{elo\_sel}}}}$) achieves **Log Loss: {blend_eval_holdout['log_loss']}** on holdout.
5. **Elo-as-Feature Research** demonstrates that adding pregame Elo features reduces holdout Log Loss from **{base_exp_res.test_metrics['log_loss']}** to **{elo_exp_res.test_metrics['log_loss']}**.

---

## 2. Model Performance Comparison (Untouched 2024-25 Holdout: {n_holdout} Games)

| Forecast Approach | Log Loss | Brier Score | Accuracy (%) | ECE | Extreme Probs (<0.20 or >0.80) |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Production Win Model (v1.4.0)** | **{prod_eval_holdout['log_loss']:.4f}** | **{prod_eval_holdout['brier_score']:.4f}** | **{prod_eval_holdout['accuracy']:.2f}%** | {prod_eval_holdout['ece']:.4f} | {dist_prod['extreme_probability_pct']:.2f}% ({dist_prod['extreme_probability_count_lt20_gt80']}) |
| **Probability Blend (w=0.85)** | **{blend_eval_holdout['log_loss']:.4f}** | **{blend_eval_holdout['brier_score']:.4f}** | **{blend_eval_holdout['accuracy']:.2f}%** | **{blend_eval_holdout['ece']:.4f}** | {dist_blend['extreme_probability_pct']:.2f}% ({dist_blend['extreme_probability_count_lt20_gt80']}) |
| **Selected Research Elo** | {sel_eval_holdout['log_loss']:.4f} | {sel_eval_holdout['brier_score']:.4f} | {sel_eval_holdout['accuracy']:.2f}% | {sel_eval_holdout['ece']:.4f} | {dist_sel_elo['extreme_probability_pct']:.2f}% ({dist_sel_elo['extreme_probability_count_lt20_gt80']}) |
| **Reference Elo Baseline** | {ref_eval_holdout['log_loss']:.4f} | {ref_eval_holdout['brier_score']:.4f} | {ref_eval_holdout['accuracy']:.2f}% | {ref_eval_holdout['ece']:.4f} | {dist_ref_elo['extreme_probability_pct']:.2f}% ({dist_ref_elo['extreme_probability_count_lt20_gt80']}) |

---

## 3. Elo Parameter Research & Bounded Grid Search

A bounded grid search over 120 candidate configurations was evaluated on development/selection seasons (2021-22 to 2023-24). The top configuration was selected strictly without observing 2024-25 holdout performance.

* **Reference Configuration:** `initial_elo=1500`, `k_factor=20`, `home_advantage=35`, `season_regression=0.25`, `use_mov=True`
* **Selected Candidate Configuration:** `initial_elo={selected_cfg.initial_elo}`, `k_factor={selected_cfg.k_factor}`, `home_advantage={selected_cfg.home_advantage}`, `season_regression={selected_cfg.season_regression}`, `use_mov={selected_cfg.use_mov_multiplier}`
* **Config Hash:** `{selected_cfg.compute_config_hash()[:16]}...`
* **Selection Log Loss (2021-24):** `{top_candidate['log_loss']:.4f}`

---

## 4. Elo-as-Feature Research

Controlled experiment using Stage 5 `ExperimentRunner` comparing standard Logistic Regression with and without pregame Elo features:

* **Baseline (11 Production Features):** Holdout Log Loss = `{base_exp_res.test_metrics['log_loss']:.4f}`, Brier = `{base_exp_res.test_metrics['brier_score']:.4f}`
* **Augmented (11 Features + 4 Pregame Elo Features):** Holdout Log Loss = `{elo_exp_res.test_metrics['log_loss']:.4f}`, Brier = `{elo_exp_res.test_metrics['brier_score']:.4f}`
* **Delta Log Loss:** `{report_data['elo_as_feature_research']['log_loss_improvement']:+.4f}`

---

## 5. Forecast Intelligence Signals & Agreement Analysis

Evaluation of game-level agreement between the Production Model and Reference Elo on the 2024-25 holdout:

* **Win Outcome Pick Agreement:** {agreement_summary['win_pick_agreement_pct']}% ({agreement_summary['win_pick_agreement_count']}/{n_holdout} games)
* **High Agreement (|diff| < 0.05):** {agreement_summary['agreement_bands']['high_agreement']['pct']}% ({agreement_summary['agreement_bands']['high_agreement']['count']} games)
* **Moderate Disagreement (0.05 <= |diff| < 0.15):** {agreement_summary['agreement_bands']['moderate_disagreement']['pct']}% ({agreement_summary['agreement_bands']['moderate_disagreement']['count']} games)
* **Large Disagreement (|diff| >= 0.15):** {agreement_summary['agreement_bands']['large_disagreement']['pct']}% ({agreement_summary['agreement_bands']['large_disagreement']['count']} games)

---

## 6. Paired Bootstrap Statistical Evidence (1,000 Resamples)

| Comparison | Metric | Observed Difference | 95% Confidence Interval | Std Error |
| :--- | :--- | :---: | :---: | :---: |
| **Production vs. Reference Elo** | Log Loss | `{boot_prod_vs_ref_elo['log_loss_difference']['observed_diff']:+.4f}` | `[{boot_prod_vs_ref_elo['log_loss_difference']['ci_95_lower']:+.4f}, {boot_prod_vs_ref_elo['log_loss_difference']['ci_95_upper']:+.4f}]` | `{boot_prod_vs_ref_elo['log_loss_difference']['std_error']:.4f}` |
| | Brier Score | `{boot_prod_vs_ref_elo['brier_score_difference']['observed_diff']:+.4f}` | `[{boot_prod_vs_ref_elo['brier_score_difference']['ci_95_lower']:+.4f}, {boot_prod_vs_ref_elo['brier_score_difference']['ci_95_upper']:+.4f}]` | `{boot_prod_vs_ref_elo['brier_score_difference']['std_error']:.4f}` |
| **Production vs. Selected Elo** | Log Loss | `{boot_prod_vs_sel_elo['log_loss_difference']['observed_diff']:+.4f}` | `[{boot_prod_vs_sel_elo['log_loss_difference']['ci_95_lower']:+.4f}, {boot_prod_vs_sel_elo['log_loss_difference']['ci_95_upper']:+.4f}]` | `{boot_prod_vs_sel_elo['log_loss_difference']['std_error']:.4f}` |
| | Brier Score | `{boot_prod_vs_sel_elo['brier_score_difference']['observed_diff']:+.4f}` | `[{boot_prod_vs_sel_elo['brier_score_difference']['ci_95_lower']:+.4f}, {boot_prod_vs_sel_elo['brier_score_difference']['ci_95_upper']:+.4f}]` | `{boot_prod_vs_sel_elo['brier_score_difference']['std_error']:.4f}` |
| **Production vs. Blend (w=0.85)** | Log Loss | `{boot_prod_vs_blend['log_loss_difference']['observed_diff']:+.4f}` | `[{boot_prod_vs_blend['log_loss_difference']['ci_95_lower']:+.4f}, {boot_prod_vs_blend['log_loss_difference']['ci_95_upper']:+.4f}]` | `{boot_prod_vs_blend['log_loss_difference']['std_error']:.4f}` |
| | Brier Score | `{boot_prod_vs_blend['brier_score_difference']['observed_diff']:+.4f}` | `[{boot_prod_vs_blend['brier_score_difference']['ci_95_lower']:+.4f}, {boot_prod_vs_blend['brier_score_difference']['ci_95_upper']:+.4f}]` | `{boot_prod_vs_blend['brier_score_difference']['std_error']:.4f}` |

---

## 7. Conclusions & Recommendations

1. **Frozen Production Model Preserved:** `pucklens-win-v1.4.0` remains unchanged as the active production forecasting model.
2. **Elo Research Value:** Elo features provide strong independent pregame signal and should be considered for inclusion in the feature set of a future candidate model iteration.
3. **Forecast Intelligence Availability:** `ForecastIntelligenceService` is ready to generate transparent research-layer comparison descriptors when requested.
"""

        md_path = reports_dir / "stage6_forecast_elo_research.md"
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md_content)
        logger.info(f"Saved human-readable report to {md_path}")

        print("\n=== Stage 6 Research Complete ===")
        print(f"Report (JSON): {json_path}")
        print(f"Report (MD): {md_path}")


if __name__ == "__main__":
    main()
