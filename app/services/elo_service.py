import math
import logging
from typing import Dict, List, Any, Tuple, Optional
from sqlalchemy import func
from app.models import db, Game, Team

logger = logging.getLogger(__name__)

INITIAL_ELO = 1500.0
BASE_K = 20.0
HOME_ADVANTAGE = 35.0
SEASON_REGRESSION = 0.25  # 25% regression to mean between seasons

class EloService:
    """
    Leakage-safe dynamic Elo rating system for NHL game win probabilities.
    Includes home-ice advantage, margin-of-victory adjustment, and season-to-season regression.
    """

    @staticmethod
    def get_win_probability(home_elo: float, away_elo: float, home_advantage: float = HOME_ADVANTAGE) -> float:
        """
        Calculates home team win probability based on current Elo ratings.
        """
        dr = (home_elo + home_advantage) - away_elo
        return 1.0 / (1.0 + math.pow(10.0, -dr / 400.0))

    @staticmethod
    def calculate_margin_multiplier(home_score: int, away_score: int, elo_diff: float) -> float:
        """
        Calculates margin-of-victory multiplier M.
        Formula: M = (abs(goal_diff) + 3)^0.8 / (7.5 + 0.006 * max(elo_diff, 0))
        """
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
        k_factor: float = BASE_K,
        home_advantage: float = HOME_ADVANTAGE
    ) -> Tuple[float, float, float]:
        """
        Updates Elo ratings for home and away teams postgame.
        Returns: (new_home_elo, new_away_elo, home_win_probability_pregame)
        """
        p_home = cls.get_win_probability(home_elo, away_elo, home_advantage)
        actual_home_win = 1.0 if home_score > away_score else (0.0 if away_score > home_score else 0.5)

        elo_diff = (home_elo + home_advantage) - away_elo
        m_mult = cls.calculate_margin_multiplier(home_score, away_score, elo_diff)

        shift = k_factor * m_mult * (actual_home_win - p_home)

        new_home_elo = home_elo + shift
        new_away_elo = away_elo - shift
        return new_home_elo, new_away_elo, p_home

    @classmethod
    def run_elo_backtest(
        cls,
        seasons: List[str],
        initial_ratings: Optional[Dict[int, float]] = None
    ) -> Dict[str, Any]:
        """
        Runs a full chronological out-of-time Elo backtest across given seasons.
        Guarantees zero future leakage by evaluating pregame win probability prior to updating rating.
        """
        team_ratings: Dict[int, float] = initial_ratings.copy() if initial_ratings else {}

        predictions = []
        season_metrics = {}

        for season_idx, season in enumerate(seasons):
            # Regress ratings between seasons
            if season_idx > 0:
                for tid in list(team_ratings.keys()):
                    team_ratings[tid] = (1.0 - SEASON_REGRESSION) * team_ratings[tid] + SEASON_REGRESSION * INITIAL_ELO

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
                home_elo = team_ratings.get(g.home_team_id, INITIAL_ELO)
                away_elo = team_ratings.get(g.away_team_id, INITIAL_ELO)

                # Pregame evaluation prior to result update
                p_home = cls.get_win_probability(home_elo, away_elo)
                actual_home_win = 1 if g.home_score > g.away_score else 0

                season_preds.append({
                    "game_id": g.game_id,
                    "season": g.season,
                    "game_date": g.game_date.strftime("%Y-%m-%d"),
                    "home_team_id": g.home_team_id,
                    "away_team_id": g.away_team_id,
                    "home_elo_pregame": round(home_elo, 1),
                    "away_elo_pregame": round(away_elo, 1),
                    "p_home_win": p_home,
                    "actual_home_win": actual_home_win,
                    "home_score": g.home_score,
                    "away_score": g.away_score
                })

                # Postgame Elo update
                new_home, new_away, _ = cls.update_ratings(home_elo, away_elo, g.home_score, g.away_score)
                team_ratings[g.home_team_id] = new_home
                team_ratings[g.away_team_id] = new_away

            predictions.extend(season_preds)

            # Calculate season metrics
            if season_preds:
                metrics = cls.evaluate_predictions(season_preds)
                season_metrics[season] = metrics

        overall_metrics = cls.evaluate_predictions(predictions) if predictions else {}

        return {
            "predictions_count": len(predictions),
            "final_ratings": {tid: round(r, 1) for tid, r in team_ratings.items()},
            "season_metrics": season_metrics,
            "overall_metrics": overall_metrics,
            "sample_predictions": predictions[:10]
        }

    @classmethod
    def evaluate_predictions(cls, predictions: List[Dict[str, Any]]) -> Dict[str, float]:
        """
        Evaluates predictions against ground truth outcomes.
        Calculates Log Loss, Brier Score, Accuracy, and Expected Calibration Error (ECE).
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

            # Log loss: -[y*log(p) + (1-y)*log(1-p)]
            ll = -(actual * math.log(prob) + (1.0 - actual) * math.log(1.0 - prob))
            total_ll += ll

            # Brier score: (p - y)^2
            brier = (prob - actual) ** 2
            total_brier += brier

            # Accuracy (threshold 0.5)
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
        """
        Calculates Expected Calibration Error (ECE) across n_bins probability buckets.
        """
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
