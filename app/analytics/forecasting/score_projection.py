import math
import logging
from typing import Dict, List, Any, Tuple

logger = logging.getLogger(__name__)

LEAGUE_AVG_GOALS = 3.05
HOME_ATTACK_MULT = 1.08

class PoissonScoreModel:
    """
    Poisson expected score projection model.
    Generates joint score distribution matrices (0..9 x 0..9) for home and away goals.
    
    Mandatory Label:
    "projected hockey-goal score distribution (excluding shootout bonus)"
    """

    @staticmethod
    def poisson_pmf(k: int, lmbda: float) -> float:
        """Calculates Poisson probability P(X = k) for mean lmbda."""
        if k < 0 or lmbda <= 0:
            return 0.0
        return (math.pow(lmbda, k) * math.exp(-lmbda)) / math.factorial(k)

    @classmethod
    def calculate_expected_goals(cls, pregame_features: Dict[str, Any]) -> Tuple[float, float]:
        """
        Calculates expected goals (lambda_home, lambda_away) based on pregame form & rest metrics.
        """
        home_gf = pregame_features.get("home_l10_gf_per_game", LEAGUE_AVG_GOALS)
        home_ga = pregame_features.get("home_l10_ga_per_game", LEAGUE_AVG_GOALS)
        away_gf = pregame_features.get("away_l10_gf_per_game", LEAGUE_AVG_GOALS)
        away_ga = pregame_features.get("away_l10_ga_per_game", LEAGUE_AVG_GOALS)

        # Rest adjustments
        home_rest_adj = -0.10 if pregame_features.get("home_is_b2b", 0) else 0.0
        away_rest_adj = -0.10 if pregame_features.get("away_is_b2b", 0) else 0.0

        # Calculate Attack / Defense Strength ratios
        home_attack = max(0.5, home_gf / LEAGUE_AVG_GOALS)
        home_defense = max(0.5, home_ga / LEAGUE_AVG_GOALS)
        away_attack = max(0.5, away_gf / LEAGUE_AVG_GOALS)
        away_defense = max(0.5, away_ga / LEAGUE_AVG_GOALS)

        lmbda_home = LEAGUE_AVG_GOALS * home_attack * away_defense * HOME_ATTACK_MULT + home_rest_adj
        lmbda_away = LEAGUE_AVG_GOALS * away_attack * home_defense + away_rest_adj

        lmbda_home = max(0.8, min(6.5, round(lmbda_home, 2)))
        lmbda_away = max(0.8, min(6.5, round(lmbda_away, 2)))

        return lmbda_home, lmbda_away

    @classmethod
    def project_score_distribution(cls, pregame_features: Dict[str, Any], max_goals: int = 10) -> Dict[str, Any]:
        """
        Generates 10x10 joint probability matrix and outcome probabilities.
        """
        lmbda_home, lmbda_away = cls.calculate_expected_goals(pregame_features)

        home_pmf = [cls.poisson_pmf(i, lmbda_home) for i in range(max_goals)]
        away_pmf = [cls.poisson_pmf(j, lmbda_away) for j in range(max_goals)]

        # 10x10 Matrix: matrix[home_goals][away_goals]
        matrix = []
        home_win_prob = 0.0
        away_win_prob = 0.0
        tie_prob = 0.0

        total_prob = 0.0

        for h in range(max_goals):
            row = []
            for a in range(max_goals):
                p_cell = home_pmf[h] * away_pmf[a]
                row.append(round(p_cell, 5))
                total_prob += p_cell

                if h > a:
                    home_win_prob += p_cell
                elif a > h:
                    away_win_prob += p_cell
                else:
                    tie_prob += p_cell
            matrix.append(row)

        # Totals Over/Under probabilities for standard lines (5.5, 6.0, 6.5)
        over_under = {}
        for total_line in [5.5, 6.0, 6.5]:
            prob_over = 0.0
            prob_under = 0.0
            prob_push = 0.0

            for h in range(max_goals):
                for a in range(max_goals):
                    tot = h + a
                    p_cell = matrix[h][a]
                    if tot > total_line:
                        prob_over += p_cell
                    elif tot < total_line:
                        prob_under += p_cell
                    else:
                        prob_push += p_cell

            over_under[str(total_line)] = {
                "over": round(prob_over, 4),
                "under": round(prob_under, 4),
                "push": round(prob_push, 4)
            }

        # Most probable exact scorelines
        scorelines = []
        for h in range(max_goals):
            for a in range(max_goals):
                scorelines.append({
                    "score": f"{h}-{a}",
                    "home_goals": h,
                    "away_goals": a,
                    "probability": round(matrix[h][a], 4)
                })

        scorelines.sort(key=lambda x: x["probability"], reverse=True)
        top_scorelines = scorelines[:5]

        return {
            "disclaimer_label": "projected hockey-goal score distribution (excluding shootout bonus)",
            "expected_home_goals": lmbda_home,
            "expected_away_goals": lmbda_away,
            "expected_total_goals": round(lmbda_home + lmbda_away, 2),
            "home_win_probability_regulation": round(home_win_prob, 4),
            "away_win_probability_regulation": round(away_win_prob, 4),
            "regulation_tie_probability": round(tie_prob, 4),
            "score_matrix": matrix,
            "top_scorelines": top_scorelines,
            "totals_projections": over_under
        }
