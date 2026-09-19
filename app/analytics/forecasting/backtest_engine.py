import os
import math
import json
import logging
from datetime import datetime, timezone
from typing import Dict, List, Any, Tuple, Optional

from sqlalchemy import func
from app.models import db, Game
from app.services.pregame_feature_service import PregameFeatureService
from app.services.elo_service import EloService
from app.analytics.forecasting.win_probability import WinProbabilityModel
from app.analytics.forecasting.score_projection import PoissonScoreModel

logger = logging.getLogger(__name__)

class BacktestEngine:
    """
    Historical Out-of-Time Backtesting Engine for PuckLens v1.4.0.
    
    Splits Protocol:
    - Train: 2021-22
    - Model Selection: 2022-23
    - Combined Refit: 2021-22 + 2022-23
    - Calibration: 2023-24
    - Final Test: 2024-25 (Untouched Holdout)
    """

    def __init__(self):
        self.win_model = WinProbabilityModel()
        self.elo_results = None
        self.model_selection_summary = None

    def run_full_backtest(self, skip_gate: bool = False) -> Dict[str, Any]:
        """
        Executes the complete out-of-time historical backtest protocol across 4 seasons.
        """
        if not skip_gate:
            from scripts.audit_seasons import audit_season_data
            audit_summary = audit_season_data(save_report=False)
            gate = audit_summary.get("production_forecast_data_gate", {})
            if not gate.get("pass", False):
                reasons = "; ".join(gate.get("reasons", ["Production training gate criteria not met"]))
                raise RuntimeError(f"PRODUCTION BACKTEST BLOCKED: {reasons}")

        logger.info("Step 0: Preloading pregame event stats into memory...")
        PregameFeatureService.preload_all_stats()

        logger.info("Step 1: Running baseline Elo backtest across 2021-22 to 2024-25...")
        self.elo_results = EloService.run_elo_backtest(['20212022', '20222023', '20232024', '20242025'])

        logger.info("Step 2: Training and selecting win probability classifier...")
        self.model_selection_summary = self.win_model.train_and_select(
            train_season='20212022',
            select_season='20222023',
            calibrate_season='20232024'
        )

        logger.info("Step 3: Evaluating final test holdout (2024-25)...")
        test_eval = self.evaluate_season('20242025')
        calib_eval = self.evaluate_season('20232024')
        select_eval = self.evaluate_season('20222023')

        summary = {
            "backtest_run_at": datetime.now(timezone.utc).isoformat(),
            "protocol": {
                "train_season": "20212022",
                "select_season": "20222023",
                "refit_seasons": "20212022 + 20222023",
                "calibrate_season": "20232024",
                "test_season": "20242025 (Holdout)"
            },
            "model_selection": self.model_selection_summary,
            "test_season_20242025_eval": test_eval,
            "calibrate_season_20232024_eval": calib_eval,
            "select_season_20222023_eval": select_eval,
            "elo_baseline_overall": self.elo_results.get("overall_metrics", {})
        }

        return summary

    def evaluate_active_registry_model(self, season: str = '20242025') -> Dict[str, Any]:
        """
        Authoritative artifact-bound holdout evaluation.
        Loads frozen active model from ForecastModelRegistry, asserts artifact SHA-256 consistency,
        and evaluates untouched holdout season (2024-25 only) with zero fitting, refitting, or tuning.
        """
        import uuid
        import subprocess
        from app.analytics.forecasting.model_registry import ForecastModelRegistry

        # Load active production model & manifest
        win_model, manifest = ForecastModelRegistry.load_active_model()
        self.win_model = win_model

        # Get actual model pkl SHA-256 on disk
        models_dir = ForecastModelRegistry.get_models_dir()
        model_version = manifest["model_version"]
        pkl_path = os.path.join(models_dir, f"pucklens-win-{model_version}.pkl")
        actual_sha = ForecastModelRegistry.compute_sha256(pkl_path)

        assert actual_sha == manifest["artifact_sha256"], (
            f"Artifact SHA mismatch: computed {actual_sha} != manifest {manifest['artifact_sha256']}"
        )

        # Get Git commit SHA
        try:
            git_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        except Exception:
            git_sha = manifest.get("git_commit_sha")

        # Run Elo baseline for comparison
        self.elo_results = EloService.run_elo_backtest(['20212022', '20222023', '20232024', season])

        # Preload stats
        PregameFeatureService.preload_all_stats()

        # Evaluate target untouched holdout season only (no training/calibration)
        holdout_eval = self.evaluate_season(season)

        run_uuid = str(uuid.uuid4())
        summary = {
            "evaluation_type": "artifact_bound_holdout_evaluation",
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
            "run_uuid": run_uuid,
            "git_commit_sha": git_sha,
            "model_version": model_version,
            "artifact_sha256": actual_sha,
            "feature_schema_version": manifest.get("feature_schema_version", "v1.4.0"),
            "protocol": {
                "train_season": "20212022",
                "select_season": "20222023",
                "refit_seasons": "20212022 + 20222023",
                "calibrate_season": "20232024",
                "test_season": f"{season} (Untouched Holdout)"
            },
            "manifest_metadata": manifest,
            "test_season_20242025_eval": holdout_eval,
            "elo_baseline_overall": self.elo_results.get("overall_metrics", {})
        }
        return summary

    def evaluate_external_season(self, season: str = '20252026', skip_gate: bool = False) -> Dict[str, Any]:
        """
        Stage 4: Dedicated External Season Validation Method.
        - Enforces Stage 4 Data Audit Gate (fail-closed unless 1,312 games, nhl_api only, zero synthetic/duplicates, >=99% coverage).
        - Loads active frozen model via ForecastModelRegistry.load_active_model() and asserts artifact SHA-256 matching.
        - Zero fitting, refitting, calibration, or tuning.
        - Computes dynamic Elo baseline chronologically across 5 seasons (20212022 -> 20222023 -> 20232024 -> 20242025 -> season).
        - Computes expanded generalization analysis:
          * Delta metrics (Log Loss, Brier, ECE vs 2024-25 holdout).
          * 10 probability calibration / reliability bins.
          * Early, Mid, and Late season performance splits.
          * Prediction distribution and 11-feature drift analysis (KS test & SMD).
          * Bootstrap 95% CIs for model-vs-Elo metric differences.
        - Dynamic key: external_season_{season}_eval.
        - Returns provenance metadata: model_training_git_sha, evaluation_git_sha, model_version, artifact_sha256, feature_schema_version, run_uuid, evaluated_at, data_audit_snapshot_hash.
        """
        import uuid
        import subprocess
        from app.analytics.forecasting.model_registry import ForecastModelRegistry
        from scripts.audit_seasons import audit_stage4_external_season_gate

        # Step 1: Stage 4 Data Gate
        passed, gate_reasons, snapshot_hash = audit_stage4_external_season_gate(season)
        if not passed and not skip_gate:
            reasons_str = "; ".join(gate_reasons)
            raise RuntimeError(f"STAGE 4 EXTERNAL VALIDATION BLOCKED: {reasons_str}")

        # Step 2: Load Active Model & Verify Artifact SHA
        win_model, manifest = ForecastModelRegistry.load_active_model()
        self.win_model = win_model

        models_dir = ForecastModelRegistry.get_models_dir()
        model_version = manifest["model_version"]
        pkl_path = os.path.join(models_dir, f"pucklens-win-{model_version}.pkl")
        actual_sha = ForecastModelRegistry.compute_sha256(pkl_path)

        assert actual_sha == manifest["artifact_sha256"], (
            f"Artifact SHA mismatch: computed {actual_sha} != manifest {manifest['artifact_sha256']}"
        )

        # Get Git Commit SHA
        try:
            git_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        except Exception:
            git_sha = manifest.get("git_commit_sha")

        # Step 3: 5-Season Continuous Chronological Elo Baseline
        all_seasons = ['20212022', '20222023', '20232024', '20242025', season]
        self.elo_results = EloService.run_elo_backtest(all_seasons)

        # Preload stats
        PregameFeatureService.preload_all_stats()

        # Step 4: Evaluate target external season & 2024-25 holdout baseline
        ext_eval = self._evaluate_season_detailed(season)
        holdout_eval = self._evaluate_season_detailed('20242025')

        # Feature Drift Analysis
        feature_drift = self._calculate_feature_drift(
            holdout_eval.get("feature_matrix", {}),
            ext_eval.get("feature_matrix", {})
        )

        # Bootstrap Confidence Intervals for model-vs-Elo differences on external season
        bootstrap_cis = self._calculate_bootstrap_cis(
            ext_eval.get("y_true", []),
            ext_eval.get("y_prob_model", []),
            ext_eval.get("y_prob_elo", []),
            n_bootstraps=1000
        )

        # Clean internal lists before returning summary JSON
        ext_eval_clean = {k: v for k, v in ext_eval.items() if k not in ("y_true", "y_prob_model", "y_prob_elo", "feature_matrix")}
        holdout_eval_clean = {k: v for k, v in holdout_eval.items() if k not in ("y_true", "y_prob_model", "y_prob_elo", "feature_matrix")}

        run_uuid = str(uuid.uuid4())
        summary = {
            "evaluation_type": "stage4_external_season_validation",
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
            "run_uuid": run_uuid,
            "model_training_git_sha": manifest.get("git_commit_sha"),
            "evaluation_git_sha": git_sha,
            "model_version": model_version,
            "artifact_sha256": actual_sha,
            "feature_schema_version": manifest.get("feature_schema_version", "v1.4.0"),
            "data_audit_snapshot_hash": snapshot_hash,
            "protocol": {
                "train_seasons": "20212022 + 20222023",
                "calibration_season": "20232024",
                "holdout_season": "20242025",
                "external_validation_season": f"{season} (Untouched External)"
            },
            f"external_season_{season}_eval": ext_eval_clean,
            "holdout_season_20242025_eval": holdout_eval_clean,
            "generalization_delta_metrics": {
                "delta_log_loss": round(ext_eval_clean["calibrated_model"]["log_loss"] - holdout_eval_clean["calibrated_model"]["log_loss"], 4),
                "delta_brier_score": round(ext_eval_clean["calibrated_model"]["brier_score"] - holdout_eval_clean["calibrated_model"]["brier_score"], 4),
                "delta_ece": round(ext_eval_clean["calibrated_model"]["ece"] - holdout_eval_clean["calibrated_model"]["ece"], 4)
            },
            "feature_drift_analysis": feature_drift,
            "bootstrap_confidence_intervals": bootstrap_cis,
            "manifest_metadata": manifest
        }
        return summary

    def _evaluate_season_detailed(self, season: str) -> Dict[str, Any]:
        """
        Detailed evaluation of a season returning probabilities, feature values, calibration bins,
        season timeline splits, and score projection metrics.
        """
        games = Game.query.filter(
            Game.season == season,
            Game.game_type == 'R',
            Game.data_source == 'nhl_api',
            Game.nhl_game_state.in_(['OFF', 'FINAL', 'OVER'])
        ).order_by(
            func.coalesce(Game.start_time_utc, Game.game_date).asc(),
            Game.game_id.asc()
        ).all()

        if not games:
            empty_eval = {"log_loss": 0.0, "brier_score": 0.0, "accuracy": 0.0, "ece": 0.0}
            empty_dist = {"mean": 0.0, "std": 0.0, "min": 0.0, "p25": 0.0, "median": 0.0, "p75": 0.0, "max": 0.0, "iqr": 0.0}
            return {
                "season": season,
                "game_count": 0,
                "calibrated_model": empty_eval,
                "elo_baseline": empty_eval,
                "naive_50_50_log_loss": 0.6931,
                "prediction_distribution": empty_dist,
                "calibration_bins": [],
                "season_timeline_splits": {},
                "score_projection": {
                    "expected_total_goals_mae": 0.0,
                    "home_goals_mae": 0.0,
                    "away_goals_mae": 0.0,
                    "exact_scoreline_coverage_pct": 0.0,
                    "top5_scoreline_coverage_pct": 0.0
                },
                "y_true": [],
                "y_prob_model": [],
                "y_prob_elo": [],
                "feature_matrix": {fname: [] for fname in self.win_model.feature_names},
                "error": f"No completed regular season games found for {season}"
            }

        predictions = []
        y_true = []
        y_prob_model = []
        y_prob_elo = []
        
        feature_matrix: Dict[str, List[float]] = {fname: [] for fname in self.win_model.feature_names}

        tot_goals_mae = 0.0
        home_goals_mae = 0.0
        away_goals_mae = 0.0
        exact_score_hits = 0
        top5_score_hits = 0

        # Extract Elo predictions lookup map for this season
        elo_map = {}
        if self.elo_results and "predictions" in self.elo_results:
            for p in self.elo_results["predictions"]:
                if p.get("game_id"):
                    elo_map[p["game_id"]] = p.get("p_home_win", 0.5)

        for g in games:
            feats = PregameFeatureService.get_pregame_features(g)
            win_pred = self.win_model.predict_game_probability(feats)
            score_proj = PoissonScoreModel.project_score_distribution(feats)

            actual_home_win = 1 if g.home_score > g.away_score else 0
            p_home = win_pred["home_win_probability"]
            p_elo = elo_map.get(g.game_id, 0.5)

            y_true.append(actual_home_win)
            y_prob_model.append(p_home)
            y_prob_elo.append(p_elo)

            for fname in self.win_model.feature_names:
                feature_matrix[fname].append(float(feats[fname]))

            actual_tot_goals = g.home_score + g.away_score
            proj_tot_goals = score_proj["expected_total_goals"]
            tot_goals_mae += abs(actual_tot_goals - proj_tot_goals)
            home_goals_mae += abs(g.home_score - score_proj["expected_home_goals"])
            away_goals_mae += abs(g.away_score - score_proj["expected_away_goals"])

            actual_score_str = f"{g.home_score}-{g.away_score}"
            top_scores = [s["score"] for s in score_proj.get("top_scorelines", [])]
            if top_scores and actual_score_str == top_scores[0]:
                exact_score_hits += 1
            if actual_score_str in top_scores[:5]:
                top5_score_hits += 1

            predictions.append({
                "game_id": g.game_id,
                "p_home_win": p_home,
                "actual_home_win": actual_home_win,
                "exp_home_goals": score_proj["expected_home_goals"],
                "exp_away_goals": score_proj["expected_away_goals"],
                "actual_home_score": g.home_score,
                "actual_away_score": g.away_score
            })

        n = len(games)
        eval_metrics = EloService.evaluate_predictions(predictions)

        # Match Elo baseline predictions for the exact season
        elo_season_metrics = self.elo_results.get("season_metrics", {}).get(season, {}) if self.elo_results else {}

        # Compute calibration bins (10 bins)
        calib_bins = self._calculate_calibration_bins(y_true, y_prob_model, n_bins=10)

        # Compute season splits (Early, Mid, Late)
        season_splits = self._calculate_season_splits(y_true, y_prob_model)

        # Compute prediction distribution stats
        pred_dist = self._calculate_distribution_stats(y_prob_model)

        return {
            "season": season,
            "game_count": n,
            "calibrated_model": eval_metrics,
            "elo_baseline": elo_season_metrics,
            "naive_50_50_log_loss": 0.6931,
            "prediction_distribution": pred_dist,
            "calibration_bins": calib_bins,
            "season_timeline_splits": season_splits,
            "score_projection": {
                "expected_total_goals_mae": round(tot_goals_mae / n, 2),
                "home_goals_mae": round(home_goals_mae / n, 2),
                "away_goals_mae": round(away_goals_mae / n, 2),
                "exact_scoreline_coverage_pct": round((exact_score_hits / n) * 100.0, 2),
                "top5_scoreline_coverage_pct": round((top5_score_hits / n) * 100.0, 2)
            },
            "y_true": y_true,
            "y_prob_model": y_prob_model,
            "y_prob_elo": y_prob_elo,
            "feature_matrix": feature_matrix
        }


    def _calculate_calibration_bins(self, y_true: List[int], y_prob: List[float], n_bins: int = 10) -> List[Dict[str, Any]]:
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

    def _calculate_season_splits(self, y_true: List[int], y_prob: List[float]) -> Dict[str, Any]:
        n = len(y_true)
        if n == 0:
            return {}

        third = n // 3
        idx_early = (0, third)
        idx_mid = (third, 2 * third)
        idx_late = (2 * third, n)

        splits = {}
        for name, (start_i, end_i) in [("early_season", idx_early), ("mid_season", idx_mid), ("late_season", idx_late)]:
            yt = y_true[start_i:end_i]
            yp = y_prob[start_i:end_i]
            if not yt:
                continue

            preds = [{"p_home_win": p, "actual_home_win": y} for p, y in zip(yp, yt)]
            metrics = EloService.evaluate_predictions(preds)
            splits[name] = {
                "game_count": len(yt),
                "start_game_index": start_i + 1,
                "end_game_index": end_i,
                "metrics": metrics
            }
        return splits

    def _calculate_distribution_stats(self, values: List[float]) -> Dict[str, float]:
        import numpy as np
        arr = np.array(values, dtype=np.float64)
        if len(arr) == 0:
            return {}
        p25 = float(np.percentile(arr, 25))
        p75 = float(np.percentile(arr, 75))
        return {
            "mean": round(float(np.mean(arr)), 4),
            "std": round(float(np.std(arr)), 4),
            "min": round(float(np.min(arr)), 4),
            "p25": round(p25, 4),
            "median": round(float(np.median(arr)), 4),
            "p75": round(p75, 4),
            "max": round(float(np.max(arr)), 4),
            "iqr": round(p75 - p25, 4)
        }

    def _calculate_feature_drift(self, feats_holdout: Dict[str, List[float]], feats_ext: Dict[str, List[float]]) -> Dict[str, Any]:
        import numpy as np
        try:
            from scipy.stats import ks_2samp
            has_scipy = True
        except ImportError:
            has_scipy = False

        drift_report = {}
        for fname in self.win_model.feature_names:
            arr_h = np.array(feats_holdout.get(fname, []), dtype=np.float64)
            arr_e = np.array(feats_ext.get(fname, []), dtype=np.float64)

            if len(arr_h) == 0 or len(arr_e) == 0:
                continue

            mean_h, std_h = float(np.mean(arr_h)), float(np.std(arr_h))
            mean_e, std_e = float(np.mean(arr_e)), float(np.std(arr_e))

            pooled_std = math.sqrt((std_h**2 + std_e**2) / 2.0)
            smd = float((mean_e - mean_h) / pooled_std) if pooled_std > 0 else 0.0

            if has_scipy:
                ks_res = ks_2samp(arr_h, arr_e)
                ks_stat = float(ks_res.statistic)
                ks_pvalue = float(ks_res.pvalue)
            else:
                ks_stat = 0.0
                ks_pvalue = 1.0

            drift_report[fname] = {
                "holdout_20242025": {
                    "mean": round(mean_h, 4),
                    "std": round(std_h, 4),
                    "p25": round(float(np.percentile(arr_h, 25)), 4),
                    "median": round(float(np.median(arr_h)), 4),
                    "p75": round(float(np.percentile(arr_h, 75)), 4),
                },
                "external_season": {
                    "mean": round(mean_e, 4),
                    "std": round(std_e, 4),
                    "p25": round(float(np.percentile(arr_e, 25)), 4),
                    "median": round(float(np.median(arr_e)), 4),
                    "p75": round(float(np.percentile(arr_e, 75)), 4),
                },
                "smd": round(smd, 4),
                "ks_statistic": round(ks_stat, 4),
                "ks_pvalue": round(ks_pvalue, 4),
                "drift_detected": (ks_pvalue < 0.05 or abs(smd) > 0.25)
            }
        return drift_report

    def _calculate_bootstrap_cis(self, y_true: List[int], p_model: List[float], p_elo: List[float], n_bootstraps: int = 1000, seed: int = 42) -> Dict[str, Any]:
        import numpy as np
        n = len(y_true)
        if n == 0:
            return {}

        rng = np.random.RandomState(seed)
        y_arr = np.array(y_true)
        pm_arr = np.array(p_model)
        pe_arr = np.array(p_elo)

        eps = 1e-15
        pm_arr = np.clip(pm_arr, eps, 1.0 - eps)
        pe_arr = np.clip(pe_arr, eps, 1.0 - eps)

        diff_ll_list = []
        diff_brier_list = []

        for _ in range(n_bootstraps):
            idxs = rng.choice(n, size=n, replace=True)
            y_b = y_arr[idxs]
            pm_b = pm_arr[idxs]
            pe_b = pe_arr[idxs]

            ll_m = -np.mean(y_b * np.log(pm_b) + (1.0 - y_b) * np.log(1.0 - pm_b))
            ll_e = -np.mean(y_b * np.log(pe_b) + (1.0 - y_b) * np.log(1.0 - pe_b))

            brier_m = np.mean((pm_b - y_b) ** 2)
            brier_e = np.mean((pe_b - y_b) ** 2)

            diff_ll_list.append(ll_m - ll_e)
            diff_brier_list.append(brier_m - brier_e)

        diff_ll_list = np.array(diff_ll_list)
        diff_brier_list = np.array(diff_brier_list)

        obs_ll_m = -float(np.mean(y_arr * np.log(pm_arr) + (1.0 - y_arr) * np.log(1.0 - pm_arr)))
        obs_ll_e = -float(np.mean(y_arr * np.log(pe_arr) + (1.0 - y_arr) * np.log(1.0 - pe_arr)))
        obs_brier_m = float(np.mean((pm_arr - y_arr) ** 2))
        obs_brier_e = float(np.mean((pe_arr - y_arr) ** 2))

        return {
            "log_loss_difference": {
                "mean_diff": round(obs_ll_m - obs_ll_e, 4),
                "ci_95_lower": round(float(np.percentile(diff_ll_list, 2.5)), 4),
                "ci_95_upper": round(float(np.percentile(diff_ll_list, 97.5)), 4),
                "std_error": round(float(np.std(diff_ll_list)), 4)
            },
            "brier_score_difference": {
                "mean_diff": round(obs_brier_m - obs_brier_e, 4),
                "ci_95_lower": round(float(np.percentile(diff_brier_list, 2.5)), 4),
                "ci_95_upper": round(float(np.percentile(diff_brier_list, 97.5)), 4),
                "std_error": round(float(np.std(diff_brier_list)), 4)
            }
        }

    def evaluate_season(self, season: str) -> Dict[str, Any]:
        """
        Evaluates pregame forecasts on a target season using the trained & calibrated WinProbabilityModel
        and PoissonScoreModel against ground truth game outcomes.
        """
        games = Game.query.filter(
            Game.season == season,
            Game.game_type == 'R',
            Game.data_source == 'nhl_api',
            Game.nhl_game_state.in_(['OFF', 'FINAL', 'OVER'])
        ).order_by(
            func.coalesce(Game.start_time_utc, Game.game_date).asc(),
            Game.game_id.asc()
        ).all()

        if not games:
            return {"game_count": 0, "error": f"No completed regular season games found for {season}"}

        predictions = []
        y_true = []
        y_prob = []
        
        tot_goals_mae = 0.0
        home_goals_mae = 0.0
        away_goals_mae = 0.0
        exact_score_hits = 0
        top5_score_hits = 0

        for g in games:
            feats = PregameFeatureService.get_pregame_features(g)
            win_pred = self.win_model.predict_game_probability(feats)
            score_proj = PoissonScoreModel.project_score_distribution(feats)

            actual_home_win = 1 if g.home_score > g.away_score else 0
            p_home = win_pred["home_win_probability"]

            y_true.append(actual_home_win)
            y_prob.append(p_home)

            actual_tot_goals = g.home_score + g.away_score
            proj_tot_goals = score_proj["expected_total_goals"]
            tot_goals_mae += abs(actual_tot_goals - proj_tot_goals)
            home_goals_mae += abs(g.home_score - score_proj["expected_home_goals"])
            away_goals_mae += abs(g.away_score - score_proj["expected_away_goals"])

            actual_score_str = f"{g.home_score}-{g.away_score}"
            top_scores = [s["score"] for s in score_proj.get("top_scorelines", [])]
            if top_scores and actual_score_str == top_scores[0]:
                exact_score_hits += 1
            if actual_score_str in top_scores[:5]:
                top5_score_hits += 1

            predictions.append({
                "game_id": g.game_id,
                "p_home_win": p_home,
                "actual_home_win": actual_home_win,
                "exp_home_goals": score_proj["expected_home_goals"],
                "exp_away_goals": score_proj["expected_away_goals"],
                "actual_home_score": g.home_score,
                "actual_away_score": g.away_score
            })

        n = len(games)
        eval_metrics = EloService.evaluate_predictions(predictions)

        # Elo metrics for the same season
        elo_season_metrics = self.elo_results.get("season_metrics", {}).get(season, {}) if self.elo_results else {}

        return {
            "season": season,
            "game_count": n,
            "calibrated_model": eval_metrics,
            "elo_baseline": elo_season_metrics,
            "naive_50_50_log_loss": 0.6931,
            "score_projection": {
                "expected_total_goals_mae": round(tot_goals_mae / n, 2),
                "home_goals_mae": round(home_goals_mae / n, 2),
                "away_goals_mae": round(away_goals_mae / n, 2),
                "exact_scoreline_coverage_pct": round((exact_score_hits / n) * 100.0, 2),
                "top5_scoreline_coverage_pct": round((top5_score_hits / n) * 100.0, 2)
            }
        }

