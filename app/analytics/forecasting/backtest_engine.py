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

    def run_full_backtest(self) -> Dict[str, Any]:
        """
        Executes the complete out-of-time historical backtest protocol across 4 seasons.
        """
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

    def evaluate_season(self, season: str) -> Dict[str, Any]:
        """
        Evaluates pregame forecasts on a target season using the trained & calibrated WinProbabilityModel
        and PoissonScoreModel against ground truth game outcomes.
        """
        games = Game.query.filter(
            Game.season == season,
            Game.game_type == 'R',
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
        top_score_hits = 0

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

            # Check if actual score is in top 5 projected scorelines
            actual_score_str = f"{g.home_score}-{g.away_score}"
            top_5_scores = [s["score"] for s in score_proj["top_scorelines"]]
            if actual_score_str in top_5_scores:
                top_score_hits += 1

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
                "total_goals_mae": round(tot_goals_mae / n, 2),
                "top5_scoreline_coverage_pct": round((top_score_hits / n) * 100.0, 2)
            }
        }
