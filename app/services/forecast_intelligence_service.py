"""
Forecast Intelligence Service.

Provides transparent, research-layer signal comparisons between PuckLens production forecasts
and Elo-derived probabilities.

Enforces strict presentation guidelines:
- Explicit numerical agreement thresholds.
- Objective, non-sensational summary descriptions.
- Zero hype terms ("lock", "safe bet", "certain", "guaranteed").
"""

import logging
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)

CLOSE_AGREEMENT_MAX = 0.05
MODERATE_DISAGREEMENT_MAX = 0.15

PROHIBITED_WORDS = ["lock", "safe bet", "certain", "guaranteed", "sure thing", "easy win"]


class ForecastIntelligenceService:
    """
    Research-layer representation combining forecasting signals into actionable,
    leakage-safe intelligence metrics.
    """

    CLOSE_AGREEMENT_MAX = CLOSE_AGREEMENT_MAX
    MODERATE_DISAGREEMENT_MAX = MODERATE_DISAGREEMENT_MAX

    @classmethod
    def generate_forecast_intelligence(
        cls,
        p_production: float,
        p_elo: float,
        home_elo: float = 1500.0,
        away_elo: float = 1500.0,
        home_advantage: float = 35.0,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Generates forecast intelligence output for a single game.

        Args:
            p_production: Home win probability from production model (0.0 to 1.0)
            p_elo: Home win probability from Elo model (0.0 to 1.0)
            home_elo: Pregame home team Elo rating
            away_elo: Pregame away team Elo rating
            home_advantage: Home-ice Elo advantage value
            metadata: Optional additional metadata dict (e.g. game_id, team_names)

        Returns:
            Structured forecast intelligence record.
        """
        prob_diff = abs(p_production - p_elo)
        raw_diff = p_production - p_elo
        elo_diff = (home_elo + home_advantage) - away_elo

        prod_pick_home = p_production >= 0.5
        elo_pick_home = p_elo >= 0.5
        model_agreement = (prod_pick_home == elo_pick_home)

        if prob_diff < cls.CLOSE_AGREEMENT_MAX:
            agreement_band = "high_agreement"
            band_desc = f"High agreement (|probability difference| < {cls.CLOSE_AGREEMENT_MAX:.2f})"
        elif prob_diff < cls.MODERATE_DISAGREEMENT_MAX:
            agreement_band = "moderate_disagreement"
            band_desc = f"Moderate disagreement ({cls.CLOSE_AGREEMENT_MAX:.2f} <= |probability difference| < {cls.MODERATE_DISAGREEMENT_MAX:.2f})"
        else:
            agreement_band = "large_disagreement"
            band_desc = f"Large disagreement (|probability difference| >= {cls.MODERATE_DISAGREEMENT_MAX:.2f})"

        # Craft transparent summary text
        summary = (
            f"Production model predicts home win probability {p_production:.1%}, "
            f"while Elo predicts {p_elo:.1%}. {band_desc}."
        )

        # Safety check against prohibited terms
        for word in PROHIBITED_WORDS:
            if word in summary.lower():
                raise ValueError(f"Forecast intelligence generated prohibited term '{word}'")

        res = {
            "production_win_probability": round(p_production, 4),
            "elo_win_probability": round(p_elo, 4),
            "probability_difference": round(prob_diff, 4),
            "raw_difference": round(raw_diff, 4),
            "pregame_elo_differential": round(elo_diff, 1),
            "home_elo_pregame": round(home_elo, 1),
            "away_elo_pregame": round(away_elo, 1),
            "model_agreement": model_agreement,
            "agreement_band": agreement_band,
            "agreement_band_description": band_desc,
            "summary": summary,
            "thresholds": {
                "high_agreement_max": cls.CLOSE_AGREEMENT_MAX,
                "moderate_disagreement_max": cls.MODERATE_DISAGREEMENT_MAX
            }
        }

        if metadata:
            res["metadata"] = metadata

        return res

    @classmethod
    def batch_generate(
        cls,
        records: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Batch processes multiple game forecast records.
        """
        out = []
        for r in records:
            p_prod = r["p_production"]
            p_elo = r["p_elo"]
            h_elo = r.get("home_elo", 1500.0)
            a_elo = r.get("away_elo", 1500.0)
            ha = r.get("home_advantage", 35.0)
            meta = r.get("metadata")
            out.append(cls.generate_forecast_intelligence(p_prod, p_elo, h_elo, a_elo, ha, meta))
        return out
