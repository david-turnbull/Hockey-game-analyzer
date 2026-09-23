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
from datetime import datetime, timezone
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
from app.analytics.experiments.point_in_time import (
    PointInTimeAdapter,
    PointInTimeCutoff,
    TemporalLeakageError,
    assert_point_in_time_safety
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


def validate_paired_game_populations(
    games: List[Any],
    prod_preds: List[float],
    ref_preds: List[float],
    sel_preds: List[float],
    blend_preds: Optional[List[float]] = None
) -> Dict[str, Any]:
    """
    Asserts exact game population matching across all evaluated models.
    Fails closed if sample counts mismatch, game IDs are duplicated, or any prediction is missing/None.
    """
    n = len(games)
    if len(prod_preds) != n or len(ref_preds) != n or len(sel_preds) != n:
        raise ValueError(
            f"POPULATION_MISMATCH: Game count ({n}) does not match prediction lengths: "
            f"prod={len(prod_preds)}, ref={len(ref_preds)}, sel={len(sel_preds)}"
        )
    if blend_preds is not None and len(blend_preds) != n:
        raise ValueError(
            f"POPULATION_MISMATCH: Blend prediction count ({len(blend_preds)}) != game count ({n})"
        )

    game_ids = [g.game_id if hasattr(g, "game_id") else g["game_id"] for g in games]
    if len(set(game_ids)) != n:
        raise ValueError(f"DUPLICATE_GAME_IDS: Found duplicate game IDs in population of size {n}")

    for idx, (gid, p1, p2, p3) in enumerate(zip(game_ids, prod_preds, ref_preds, sel_preds)):
        if p1 is None or p2 is None or p3 is None:
            raise ValueError(f"MISSING_PREDICTION: Missing prediction at index {idx} (game_id={gid})")
        if math.isnan(p1) or math.isnan(p2) or math.isnan(p3):
            raise ValueError(f"INVALID_PREDICTION_VALUE: NaN prediction at index {idx} (game_id={gid})")

    return {
        "sample_count": n,
        "unique_game_ids_count": len(set(game_ids)),
        "population_valid": True
    }


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
    Computes paired bootstrap 95% CIs for metric differences (comparator - base).

    SIGN SEMANTICS (comparator_minus_base_diff):
    - Negative (< 0): Comparator model achieved LOWER (better) Log Loss / Brier Score than base model.
    - Positive (> 0): Base model (production) achieved LOWER (better) Log Loss / Brier Score than comparator model.
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
            "comparator_minus_base_diff": round(obs_ll_c - obs_ll_b, 4),
            "sign_interpretation": "Negative indicates comparator model achieved lower (better) Log Loss than base model",
            "base_log_loss": round(obs_ll_b, 4),
            "comp_log_loss": round(obs_ll_c, 4),
            "ci_95_lower": round(float(np.percentile(diff_ll_list, 2.5)), 4),
            "ci_95_upper": round(float(np.percentile(diff_ll_list, 97.5)), 4),
            "std_error": round(float(np.std(diff_ll_list)), 4)
        },
        "brier_score_difference": {
            "comparator_minus_base_diff": round(obs_brier_c - obs_brier_b, 4),
            "sign_interpretation": "Negative indicates comparator model achieved lower (better) Brier Score than base model",
            "base_brier_score": round(obs_brier_b, 4),
            "comp_brier_score": round(obs_brier_c, 4),
            "ci_95_lower": round(float(np.percentile(diff_brier_list, 2.5)), 4),
            "ci_95_upper": round(float(np.percentile(diff_brier_list, 97.5)), 4),
            "std_error": round(float(np.std(diff_brier_list)), 4)
        }
    }


def generate_dynamic_narrative_conclusions(
    prod_eval: Dict[str, float],
    ref_eval: Dict[str, float],
    sel_eval: Dict[str, float],
    blend_eval: Dict[str, float],
    boot_sel: Dict[str, Any],
    boot_blend: Dict[str, Any],
    base_val_ll: float,
    elo_val_ll: float,
    base_test_ll: float,
    elo_test_ll: float
) -> List[str]:
    """Generates narrative conclusions strictly derived from empirical calculated metrics."""
    conclusions = []

    models = [
        ("Production Win Model (v1.4.0)", prod_eval["log_loss"]),
        ("Reference Elo Baseline", ref_eval["log_loss"]),
        ("Selected Research Elo", sel_eval["log_loss"]),
        ("Probability Blend", blend_eval["log_loss"])
    ]
    models.sort(key=lambda m: m[1])
    best_model_name, best_ll = models[0]

    conclusions.append(
        f"On the untouched 2024-25 holdout split, the observed lowest Log Loss model was {best_model_name} "
        f"(Log Loss: {best_ll:.4f})."
    )

    diff_sel = boot_sel["log_loss_difference"]
    ci_sel_low = diff_sel["ci_95_lower"]
    ci_sel_up = diff_sel["ci_95_upper"]
    sel_ci_excludes_zero = (ci_sel_low < 0 and ci_sel_up < 0) or (ci_sel_low > 0 and ci_sel_up > 0)

    if diff_sel["comparator_minus_base_diff"] < 0:
        if sel_ci_excludes_zero:
            conclusions.append(
                f"On this holdout, Selected Research Elo produced lower Log Loss ({sel_eval['log_loss']:.4f}) than the frozen "
                f"production model ({prod_eval['log_loss']:.4f}); the paired bootstrap CI for the difference [{ci_sel_low:+.4f}, {ci_sel_up:+.4f}] "
                f"did not include zero."
            )
        else:
            conclusions.append(
                f"Selected Research Elo produced lower Log Loss ({sel_eval['log_loss']:.4f}) than the production model "
                f"({prod_eval['log_loss']:.4f}) on the 2024-25 holdout, but the paired bootstrap 95% CI [{ci_sel_low:+.4f}, {ci_sel_up:+.4f}] "
                f"includes zero, indicating statistical uncertainty."
            )
    else:
        conclusions.append(
            f"The frozen production model produced lower or equal Log Loss ({prod_eval['log_loss']:.4f}) compared to Selected Research Elo "
            f"({sel_eval['log_loss']:.4f}) on the 2024-25 holdout."
        )

    val_delta = base_val_ll - elo_val_ll
    test_delta = base_test_ll - elo_test_ll
    if val_delta > 0:
        conclusions.append(
            f"Elo-as-feature augmentation improved Log Loss on the frozen 2023-24 research-validation season "
            f"(Validation Delta: {val_delta:+.4f}, Baseline Log Loss: {base_val_ll:.4f} -> Elo-Augmented: {elo_val_ll:.4f}). "
            f"On the untouched 2024-25 holdout, the delta was {test_delta:+.4f} (Baseline: {base_test_ll:.4f} -> Elo-Augmented: {elo_test_ll:.4f})."
        )
    else:
        conclusions.append(
            f"Elo-as-feature augmentation did not show validation improvement on 2023-24 (Validation Delta: {val_delta:+.4f}). "
            f"Holdout delta on 2024-25 was {test_delta:+.4f}."
        )

    conclusions.append(
        "All production models and artifacts remain strictly frozen (v1.4.0). Research Elo and Forecast Intelligence outputs remain "
        "in the research layer only."
    )

    return conclusions


def main():
    logger.info("Initializing Stage 6 Forecast Intelligence & Elo Research...")
    app = create_app()

    with app.app_context():
        # 1. Verify production artifact invariance
        verify_production_artifact_invariance()

        # Audit Git SHA
        try:
            git_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        except Exception:
            git_sha = "unknown"

        execution_time = datetime.now(timezone.utc).isoformat()

        # Preload pregame event statistics
        logger.info("Preloading pregame event stats into memory...")
        PregameFeatureService.preload_all_stats()

        # ----------------------------------------------------
        # 2. Reference Elo Baseline Evaluation
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
        ).all()

        # Deterministic chronological sorting of all games
        all_games = EloResearchEngine.sort_games_chronologically(all_games)

        logger.info(f"Loaded {len(all_games)} games across 4 regular seasons.")

        ref_elo_res = EloResearchEngine.run_elo_backtest(seasons_all, ref_config, games_override=all_games)
        ref_preds_all_map = {p["game_id"]: p for p in ref_elo_res["predictions"]}

        ref_preds_val = [p for p in ref_elo_res["predictions"] if p["season"] == '20232024']
        ref_eval_val = EloResearchEngine.evaluate_predictions(ref_preds_val)

        ref_preds_holdout = [p for p in ref_elo_res["predictions"] if p["season"] == '20242025']
        ref_eval_holdout = EloResearchEngine.evaluate_predictions(ref_preds_holdout)

        # ----------------------------------------------------
        # 3. Elo Parameter Research & Protocol Separation
        # Protocol:
        # Development / State Init: 2021-22
        # Parameter Selection: 2022-23 ONLY (evaluate on 2022-23 using state generated from prior games)
        # Frozen Validation: 2023-24
        # Untouched Holdout: 2024-25
        # ----------------------------------------------------
        logger.info("Running bounded Elo parameter research (Selection Season: 2022-23 ONLY)...")
        grid_results = run_elo_parameter_grid_search(
            seasons=['20212022', '20222023'],
            k_factors=[10.0, 15.0, 20.0, 25.0, 30.0],
            home_advantages=[20.0, 35.0, 50.0, 65.0],
            season_regressions=[0.10, 0.25, 0.40],
            use_mov_options=[True, False],
            games_override=all_games,
            selection_season='20222023'
        )

        top_candidate = grid_results[0]
        selected_cfg = EloResearchConfig(**top_candidate["config"])

        logger.info(
            f"Selected Research Elo Config (Selection Season 2022-23 Log Loss={top_candidate['log_loss']:.4f}): "
            f"{selected_cfg.to_dict()}"
        )

        # ----------------------------------------------------
        # 4. Evaluate Selected Research Elo across all windows
        # ----------------------------------------------------
        sel_elo_res = EloResearchEngine.run_elo_backtest(seasons_all, selected_cfg, games_override=all_games)
        sel_preds_all_map = {p["game_id"]: p for p in sel_elo_res["predictions"]}

        sel_preds_val = [p for p in sel_elo_res["predictions"] if p["season"] == '20232024']
        sel_eval_val = EloResearchEngine.evaluate_predictions(sel_preds_val)

        sel_preds_holdout = [p for p in sel_elo_res["predictions"] if p["season"] == '20242025']
        sel_eval_holdout = EloResearchEngine.evaluate_predictions(sel_preds_holdout)

        # ----------------------------------------------------
        # 5. Evaluate Frozen Production Win Probability Model (pucklens-win-v1.4.0)
        # ----------------------------------------------------
        logger.info("Evaluating frozen production win probability model across seasons...")
        win_model, manifest = ForecastModelRegistry.load_active_model()

        # Build game populations per season
        games_by_season = {
            s: [g for g in all_games if g.season == s]
            for s in seasons_all
        }

        feature_cache = {}

        prod_preds_by_season = {}
        y_true_by_season = {}
        p_prod_by_season = {}
        p_ref_elo_by_season = {}
        p_sel_elo_by_season = {}
        prod_eval_by_season = {}

        for s in ['20222023', '20232024', '20242025']:
            s_games = games_by_season[s]
            s_prod_preds = []
            s_y_true = []
            s_p_prod = []
            s_p_ref_elo = []
            s_p_sel_elo = []

            for g in s_games:
                if g.game_id not in ref_preds_all_map:
                    raise ValueError(f"FAIL_CLOSED: Missing Reference Elo prediction for game_id={g.game_id}")
                if g.game_id not in sel_preds_all_map:
                    raise ValueError(f"FAIL_CLOSED: Missing Selected Elo prediction for game_id={g.game_id}")

                feats = feature_cache.setdefault(g.game_id, PregameFeatureService.get_pregame_features(g))
                win_pred = win_model.predict_game_probability(feats)
                p_prod = win_pred["home_win_probability"]

                p_ref = ref_preds_all_map[g.game_id]["p_home_win"]
                p_sel = sel_preds_all_map[g.game_id]["p_home_win"]
                actual = 1 if g.home_score > g.away_score else 0

                s_y_true.append(actual)
                s_p_prod.append(p_prod)
                s_p_ref_elo.append(p_ref)
                s_p_sel_elo.append(p_sel)

                s_prod_preds.append({
                    "game_id": g.game_id,
                    "p_home_win": p_prod,
                    "actual_home_win": actual
                })

            # Assert exact population integrity (Fail Closed)
            validate_paired_game_populations(s_games, s_p_prod, s_p_ref_elo, s_p_sel_elo)

            prod_preds_by_season[s] = s_prod_preds
            y_true_by_season[s] = s_y_true
            p_prod_by_season[s] = s_p_prod
            p_ref_elo_by_season[s] = s_p_ref_elo
            p_sel_elo_by_season[s] = s_p_sel_elo
            prod_eval_by_season[s] = EloService.evaluate_predictions(s_prod_preds)

        prod_eval_val = prod_eval_by_season['20232024']
        prod_eval_holdout = prod_eval_by_season['20242025']

        # ----------------------------------------------------
        # 6. Probability Blend Research Protocol
        # Protocol:
        # Select blend weight w on Selection Season (2022-23) ONLY.
        # Freeze w*. Evaluate on 2023-24 (Validation) and 2024-25 (Holdout).
        # ----------------------------------------------------
        logger.info("Selecting probability blend weight w on Selection Season (2022-23 ONLY)...")
        sel_y_true = y_true_by_season['20222023']
        sel_p_prod = p_prod_by_season['20222023']
        sel_p_sel_elo = p_sel_elo_by_season['20222023']

        best_w = 0.5
        best_blend_ll_sel = 999.0
        blend_tuning_history = []

        eps = 1e-15
        for w_step in [i / 20.0 for i in range(21)]:  # 0.0 to 1.0 step 0.05
            p_blend_sel = [w_step * p1 + (1.0 - w_step) * p2 for p1, p2 in zip(sel_p_prod, sel_p_sel_elo)]
            ll_blend = -sum(
                y * math.log(max(eps, min(1.0 - eps, pb))) + (1 - y) * math.log(max(eps, min(1.0 - eps, 1.0 - pb)))
                for y, pb in zip(sel_y_true, p_blend_sel)
            ) / len(sel_y_true)

            blend_tuning_history.append({"w": round(w_step, 2), "log_loss": round(ll_blend, 4)})
            if ll_blend < best_blend_ll_sel:
                best_blend_ll_sel = ll_blend
                best_w = w_step

        logger.info(f"Selected Frozen Blend Weight w={best_w:.2f} (Selection 2022-23 Log Loss={best_blend_ll_sel:.4f})")

        # Evaluate frozen blend weight on Validation (2023-24)
        val_p_blend = [best_w * p1 + (1.0 - best_w) * p2 for p1, p2 in zip(p_prod_by_season['20232024'], p_sel_elo_by_season['20232024'])]
        blend_preds_val = [{"p_home_win": pb, "actual_home_win": y} for pb, y in zip(val_p_blend, y_true_by_season['20232024'])]
        blend_eval_val = EloService.evaluate_predictions(blend_preds_val)

        # Evaluate frozen blend weight on Holdout (2024-25)
        holdout_p_blend = [best_w * p1 + (1.0 - best_w) * p2 for p1, p2 in zip(p_prod_by_season['20242025'], p_sel_elo_by_season['20242025'])]
        blend_preds_holdout = [{"p_home_win": pb, "actual_home_win": y} for pb, y in zip(holdout_p_blend, y_true_by_season['20242025'])]
        blend_eval_holdout = EloService.evaluate_predictions(blend_preds_holdout)

        # ----------------------------------------------------
        # 7. Elo-as-Feature Controlled Experiment (Point-in-Time Provenance)
        # ----------------------------------------------------
        logger.info("Running Elo-as-feature experiment via PointInTimeAdapter...")
        exp_dataset = []
        excluded_provenance_count = 0

        for g in all_games:
            try:
                feats, cutoff = PointInTimeAdapter.extract_game_features_with_cutoff(g)
            except TemporalLeakageError as exc:
                excluded_provenance_count += 1
                logger.warning(f"Excluding game {g.game_id} from Elo-as-feature dataset due to provenance: {exc}")
                continue

            ref_p_data = ref_preds_all_map.get(g.game_id, {})
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

            target_val = 1 if g.home_score > g.away_score else 0

            exp_dataset.append({
                "game_id": g.game_id,
                "season": g.season,
                "timestamp": cutoff.prediction_cutoff_time.isoformat(),
                "target": target_val,
                "features": feats_augmented,
                "point_in_time_cutoff": cutoff.to_dict()
            })

        logger.info(f"Auditing temporal provenance safety for {len(exp_dataset)} dataset records...")
        assert_point_in_time_safety(exp_dataset)

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
        # 8. Forecast Intelligence Signal Packaging & Agreement Analysis
        # ----------------------------------------------------
        logger.info("Generating Forecast Intelligence records for 2024-25 holdout...")
        holdout_games = games_by_season['20242025']
        game_records_holdout = []

        for g in holdout_games:
            feats = feature_cache.setdefault(g.game_id, PregameFeatureService.get_pregame_features(g))
            win_pred = win_model.predict_game_probability(feats)
            p_prod = win_pred["home_win_probability"]
            p_ref = ref_preds_all_map[g.game_id]["p_home_win"]
            actual = 1 if g.home_score > g.away_score else 0

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
        # 9. Paired Bootstrap Statistical Evidence (Holdout 2024-25)
        # ----------------------------------------------------
        logger.info("Computing paired bootstrap 95% CIs (1,000 iterations)...")
        y_true_holdout = y_true_by_season['20242025']
        p_prod_holdout = p_prod_by_season['20242025']
        p_ref_elo_holdout = p_ref_elo_by_season['20242025']
        p_sel_elo_holdout = p_sel_elo_by_season['20242025']

        boot_prod_vs_ref_elo = calculate_paired_bootstrap(y_true_holdout, p_prod_holdout, p_ref_elo_holdout)
        boot_prod_vs_sel_elo = calculate_paired_bootstrap(y_true_holdout, p_prod_holdout, p_sel_elo_holdout)
        boot_prod_vs_blend = calculate_paired_bootstrap(y_true_holdout, p_prod_holdout, holdout_p_blend)

        # ----------------------------------------------------
        # 10. Calibration Analysis & Probability Distribution
        # ----------------------------------------------------
        logger.info("Performing calibration and reliability analysis...")
        calib_prod_holdout = calculate_calibration_bins(y_true_holdout, p_prod_holdout)
        calib_ref_elo_holdout = calculate_calibration_bins(y_true_holdout, p_ref_elo_holdout)
        calib_sel_elo_holdout = calculate_calibration_bins(y_true_holdout, p_sel_elo_holdout)
        calib_blend_holdout = calculate_calibration_bins(y_true_holdout, holdout_p_blend)

        dist_prod_holdout = calculate_distribution_stats(p_prod_holdout)
        dist_ref_elo_holdout = calculate_distribution_stats(p_ref_elo_holdout)
        dist_sel_elo_holdout = calculate_distribution_stats(p_sel_elo_holdout)
        dist_blend_holdout = calculate_distribution_stats(holdout_p_blend)

        # ----------------------------------------------------
        # 11. Generate Dynamic Narrative Conclusions
        # ----------------------------------------------------
        narrative_conclusions = generate_dynamic_narrative_conclusions(
            prod_eval=prod_eval_holdout,
            ref_eval=ref_eval_holdout,
            sel_eval=sel_eval_holdout,
            blend_eval=blend_eval_holdout,
            boot_sel=boot_prod_vs_sel_elo,
            boot_blend=boot_prod_vs_blend,
            base_val_ll=base_exp_res.metrics["log_loss"],
            elo_val_ll=elo_exp_res.metrics["log_loss"],
            base_test_ll=base_exp_res.test_metrics["log_loss"],
            elo_test_ll=elo_exp_res.test_metrics["log_loss"]
        )

        # ----------------------------------------------------
        # 12. Assemble Full Stage 6 JSON Report
        # ----------------------------------------------------
        report_data = {
            "stage": "Stage 6 — Forecast Intelligence & Elo Research",
            "evaluated_at": execution_time,
            "research_execution_git_sha": git_sha,
            "production_models_invariance_verified": True,
            "protocol": {
                "development_season": "20212022 (State Initialization)",
                "selection_season": "20222023 (Parameter & Blend Weight Selection)",
                "validation_season": "20232024 (Frozen Research Validation)",
                "holdout_season": "20242025 (Untouched Holdout)",
                "sample_counts": {
                    "development_20212022": len(games_by_season['20212022']),
                    "selection_20222023": len(games_by_season['20222023']),
                    "validation_20232024": len(games_by_season['20232024']),
                    "holdout_20242025": len(games_by_season['20242025'])
                }
            },
            "reference_elo_baseline": {
                "config": ref_config.to_dict(),
                "config_hash": ref_config.compute_config_hash(),
                "validation_metrics_20232024": ref_eval_val,
                "holdout_metrics_20242025": ref_eval_holdout,
                "holdout_distribution": dist_ref_elo_holdout
            },
            "elo_parameter_research": {
                "total_candidates_evaluated": len(grid_results),
                "selection_protocol": "Rank candidates by Log Loss on 2022-23 ONLY (using state initialized from 2021-22)",
                "selected_candidate_config": selected_cfg.to_dict(),
                "selected_candidate_hash": selected_cfg.compute_config_hash(),
                "selection_season_log_loss_20222023": top_candidate["log_loss"],
                "validation_metrics_20232024": sel_eval_val,
                "holdout_metrics_20242025": sel_eval_holdout,
                "holdout_distribution": dist_sel_elo_holdout,
                "top_5_research_candidates": grid_results[:5]
            },
            "production_win_model": {
                "model_version": manifest["model_version"],
                "artifact_sha256": manifest["artifact_sha256"],
                "validation_metrics_20232024": prod_eval_val,
                "holdout_metrics_20242025": prod_eval_holdout,
                "holdout_distribution": dist_prod_holdout
            },
            "probability_blend_research": {
                "formula": "P_blend = w * P_production + (1 - w) * P_elo_selected",
                "weight_selection_protocol": "Select w by Log Loss minimization on Selection Season 2022-23 ONLY",
                "selected_weight_w": best_w,
                "selection_season_log_loss_20222023": best_blend_ll_sel,
                "weight_tuning_history": blend_tuning_history,
                "validation_metrics_20232024": blend_eval_val,
                "holdout_metrics_20242025": blend_eval_holdout,
                "holdout_distribution": dist_blend_holdout
            },
            "elo_as_feature_research": {
                "point_in_time_provenance_method": "PointInTimeAdapter.extract_game_features_with_cutoff",
                "excluded_unverifiable_games": excluded_provenance_count,
                "baseline_11_features": {
                    "validation_metrics_20232024": base_exp_res.metrics,
                    "holdout_metrics_20242025": base_exp_res.test_metrics
                },
                "augmented_15_features": {
                    "validation_metrics_20232024": elo_exp_res.metrics,
                    "holdout_metrics_20242025": elo_exp_res.test_metrics
                },
                "validation_log_loss_delta": round(base_exp_res.metrics["log_loss"] - elo_exp_res.metrics["log_loss"], 4),
                "holdout_log_loss_delta": round(base_exp_res.test_metrics["log_loss"] - elo_exp_res.test_metrics["log_loss"], 4),
                "validation_brier_delta": round(base_exp_res.metrics["brier_score"] - elo_exp_res.metrics["brier_score"], 4),
                "holdout_brier_delta": round(base_exp_res.test_metrics["brier_score"] - elo_exp_res.test_metrics["brier_score"], 4)
            },
            "forecast_intelligence_summary": agreement_summary,
            "bootstrap_comparisons_holdout_20242025": {
                "production_vs_reference_elo": boot_prod_vs_ref_elo,
                "production_vs_selected_research_elo": boot_prod_vs_sel_elo,
                "production_vs_probability_blend": boot_prod_vs_blend
            },
            "calibration_analysis_holdout_20242025": {
                "production_model_bins": calib_prod_holdout,
                "reference_elo_bins": calib_ref_elo_holdout,
                "selected_research_elo_bins": calib_sel_elo_holdout,
                "probability_blend_bins": calib_blend_holdout
            },
            "narrative_conclusions": narrative_conclusions
        }

        # Save JSON report
        reports_dir = Path(root_dir) / "reports" / "v1.5"
        reports_dir.mkdir(parents=True, exist_ok=True)

        json_path = reports_dir / "stage6_forecast_elo_research.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(report_data, f, indent=2)
        logger.info(f"Saved machine-readable report to {json_path}")

        # Construct Markdown report
        md_content = f"""# Stage 6 — Forecast Intelligence & Elo Research Report

**Evaluated At:** `{execution_time}`  
**Research Execution Git SHA:** `{git_sha}`  
**Production Artifact Invariance:** Verified (SHA-256 match)

---

## 1. Executive Summary & Dynamic Research Conclusions

This research study evaluates whether Elo-derived team strength signals improve PuckLens game forecasting. All evaluations were conducted using a strict, leakage-safe chronological protocol across 4 NHL regular seasons:

* **2021–22:** Development & Elo state initialization
* **2022–23:** Parameter selection & blend weight optimization
* **2023–24:** Frozen research validation
* **2024–25:** Untouched final holdout

### Key Empirical Findings:

"""
        for idx, conc in enumerate(narrative_conclusions, 1):
            md_content += f"{idx}. {conc}\n"

        md_content += f"""
---

## 2. Model Performance Summary Across Evaluation Windows

### Frozen 2023–24 Research Validation Window ({len(games_by_season['20232024'])} Games)

| Forecast Approach | Log Loss | Brier Score | Accuracy (%) | ECE |
| :--- | :---: | :---: | :---: | :---: |
| **Production Win Model (v1.4.0)** | {prod_eval_val['log_loss']:.4f} | {prod_eval_val['brier_score']:.4f} | {prod_eval_val['accuracy']:.2f}% | {prod_eval_val['ece']:.4f} |
| **Probability Blend (w={best_w:.2f})** | {blend_eval_val['log_loss']:.4f} | {blend_eval_val['brier_score']:.4f} | {blend_eval_val['accuracy']:.2f}% | {blend_eval_val['ece']:.4f} |
| **Selected Research Elo** | {sel_eval_val['log_loss']:.4f} | {sel_eval_val['brier_score']:.4f} | {sel_eval_val['accuracy']:.2f}% | {sel_eval_val['ece']:.4f} |
| **Reference Elo Baseline** | {ref_eval_val['log_loss']:.4f} | {ref_eval_val['brier_score']:.4f} | {ref_eval_val['accuracy']:.2f}% | {ref_eval_val['ece']:.4f} |

### Untouched 2024–25 Final Holdout Window ({n_holdout} Games)

| Forecast Approach | Log Loss | Brier Score | Accuracy (%) | ECE | Extreme Probs (<0.20 or >0.80) |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Production Win Model (v1.4.0)** | {prod_eval_holdout['log_loss']:.4f} | {prod_eval_holdout['brier_score']:.4f} | {prod_eval_holdout['accuracy']:.2f}% | {prod_eval_holdout['ece']:.4f} | {dist_prod_holdout['extreme_probability_pct']:.2f}% ({dist_prod_holdout['extreme_probability_count_lt20_gt80']}) |
| **Probability Blend (w={best_w:.2f})** | {blend_eval_holdout['log_loss']:.4f} | {blend_eval_holdout['brier_score']:.4f} | {blend_eval_holdout['accuracy']:.2f}% | {blend_eval_holdout['ece']:.4f} | {dist_blend_holdout['extreme_probability_pct']:.2f}% ({dist_blend_holdout['extreme_probability_count_lt20_gt80']}) |
| **Selected Research Elo** | {sel_eval_holdout['log_loss']:.4f} | {sel_eval_holdout['brier_score']:.4f} | {sel_eval_holdout['accuracy']:.2f}% | {sel_eval_holdout['ece']:.4f} | {dist_sel_elo_holdout['extreme_probability_pct']:.2f}% ({dist_sel_elo_holdout['extreme_probability_count_lt20_gt80']}) |
| **Reference Elo Baseline** | {ref_eval_holdout['log_loss']:.4f} | {ref_eval_holdout['brier_score']:.4f} | {ref_eval_holdout['accuracy']:.2f}% | {ref_eval_holdout['ece']:.4f} | {dist_ref_elo_holdout['extreme_probability_pct']:.2f}% ({dist_ref_elo_holdout['extreme_probability_count_lt20_gt80']}) |

---

## 3. Elo Parameter Optimization Protocol & Results

Parameters were selected strictly on **2022–23 Log Loss** using state initialized from **2021–22**.

* **Reference Configuration:** `initial_elo=1500`, `k_factor=20`, `home_advantage=35`, `season_regression=0.25`, `use_mov=True`
* **Selected Candidate Configuration:** `initial_elo={selected_cfg.initial_elo}`, `k_factor={selected_cfg.k_factor}`, `home_advantage={selected_cfg.home_advantage}`, `season_regression={selected_cfg.season_regression}`, `use_mov={selected_cfg.use_mov_multiplier}`
* **Config Hash:** `{selected_cfg.compute_config_hash()[:16]}...`
* **Selection Metric (2022–23 Log Loss):** `{top_candidate['log_loss']:.4f}`

---

## 4. Elo-as-Feature Research (Point-in-Time Provenance)

Controlled experiment using Stage 5 `PointInTimeAdapter` with Logistic Regression:

* **Point-in-Time Provenance:** `PointInTimeAdapter.extract_game_features_with_cutoff` (zero synthetic timestamps).
* **Baseline Candidate (11 Production Features):**
  * 2023–24 Validation Log Loss: `{base_exp_res.metrics['log_loss']:.4f}`
  * 2024–25 Holdout Log Loss: `{base_exp_res.test_metrics['log_loss']:.4f}`
* **Elo-Augmented Candidate (11 Features + 4 Pregame Elo Features):**
  * 2023–24 Validation Log Loss: `{elo_exp_res.metrics['log_loss']:.4f}`
  * 2024–25 Holdout Log Loss: `{elo_exp_res.test_metrics['log_loss']:.4f}`
* **Validation Delta (Validation Log Loss Improvement):** `{report_data['elo_as_feature_research']['validation_log_loss_delta']:+.4f}`
* **Holdout Delta (Holdout Log Loss Improvement):** `{report_data['elo_as_feature_research']['holdout_log_loss_delta']:+.4f}`

---

## 5. Forecast Intelligence Signals & Agreement Analysis

Game-level agreement analysis on 2024–25 holdout ({n_holdout} games):

* **Win Outcome Pick Agreement:** {agreement_summary['win_pick_agreement_pct']}% ({agreement_summary['win_pick_agreement_count']}/{n_holdout} games)
* **High Agreement (|diff| < 0.05):** {agreement_summary['agreement_bands']['high_agreement']['pct']}% ({agreement_summary['agreement_bands']['high_agreement']['count']} games)
* **Moderate Disagreement (0.05 <= |diff| < 0.15):** {agreement_summary['agreement_bands']['moderate_disagreement']['pct']}% ({agreement_summary['agreement_bands']['moderate_disagreement']['count']} games)
* **Large Disagreement (|diff| >= 0.15):** {agreement_summary['agreement_bands']['large_disagreement']['pct']}% ({agreement_summary['agreement_bands']['large_disagreement']['count']} games)

---

## 6. Paired Bootstrap Statistical Evidence (1,000 Resamples on 2024–25 Holdout)

> **Sign Semantics Note:** Difference = `comparator - base`. A negative difference indicates that the comparator model achieved a lower (better) score than the base production model.

| Comparison | Metric | Observed Difference (Comp - Base) | 95% Confidence Interval | Std Error |
| :--- | :--- | :---: | :---: | :---: |
| **Production vs. Reference Elo** | Log Loss | `{boot_prod_vs_ref_elo['log_loss_difference']['comparator_minus_base_diff']:+.4f}` | `[{boot_prod_vs_ref_elo['log_loss_difference']['ci_95_lower']:+.4f}, {boot_prod_vs_ref_elo['log_loss_difference']['ci_95_upper']:+.4f}]` | `{boot_prod_vs_ref_elo['log_loss_difference']['std_error']:.4f}` |
| | Brier Score | `{boot_prod_vs_ref_elo['brier_score_difference']['comparator_minus_base_diff']:+.4f}` | `[{boot_prod_vs_ref_elo['brier_score_difference']['ci_95_lower']:+.4f}, {boot_prod_vs_ref_elo['brier_score_difference']['ci_95_upper']:+.4f}]` | `{boot_prod_vs_ref_elo['brier_score_difference']['std_error']:.4f}` |
| **Production vs. Selected Elo** | Log Loss | `{boot_prod_vs_sel_elo['log_loss_difference']['comparator_minus_base_diff']:+.4f}` | `[{boot_prod_vs_sel_elo['log_loss_difference']['ci_95_lower']:+.4f}, {boot_prod_vs_sel_elo['log_loss_difference']['ci_95_upper']:+.4f}]` | `{boot_prod_vs_sel_elo['log_loss_difference']['std_error']:.4f}` |
| | Brier Score | `{boot_prod_vs_sel_elo['brier_score_difference']['comparator_minus_base_diff']:+.4f}` | `[{boot_prod_vs_sel_elo['brier_score_difference']['ci_95_lower']:+.4f}, {boot_prod_vs_sel_elo['brier_score_difference']['ci_95_upper']:+.4f}]` | `{boot_prod_vs_sel_elo['brier_score_difference']['std_error']:.4f}` |
| **Production vs. Blend (w={best_w:.2f})** | Log Loss | `{boot_prod_vs_blend['log_loss_difference']['comparator_minus_base_diff']:+.4f}` | `[{boot_prod_vs_blend['log_loss_difference']['ci_95_lower']:+.4f}, {boot_prod_vs_blend['log_loss_difference']['ci_95_upper']:+.4f}]` | `{boot_prod_vs_blend['log_loss_difference']['std_error']:.4f}` |
| | Brier Score | `{boot_prod_vs_blend['brier_score_difference']['comparator_minus_base_diff']:+.4f}` | `[{boot_prod_vs_blend['brier_score_difference']['ci_95_lower']:+.4f}, {boot_prod_vs_blend['brier_score_difference']['ci_95_upper']:+.4f}]` | `{boot_prod_vs_blend['brier_score_difference']['std_error']:.4f}` |

---

## 7. Conclusions & Production Invariance Statement

1. **Frozen Production Model Preserved:** `pucklens-win-v1.4.0` remains 100% unchanged as the active production model.
2. **Elo Research Qualification:** Elo research parameters, probability blending, and Elo-as-feature experiments were executed cleanly under point-in-time provenance.
3. **Forecast Intelligence Availability:** `ForecastIntelligenceService` provides transparent research-layer comparison descriptors when invoked.
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
