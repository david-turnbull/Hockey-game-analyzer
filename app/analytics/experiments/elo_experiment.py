"""
Elo Research Experiment Engine and Configuration.

Provides a parameterizable, leakage-safe Elo research framework separate from production EloService.
Allows exploring variations in initial Elo, K-factor, home-ice advantage, season regression,
and margin-of-victory (MOV) adjustment without mutating production constants.
"""

import math
import hashlib
import json
import logging
from dataclasses import dataclass, asdict
from typing import Dict, List, Any, Tuple, Optional
from sqlalchemy import func
from app.models import db, Game

logger = logging.getLogger(__name__)


@dataclass
class EloResearchConfig:
    """
    Configuration specification for Elo research experiments.
    """
    initial_elo: float = 1500.0
    k_factor: float = 20.0
    home_advantage: float = 35.0
    season_regression: float = 0.25
    use_mov_multiplier: bool = True

    def compute_config_hash(self) -> str:
        """Computes a deterministic SHA-256 hash for this config."""
        d = self.to_dict()
        canonical_str = json.dumps(d, sort_keys=True)
        return hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        """Returns dictionary representation with rounded float parameters for clean serialization."""
        return {
            "initial_elo": float(self.initial_elo),
            "k_factor": float(self.k_factor),
            "home_advantage": float(self.home_advantage),
            "season_regression": float(self.season_regression),
            "use_mov_multiplier": bool(self.use_mov_multiplier)
        }


class EloResearchEngine:
    """
    Leakage-safe dynamic Elo rating system for research experiments.
    Chronologically updates ratings pregame-to-postgame.
    Does not mutate production EloService constants.
    """

    @staticmethod
    def get_win_probability(home_elo: float, away_elo: float, home_advantage: float = 35.0) -> float:
        """Calculates home win probability given home/away Elo ratings and home advantage."""
        dr = (home_elo + home_advantage) - away_elo
        return 1.0 / (1.0 + math.pow(10.0, -dr / 400.0))

    @staticmethod
    def calculate_margin_multiplier(
        home_score: int,
        away_score: int,
        elo_diff: float,
        use_mov_multiplier: bool = True
    ) -> float:
        """
        Calculates margin-of-victory multiplier M.
        Formula: M = (abs(goal_diff) + 3)^0.8 / (7.5 + 0.006 * max(winner_elo_diff, 0))
        If use_mov_multiplier is False, returns 1.0.
        """
        if not use_mov_multiplier:
            return 1.0

        goal_diff = abs(home_score - away_score)
        if goal_diff <= 0:
            return 1.0

        winner_elo_diff = elo_diff if home_score > away_score else -elo_diff
        multiplier = math.pow(goal_diff + 3.0, 0.8) / (7.5 + 0.006 * max(0.0, winner_elo_diff))
        return max(1.0, multiplier)

    @classmethod
    def update_ratings(
        cls,
        home_elo: float,
        away_elo: float,
        home_score: int,
        away_score: int,
        config: EloResearchConfig
    ) -> Tuple[float, float, float]:
        """
        Updates Elo ratings for home and away teams postgame.
        Returns: (new_home_elo, new_away_elo, p_home_win_pregame)
        """
        p_home = cls.get_win_probability(home_elo, away_elo, config.home_advantage)
        actual_home_win = 1.0 if home_score > away_score else (0.0 if away_score > home_score else 0.5)

        elo_diff = (home_elo + config.home_advantage) - away_elo
        m_mult = cls.calculate_margin_multiplier(home_score, away_score, elo_diff, config.use_mov_multiplier)

        shift = config.k_factor * m_mult * (actual_home_win - p_home)

        new_home = home_elo + shift
        new_away = away_elo - shift
        return new_home, new_away, p_home

    @classmethod
    def run_elo_backtest(
        cls,
        seasons: List[str],
        config: EloResearchConfig,
        initial_ratings: Optional[Dict[int, float]] = None,
        games_override: Optional[List[Any]] = None
    ) -> Dict[str, Any]:
        """
        Runs a chronological out-of-time Elo backtest across given seasons using config parameters.
        Guarantees zero future leakage by evaluating pregame win probability prior to updating rating.
        """
        team_ratings: Dict[int, float] = initial_ratings.copy() if initial_ratings else {}
        predictions = []
        season_metrics = {}

        for season_idx, season in enumerate(seasons):
            # Regress ratings toward mean between seasons
            if season_idx > 0:
                for tid in list(team_ratings.keys()):
                    team_ratings[tid] = (1.0 - config.season_regression) * team_ratings[tid] + config.season_regression * config.initial_elo

            if games_override is not None:
                games = [g for g in games_override if getattr(g, "season", None) == season]
            else:
                games = Game.query.filter(
                    Game.season == season,
                    Game.game_type == 'R',
                    Game.data_source == 'nhl_api',
                    Game.nhl_game_state.in_(['OFF', 'FINAL', 'OVER'])
                ).order_by(
                    func.coalesce(Game.start_time_utc, Game.game_date).asc(),
                    Game.game_id.asc()
                ).all()

            season_preds = []

            for g in games:
                h_id = g.home_team_id
                a_id = g.away_team_id
                home_elo = team_ratings.get(h_id, config.initial_elo)
                away_elo = team_ratings.get(a_id, config.initial_elo)

                # Pregame win probability prior to result update
                p_home = cls.get_win_probability(home_elo, away_elo, config.home_advantage)
                actual_home_win = 1 if g.home_score > g.away_score else 0

                season_preds.append({
                    "game_id": g.game_id,
                    "season": g.season,
                    "game_date": g.game_date.strftime("%Y-%m-%d") if hasattr(g.game_date, "strftime") else str(g.game_date),
                    "home_team_id": h_id,
                    "away_team_id": a_id,
                    "home_elo_pregame": round(home_elo, 1),
                    "away_elo_pregame": round(away_elo, 1),
                    "elo_diff_pregame": round((home_elo + config.home_advantage) - away_elo, 1),
                    "p_home_win": p_home,
                    "actual_home_win": actual_home_win,
                    "home_score": g.home_score,
                    "away_score": g.away_score
                })

                # Postgame Elo update
                new_home, new_away, _ = cls.update_ratings(
                    home_elo, away_elo, g.home_score, g.away_score, config
                )
                team_ratings[h_id] = new_home
                team_ratings[a_id] = new_away

            predictions.extend(season_preds)
            if season_preds:
                metrics = cls.evaluate_predictions(season_preds)
                season_metrics[season] = metrics

        overall_metrics = cls.evaluate_predictions(predictions) if predictions else {}

        return {
            "config": config.to_dict(),
            "config_hash": config.compute_config_hash(),
            "predictions_count": len(predictions),
            "final_ratings": {tid: round(r, 1) for tid, r in team_ratings.items()},
            "season_metrics": season_metrics,
            "overall_metrics": overall_metrics,
            "predictions": predictions,
            "sample_predictions": predictions[:10]
        }

    @classmethod
    def evaluate_predictions(cls, predictions: List[Dict[str, Any]]) -> Dict[str, float]:
        """
        Evaluates predictions against ground truth outcomes.
        Calculates Log Loss, Brier Score, Accuracy, and ECE.
        """
        if not predictions:
            return {"log_loss": 0.0, "brier_score": 0.0, "accuracy": 0.0, "ece": 0.0}

        eps = 1e-15
        total_ll = 0.0
        total_brier = 0.0
        correct = 0

        y_true = []
        y_prob = []

        for p in predictions:
            prob = max(eps, min(1.0 - eps, p["p_home_win"]))
            actual = p["actual_home_win"]

            # Log loss
            ll = -(actual * math.log(prob) + (1.0 - actual) * math.log(1.0 - prob))
            total_ll += ll

            # Brier score
            brier = (prob - actual) ** 2
            total_brier += brier

            # Accuracy
            pred_class = 1 if prob >= 0.5 else 0
            if pred_class == actual:
                correct += 1

            y_true.append(actual)
            y_prob.append(prob)

        n = len(predictions)
        ece = cls.calculate_ece(y_true, y_prob, n_bins=10)

        return {
            "log_loss": round(total_ll / n, 4),
            "brier_score": round(total_brier / n, 4),
            "accuracy": round((correct / n) * 100.0, 2),
            "ece": round(ece, 4)
        }

    @staticmethod
    def calculate_ece(y_true: List[int], y_prob: List[float], n_bins: int = 10) -> float:
        """Calculates Expected Calibration Error (ECE) across n_bins probability buckets."""
        if not y_true:
            return 0.0

        bin_boundaries = [i / n_bins for i in range(n_bins + 1)]
        ece = 0.0
        n_samples = len(y_true)

        for i in range(n_bins):
            bin_lower = bin_boundaries[i]
            bin_upper = bin_boundaries[i + 1]

            bin_indices = [
                idx for idx, p in enumerate(y_prob)
                if (p >= bin_lower and p < bin_upper) or (i == n_bins - 1 and p == bin_upper)
            ]

            if bin_indices:
                bin_prob_avg = sum(y_prob[idx] for idx in bin_indices) / len(bin_indices)
                bin_true_avg = sum(y_true[idx] for idx in bin_indices) / len(bin_indices)
                bin_weight = len(bin_indices) / n_samples
                ece += bin_weight * abs(bin_prob_avg - bin_true_avg)

        return ece


def run_elo_parameter_grid_search(
    seasons: List[str],
    k_factors: Optional[List[float]] = None,
    home_advantages: Optional[List[float]] = None,
    season_regressions: Optional[List[float]] = None,
    use_mov_options: Optional[List[bool]] = None,
    initial_elo: float = 1500.0,
    games_override: Optional[List[Any]] = None
) -> List[Dict[str, Any]]:
    """
    Runs a bounded parameter research study over candidate Elo parameter combinations.
    Ranks candidates by primary selection metric (Log Loss) on specified dev/selection seasons.
    """
    if k_factors is None:
        k_factors = [10.0, 15.0, 20.0, 25.0, 30.0]
    if home_advantages is None:
        home_advantages = [20.0, 35.0, 50.0, 65.0]
    if season_regressions is None:
        season_regressions = [0.10, 0.25, 0.40]
    if use_mov_options is None:
        use_mov_options = [True, False]

    candidates_results = []

    for k in k_factors:
        for ha in home_advantages:
            for reg in season_regressions:
                for mov in use_mov_options:
                    cfg = EloResearchConfig(
                        initial_elo=initial_elo,
                        k_factor=k,
                        home_advantage=ha,
                        season_regression=reg,
                        use_mov_multiplier=mov
                    )
                    res = EloResearchEngine.run_elo_backtest(seasons, cfg, games_override=games_override)
                    candidates_results.append({
                        "config": cfg.to_dict(),
                        "config_hash": cfg.compute_config_hash(),
                        "seasons": seasons,
                        "sample_count": res["predictions_count"],
                        "log_loss": res["overall_metrics"].get("log_loss", 999.0),
                        "brier_score": res["overall_metrics"].get("brier_score", 999.0),
                        "accuracy": res["overall_metrics"].get("accuracy", 0.0),
                        "ece": res["overall_metrics"].get("ece", 999.0),
                        "season_metrics": res["season_metrics"]
                    })

    # Rank candidates by Log Loss ascending
    candidates_results.sort(key=lambda c: c["log_loss"])
    return candidates_results
