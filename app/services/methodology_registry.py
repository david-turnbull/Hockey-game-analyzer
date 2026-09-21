"""
PuckLens Methodology & Model Registry.

Centralized, testable source of truth describing how PuckLens metrics and production models
are calculated, structured, and interpreted across the application without altering analytical
or forecasting behavior.
"""

from dataclasses import dataclass, asdict
from typing import Dict, List, Any, Optional

@dataclass(frozen=True)
class MetricDefinition:
    """Structured definition for an analytical hockey metric."""
    key: str
    name: str
    category: str
    definition: str
    formula: str
    strength_context: str
    units: str
    interpretation: str
    caveats: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ModelCard:
    """Structured methodology model card for a production PuckLens model."""
    key: str
    name: str
    version: str
    purpose: str
    target_output: str
    features: List[str]
    training_validation_approach: str
    assumptions: List[str]
    limitations: List[str]
    version_info: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# Canonical Metric Definitions Registry
METRIC_REGISTRY: Dict[str, MetricDefinition] = {
    "cf_pct": MetricDefinition(
        key="cf_pct",
        name="Corsi For % (CF%)",
        category="possession_5v5",
        definition="The percentage of all 5v5 shot attempts (goals, saved shots, missed shots, and blocked shots) taken by a player's team while that player is on the ice.",
        formula="CF% = (CF / (CF + CA)) * 100",
        strength_context="5v5 Even Strength On-Ice",
        units="%",
        interpretation="Values above 50.0% indicate the player's team controls the majority of shot attempt volume while the player is on the ice.",
        caveats="Does not differentiate shot quality or distance; subject to score effects (teams trailing in third period generate higher shot volume)."
    ),
    "ff_pct": MetricDefinition(
        key="ff_pct",
        name="Fenwick For % (FF%)",
        category="possession_5v5",
        definition="The percentage of unblocked 5v5 shot attempts (goals, saved shots, and missed shots) taken by a player's team while that player is on the ice.",
        formula="FF% = (FF / (FF + FA)) * 100",
        strength_context="5v5 Even Strength On-Ice",
        units="%",
        interpretation="Values above 50.0% indicate superior unblocked shot attempt possession control. Excludes shot blocks to focus on uninhibited offensive threat.",
        caveats="Excludes shot-blocking skill as a defensive metric; still unweighted by individual shot location or goaltender positioning."
    ),
    "on_ice_xg_pct": MetricDefinition(
        key="on_ice_xg_pct",
        name="On-Ice Expected Goals % (xG%)",
        category="possession_5v5",
        definition="The percentage of total expected goals created vs conceded by a player's team while that player is on the ice at 5v5.",
        formula="xG% = (xGF / (xGF + xGA)) * 100",
        strength_context="5v5 Even Strength On-Ice",
        units="%",
        interpretation="Values above 50.0% indicate the player's team controls quality-weighted scoring chances while on the ice.",
        caveats="Requires robust shot location tracking and spatial xG model attribution; small game samples exhibit higher variance."
    ),
    "xg": MetricDefinition(
        key="xg",
        name="Individual Expected Goals (xG)",
        category="individual_counting",
        definition="The cumulative expected goal probability summed across all unblocked shot attempts taken individually by the player.",
        formula="xG = SUM(p_i) for unblocked shots i",
        strength_context="All Game Situations",
        units="goals",
        interpretation="Higher values indicate a player is generating a large volume of high-probability scoring opportunities.",
        caveats="Evaluates shot opportunity quality based on distance, angle, shot type, and strength; does not account for pre-shot passes or open-net passes."
    ),
    "goals_above_expected": MetricDefinition(
        key="goals_above_expected",
        name="Goals Above Expected (G - xG)",
        category="advanced_efficiency",
        definition="The difference between actual goals scored by a player and their cumulative expected goals (xG). Also referred to as goals_minus_xg.",
        formula="G - xG = Actual Goals - Individual xG",
        strength_context="All Game Situations",
        units="goals",
        interpretation="Positive values indicate elite finishing talent or positive shooting luck; negative values indicate finishing underperformance or bad luck.",
        caveats="High positive values over small samples tend to regress toward the league average shooting conversion rate."
    ),
    "shooting_pct": MetricDefinition(
        key="shooting_pct",
        name="Shooting % (SH%)",
        category="individual_rates",
        definition="The percentage of shots on goal (excluding missed and blocked shots) that resulted in a goal.",
        formula="SH% = (Goals / Shots on Goal) * 100",
        strength_context="All Game Situations",
        units="%",
        interpretation="Career NHL skater average is ~9-10%. Elite goalscorers sustain 14-18% over large multi-season samples.",
        caveats="Highly noisy in small sample sizes; heavily influenced by shot location selection and opponent goaltending."
    ),
    "expected_conversion_pct": MetricDefinition(
        key="expected_conversion_pct",
        name="Expected Conversion % (Exp Conv %)",
        category="advanced_efficiency",
        definition="The expected goal rate per unblocked shot attempt taken by the player.",
        formula="Exp Conv % = (xG / Unblocked Attempts) * 100",
        strength_context="All Game Situations",
        units="%",
        interpretation="Measures average shot selection quality. Higher percentages indicate a player who prioritizes high-danger slot shots over long-range perimeter shots.",
        caveats="Unblocked attempts include missed shots; players taking many low-probability perimeter shots will see lower conversion rates."
    ),
    "goals_per_60": MetricDefinition(
        key="goals_per_60",
        name="Goals per 60 Minutes (G/60)",
        category="individual_rates",
        definition="The rate of goals scored per 60 minutes of total ice time.",
        formula="G/60 = (Goals * 3600) / TOI_seconds",
        strength_context="All Game Situations",
        units="goals/60 min",
        interpretation="Normalizes goal production across different ice time usage levels, enabling fair comparison between top-line and lower-line forwards.",
        caveats="Can be distorted for players with low total ice time; power play ice time artificially inflates overall G/60 rates."
    ),
    "xg_per_60": MetricDefinition(
        key="xg_per_60",
        name="Expected Goals per 60 Minutes (xG/60)",
        category="individual_rates",
        definition="The rate of individual expected goals generated per 60 minutes of total ice time.",
        formula="xG/60 = (xG * 3600) / TOI_seconds",
        strength_context="All Game Situations",
        units="goals/60 min",
        interpretation="Measures a skater's underlying rate of offensive threat generation independent of ice time or short-term shooting luck.",
        caveats="Power play deployment provides significantly higher xG/60 than even strength play."
    )
}


# Production Model Cards Registry
MODEL_CARD_REGISTRY: Dict[str, ModelCard] = {
    "xg": ModelCard(
        key="xg",
        name="PuckLens Expected Goals (xG) Model",
        version="1.4.0",
        purpose="Estimates the probability of an unblocked shot attempt resulting in a goal based on spatial and contextual features.",
        target_output="Goal probability p in range [0.0, 1.0]",
        features=[
            "Shot distance to goal center (feet)",
            "Shot angle relative to net center (degrees)",
            "Shot type (slap shot, wrist shot, backhand, tip-in/deflection)",
            "Game strength state (5v5, 5v4 PP, 4v5 SH, 5v3, etc.)",
            "Empty net indicator (true/false)"
        ],
        training_validation_approach="Trained on historical NHL play-by-play shot data using logistic regression with gradient-boosted candidate benchmarks and out-of-time seasonal cross-validation. Includes a deterministic HeuristicXGModel baseline fallback for uncalibrated boundary conditions.",
        assumptions=[
            "Shot outcomes conditional on spatial location and game context follow independent Bernoulli trials.",
            "Unblocked shot attempts represent all shots with a non-zero probability of reaching the net."
        ],
        limitations=[
            "Does not incorporate real-time pre-shot lateral pass distance (royal road passes) or defender proximity.",
            "Does not track goaltender movement or lateral positioning immediately prior to release."
        ],
        version_info="v1.4.0 Production xG Pipeline. Replaced legacy static weights with calibrated spatial probability curves."
    ),
    "win_probability": ModelCard(
        key="win_probability",
        name="PuckLens Pregame Win Probability Engine",
        version="1.4.0",
        purpose="Predicts pregame win probabilities for home and away teams in upcoming NHL regular season and playoff games.",
        target_output="Pregame Home Win Probability P(Home Win) in range (0.0, 1.0)",
        features=[
            "Pregame Elo rating differential (home - away)",
            "Home ice advantage constant (+35 Elo points)",
            "10-game rolling expected goals share (xG%) differential",
            "Rest day differential and back-to-back schedule fatigue indicators",
            "Starting goaltender Goals Saved Above Expected (GSAx) differential"
        ],
        training_validation_approach="Calibrated binary classification pipeline trained on historical multi-season NHL game outcomes. Validated using strict out-of-time temporal train/test splits to guarantee zero future data leakage.",
        assumptions=[
            "Pregame Elo and rolling 10-game xG trends capture true underlying team strength.",
            "Home venue advantage remains consistent throughout the regular season."
        ],
        limitations=[
            "Last-minute lineup scratches announced immediately before puck drop may not be reflected if starting rosters are unconfirmed.",
            "Does not model mid-game live in-game events after puck drop."
        ],
        version_info="v1.4.0 Pregame Engine. Integrated GSAx goalie adjustments and rolling 10-game xG share features."
    ),
    "score_projection": ModelCard(
        key="score_projection",
        name="PuckLens Bivariate Poisson Score Engine",
        version="1.4.0",
        purpose="Projects expected goals scored by each team, exact score probability matrices, regulation win/tie odds, and over/under total goal distributions.",
        target_output="Expected home goals lambda_home, expected away goals lambda_away, and score probability matrix P(X=x, Y=y)",
        features=[
            "Home team offensive rating (expected goals for per 60)",
            "Away team defensive rating (expected goals allowed per 60)",
            "Home venue advantage goal boost factor",
            "Starting goaltender GSAx goals expectation modifier",
            "Rest and schedule density adjustments"
        ],
        training_validation_approach="Bivariate Poisson distribution fit to historical score distributions, incorporating overtime tie probability adjustments (candidate models optimized via score_candidate_params_v1.4.0.json).",
        assumptions=[
            "Team goal scoring follows a Poisson distribution conditional on expected scoring rates.",
            "Tied games at the end of regulation transition to overtime/shootout resolution rules."
        ],
        limitations=[
            "Empty net goals in final minutes slightly distort pure Poisson tail distributions.",
            "High single-game variance inherent in hockey goal scoring."
        ],
        version_info="v1.4.0 Score Model. Fitted candidate Poisson parameters with zero-inflated overtime tie adjustment."
    ),
    "elo": ModelCard(
        key="elo",
        name="PuckLens Dynamic Team Elo Engine",
        version="1.4.0",
        purpose="Provides a continuous, leakage-safe measure of team quality updated dynamically after every completed NHL game.",
        target_output="Team Elo rating R in range [1200, 1800] (baseline 1500.0)",
        features=[
            "Previous game team Elo rating",
            "Home venue advantage adjustment (+35.0 Elo points)",
            "Actual goal differential (home score - away score)",
            "Margin-of-victory scaling factor M = (diff + 3)^0.8 / (7.5 + 0.006 * max(0, winner_elo_diff))",
            "Off-season mean regression factor (25% regression toward 1500.0 between seasons)"
        ],
        training_validation_approach="Chronological out-of-time backtesting across multi-season datasets. Evaluates pregame win probability prior to updating postgame ratings to eliminate future leakage.",
        assumptions=[
            "Team quality transitions smoothly over time with margin-of-victory adjustments.",
            "Off-season roster turnover is effectively modeled by 25% regression toward the 1500.0 league mean."
        ],
        limitations=[
            "Does not instantly reflect mid-season trade deadline roster overhauls until subsequent games are played.",
            "Does not isolate individual player injuries directly within the team-level rating."
        ],
        version_info="v1.4.0 Leakage-Safe Elo Engine. Optimized margin-of-victory multiplier and inter-season regression."
    )
}


class MethodologyRegistry:
    """Centralized service providing access to PuckLens metric definitions and model cards."""

    @classmethod
    def get_metric(cls, key: str) -> Optional[MetricDefinition]:
        """Retrieves metric definition by key."""
        return METRIC_REGISTRY.get(key)

    @classmethod
    def list_metrics(cls, category: Optional[str] = None) -> List[MetricDefinition]:
        """Lists all metric definitions, optionally filtered by category."""
        metrics = list(METRIC_REGISTRY.values())
        if category:
            metrics = [m for m in metrics if m.category == category]
        return metrics

    @classmethod
    def get_model_card(cls, key: str) -> Optional[ModelCard]:
        """Retrieves model card by key."""
        return MODEL_CARD_REGISTRY.get(key)

    @classmethod
    def list_model_cards(cls) -> List[ModelCard]:
        """Lists all production model cards."""
        return list(MODEL_CARD_REGISTRY.values())

    @classmethod
    def get_all_methodology(cls) -> Dict[str, Any]:
        """Returns full methodology dictionary for API/UI consumers."""
        return {
            "metrics": {key: m.to_dict() for key, m in METRIC_REGISTRY.items()},
            "models": {key: m.to_dict() for key, m in MODEL_CARD_REGISTRY.items()}
        }
