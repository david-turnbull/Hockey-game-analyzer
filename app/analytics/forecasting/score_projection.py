import math
import logging
from typing import Dict, List, Any, Tuple

logger = logging.getLogger(__name__)

LEAGUE_AVG_GOALS = 3.05
HOME_ATTACK_MULT = 1.08

class PoissonScoreModel:
    """
    Poisson expected score projection model.
    Generates joint score distribution matrices for home and away goals.
    
    Mandatory Label:
    "projected hockey-goal score distribution (excluding shootout bonus)"
    
    Boundary Behavior:
    - alpha == 0.0 collapses Negative Binomial to Independent Poisson.
    - lambda3 == 0.0 collapses Bivariate Poisson to Independent Poisson.
    
    Feature Service Score Target Limitation (Win Model Freezing Constraint):
    PregameFeatureService computes rolling 10-game goals for (l10_gf_per_game) and
    goals against (l10_ga_per_game) using official boxscore scores (Game.home_score/away_score),
    which include the +1 shootout winner goal bonus. Because the production win probability model
    (v1.4.0, SHA 63cf3cec...) is strictly frozen and depends on PregameFeatureService,
    PregameFeatureService is not modified in v1.4 to preserve win model compatibility.
    """

    @staticmethod
    def poisson_pmf(k: int, lmbda: float) -> float:
        """Calculates Poisson probability P(X = k) for mean lmbda."""
        if k < 0 or lmbda <= 0:
            return 0.0
        return (math.pow(lmbda, k) * math.exp(-lmbda)) / math.factorial(k)

    @staticmethod
    def neg_binomial_pmf(k: int, lmbda: float, alpha: float = 0.001) -> float:
        """Calculates Negative Binomial probability P(X = k) for mean lmbda and dispersion alpha."""
        if k < 0 or lmbda <= 0:
            return 0.0
        if alpha <= 1e-6:
            return PoissonScoreModel.poisson_pmf(k, lmbda)
        r = 1.0 / alpha
        p = r / (r + lmbda)
        # P(X = k) = gamma(k + r) / (k! gamma(r)) * p^r * (1-p)^k
        return math.exp(math.lgamma(k + r) - math.lgamma(r) - math.lgamma(k + 1)) * math.pow(p, r) * math.pow(1 - p, k)

    @staticmethod
    def bivariate_poisson_pmf(h: int, a: int, lmbda_h: float, lmbda_a: float, lmbda3: float = 0.001) -> float:
        """Calculates Bivariate Poisson joint probability P(H=h, A=a) with shared intensity lmbda3."""
        if h < 0 or a < 0 or lmbda_h <= 0 or lmbda_a <= 0:
            return 0.0
        lmbda1 = max(1e-4, lmbda_h - lmbda3)
        lmbda2 = max(1e-4, lmbda_a - lmbda3)
        l3 = max(0.0, lmbda3)
        prob = 0.0
        for k in range(min(h, a) + 1):
            term = (math.pow(lmbda1, h - k) / math.factorial(h - k)) * \
                   (math.pow(lmbda2, a - k) / math.factorial(a - k)) * \
                   (math.pow(l3, k) / math.factorial(k))
            prob += term
        return math.exp(-(lmbda1 + lmbda2 + l3)) * prob

    @staticmethod
    def dixon_coles_adj(h: int, a: int, lmbda_h: float, lmbda_a: float, gamma: float = 0.0543) -> float:
        """Dixon-Coles low score adjustment multiplier tau(h, a)."""
        if h == 0 and a == 0:
            return max(0.0, 1.0 - lmbda_h * lmbda_a * gamma)
        elif h == 1 and a == 0:
            return max(0.0, 1.0 + lmbda_a * gamma)
        elif h == 0 and a == 1:
            return max(0.0, 1.0 + lmbda_h * gamma)
        elif h == 1 and a == 1:
            return max(0.0, 1.0 - gamma)
        else:
            return 1.0

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
    def generate_joint_matrix(cls, lmbda_home: float, lmbda_away: float, model_type: str = "poisson", tol: float = 1e-8, max_support_cap: int = 50, **kwargs) -> Tuple[List[List[float]], int, float, float]:
        """
        Generates N x N joint score probability matrix with adaptive support selection and probability normalization.
        
        Step 1: Determine support size N adaptively based on tail probability criteria (omitted tail mass < tol).
        Step 2: Generate raw N x N cell probabilities and calculate raw_total_mass.
        Step 3: Normalize all matrix cells so cell probabilities sum to 1.0 (normalized_total_mass = 1.0).
        
        Returns (normalized_matrix, support_size_N, raw_total_mass, normalized_total_mass).
        """
        N = 10
        # Step 1: Support selection based on tail probability
        while N <= max_support_cap:
            if model_type == "neg_binomial":
                alpha = kwargs.get("alpha", 0.0)
                cdf_h = sum(cls.neg_binomial_pmf(h, lmbda_home, alpha) for h in range(N))
                cdf_a = sum(cls.neg_binomial_pmf(a, lmbda_away, alpha) for a in range(N))
                omitted_tail = 1.0 - (cdf_h * cdf_a)
            elif model_type == "bivariate_poisson":
                lambda3 = kwargs.get("lambda3", 0.0)
                # Compute accumulated joint mass for candidate support N
                accum_mass = sum(cls.bivariate_poisson_pmf(h, a, lmbda_home, lmbda_away, lambda3) for h in range(N) for a in range(N))
                omitted_tail = 1.0 - accum_mass
            else:  # default poisson, dixon_coles
                cdf_h = sum(cls.poisson_pmf(h, lmbda_home) for h in range(N))
                cdf_a = sum(cls.poisson_pmf(a, lmbda_away) for a in range(N))
                omitted_tail = 1.0 - (cdf_h * cdf_a)

            if omitted_tail < tol or N >= max_support_cap:
                break
            N += 1

        # Step 2: Generate raw matrix cell probabilities
        raw_matrix = []
        raw_total_mass = 0.0
        for h in range(N):
            row = []
            for a in range(N):
                if model_type == "neg_binomial":
                    alpha = kwargs.get("alpha", 0.0)
                    p_cell = cls.neg_binomial_pmf(h, lmbda_home, alpha) * cls.neg_binomial_pmf(a, lmbda_away, alpha)
                elif model_type == "bivariate_poisson":
                    lambda3 = kwargs.get("lambda3", 0.0)
                    p_cell = cls.bivariate_poisson_pmf(h, a, lmbda_home, lmbda_away, lambda3)
                elif model_type == "dixon_coles":
                    gamma = kwargs.get("gamma", 0.0543)
                    tau = cls.dixon_coles_adj(h, a, lmbda_home, lmbda_away, gamma)
                    p_cell = tau * cls.poisson_pmf(h, lmbda_home) * cls.poisson_pmf(a, lmbda_away)
                else:  # default poisson
                    p_cell = cls.poisson_pmf(h, lmbda_home) * cls.poisson_pmf(a, lmbda_away)
                row.append(p_cell)
                raw_total_mass += p_cell
            raw_matrix.append(row)

        # Step 3: Normalize cell probabilities so joint sum equals 1.0
        norm_matrix = []
        normalized_total_mass = 0.0
        scale = (1.0 / raw_total_mass) if raw_total_mass > 0 else 1.0
        for h in range(N):
            row_norm = []
            for a in range(N):
                cell_norm = raw_matrix[h][a] * scale
                row_norm.append(cell_norm)
                normalized_total_mass += cell_norm
            norm_matrix.append(row_norm)

        return norm_matrix, N, raw_total_mass, normalized_total_mass

    @classmethod
    def project_score_distribution(cls, pregame_features: Dict[str, Any], display_max_goals: int = 10, model_type: str = "poisson", tol: float = 1e-8, **kwargs) -> Dict[str, Any]:
        """
        Generates score probability matrix and pre-shootout outcome probabilities using adaptive support and normalized probability matrix.
        """
        lmbda_home, lmbda_away = cls.calculate_expected_goals(pregame_features)
        norm_matrix, support_N, raw_total_mass, norm_total_mass = cls.generate_joint_matrix(lmbda_home, lmbda_away, model_type=model_type, tol=tol, **kwargs)

        home_win_prob = 0.0
        away_win_prob = 0.0
        tie_prob = 0.0

        display_matrix = []
        for h in range(support_N):
            if h < display_max_goals:
                row_disp = []
                for a in range(display_max_goals):
                    row_disp.append(round(norm_matrix[h][a], 5))
                display_matrix.append(row_disp)

            for a in range(support_N):
                p_cell = norm_matrix[h][a]
                if h > a:
                    home_win_prob += p_cell
                elif a > h:
                    away_win_prob += p_cell
                else:
                    tie_prob += p_cell

        # Totals Over/Under probabilities for standard lines (5.5, 6.0, 6.5)
        over_under = {}
        for total_line in [5.5, 6.0, 6.5]:
            prob_over = 0.0
            prob_under = 0.0
            prob_push = 0.0

            for h in range(support_N):
                for a in range(support_N):
                    tot = h + a
                    p_cell = norm_matrix[h][a]
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
        for h in range(support_N):
            for a in range(support_N):
                scorelines.append({
                    "score": f"{h}-{a}",
                    "home_goals": h,
                    "away_goals": a,
                    "probability": round(norm_matrix[h][a], 4)
                })

        scorelines.sort(key=lambda x: x["probability"], reverse=True)
        top_scorelines = scorelines[:5]

        return {
            "disclaimer_label": "projected hockey-goal score distribution (excluding shootout bonus)",
            "expected_home_goals": lmbda_home,
            "expected_away_goals": lmbda_away,
            "expected_total_goals": round(lmbda_home + lmbda_away, 2),
            "home_win_probability_pre_shootout": round(home_win_prob, 4),
            "away_win_probability_pre_shootout": round(away_win_prob, 4),
            "shootout_required_probability": round(tie_prob, 4),
            # Compatibility aliases
            "home_win_probability_regulation": round(home_win_prob, 4),
            "away_win_probability_regulation": round(away_win_prob, 4),
            "regulation_tie_probability": round(tie_prob, 4),
            "adaptive_support_N": support_N,
            "raw_total_mass": round(raw_total_mass, 8),
            "total_probability_mass": round(norm_total_mass, 8),
            "score_matrix": display_matrix,
            "top_scorelines": top_scorelines,
            "totals_projections": over_under
        }
