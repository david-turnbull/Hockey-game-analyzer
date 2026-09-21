"""
PuckLens Metric & Model Methodology Registry.

Centralized, testable source of truth describing how PuckLens metrics and production models
are calculated, structured, and interpreted across the repository without altering any analytical
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
    inputs: List[str]
    strength_context: str
    units: str
    interpretation: str
    caveats: str
    version: str
    references_or_methodology: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ModelCard:
    """Structured methodology model card for a production PuckLens model."""
    key: str
    name: str
    version: str
    purpose: str
    model_type: str
    equation_or_method: str
    target_output: str
    features: List[str]
    evaluation_metrics: Dict[str, Any]
    training_validation_approach: str
    assumptions: List[str]
    limitations: List[str]
    provenance: Dict[str, Any]
    artifact_hash: Optional[str]
    version_info: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# Canonical Metric Definitions Registry (Grounded in repository analytical implementations)
METRIC_REGISTRY: Dict[str, MetricDefinition] = {
    "cf_pct": MetricDefinition(
        key="cf_pct",
        name="Corsi For % (CF%)",
        category="possession_5v5",
        definition="The percentage of all 5v5 shot attempts (goals, saved shots, missed shots, and blocked shots) taken by a player's team while that player is on the ice.",
        formula="CF% = (CF / (CF + CA)) * 100",
        inputs=["cf", "ca"],
        strength_context="5v5 Even Strength On-Ice",
        units="%",
        interpretation="Values above 50.0% indicate the player's team controls the majority of shot attempt volume while the player is on the ice.",
        caveats="Does not differentiate shot quality or distance; subject to score effects (teams trailing in third period generate higher shot volume).",
        version="1.0.0",
        references_or_methodology="Calculated in PlayerSeasonService._aggregate_season_5v5_on_ice and PlayerGameAnalyticsBuilder."
    ),
    "ff_pct": MetricDefinition(
        key="ff_pct",
        name="Fenwick For % (FF%)",
        category="possession_5v5",
        definition="The percentage of unblocked 5v5 shot attempts (goals, saved shots, and missed shots) taken by a player's team while that player is on the ice.",
        formula="FF% = (FF / (FF + FA)) * 100",
        inputs=["ff", "fa"],
        strength_context="5v5 Even Strength On-Ice",
        units="%",
        interpretation="Values above 50.0% indicate superior unblocked shot attempt possession control. Excludes shot blocks to focus on uninhibited offensive threat.",
        caveats="Excludes shot-blocking skill as a defensive metric; still unweighted by individual shot location or goaltender positioning.",
        version="1.0.0",
        references_or_methodology="Calculated in PlayerSeasonService._aggregate_season_5v5_on_ice and PlayerGameAnalyticsBuilder."
    ),
    "on_ice_xg_pct": MetricDefinition(
        key="on_ice_xg_pct",
        name="On-Ice Expected Goals % (xG%)",
        category="possession_5v5",
        definition="The percentage of total expected goals created vs conceded by a player's team while that player is on the ice at 5v5.",
        formula="xG% = (round(xgf, 2) / (round(xgf, 2) + round(xga, 2))) * 100",
        inputs=["xgf_5v5", "xga_5v5"],
        strength_context="5v5 Even Strength On-Ice",
        units="%",
        interpretation="Values above 50.0% indicate the player's team controls quality-weighted scoring chances while on the ice.",
        caveats="Requires robust shot location tracking and spatial xG model attribution; small game samples exhibit higher variance.",
        version="1.4.0",
        references_or_methodology="Calculated in PlayerSeasonService using 2-decimal rounded xGF/xGA sums to preserve public leaderboard ranking semantics."
    ),
    "xg": MetricDefinition(
        key="xg",
        name="Individual Expected Goals (xG)",
        category="individual_counting",
        definition="The cumulative expected goal probability summed across all unblocked shot attempts taken individually by the player.",
        formula="xG = SUM(individual_xg)",
        inputs=["distance", "angle", "shot_type", "strength_state", "empty_net", "time_since_prev_event"],
        strength_context="All Game Situations",
        units="goals",
        interpretation="Higher values indicate a player is generating a large volume of high-probability scoring opportunities.",
        caveats="Evaluates shot opportunity quality based on distance, angle, shot type, and strength; does not account for pre-shot passes across slot.",
        version="1.4.0",
        references_or_methodology="Predicted per shot via ModelRegistry/xg_model pipeline and aggregated in PlayerGameAnalytics."
    ),
    "goals_above_expected": MetricDefinition(
        key="goals_above_expected",
        name="Goals Above Expected (G - xG)",
        category="advanced_efficiency",
        definition="The difference between actual goals scored by a player and their cumulative expected goals (xG). Also referred to as goals_minus_xg or g_minus_xg.",
        formula="G - xG = Goals - round(xG, 2)",
        inputs=["goals", "individual_xg"],
        strength_context="All Game Situations",
        units="goals",
        interpretation="Positive values indicate elite finishing talent or positive shooting luck; negative values indicate finishing underperformance or bad luck.",
        caveats="High positive values over small samples tend to regress toward the league average shooting conversion rate.",
        version="1.4.0",
        references_or_methodology="Calculated in PlayerSeasonService as Goals - round(xG, 2)."
    ),
    "shooting_pct": MetricDefinition(
        key="shooting_pct",
        name="Shooting % (SH%)",
        category="individual_rates",
        definition="The percentage of shots on goal (excluding missed and blocked shots) that resulted in a goal.",
        formula="SH% = (Goals / Shots on Goal) * 100",
        inputs=["goals", "shots_on_goal"],
        strength_context="All Game Situations",
        units="%",
        interpretation="Career NHL skater average is ~9-10%. Elite goalscorers sustain 14-18% over large multi-season samples.",
        caveats="Highly noisy in small sample sizes; heavily influenced by shot location selection and opponent goaltending.",
        version="1.0.0",
        references_or_methodology="Calculated in PlayerSeasonService."
    ),
    "expected_conversion_pct": MetricDefinition(
        key="expected_conversion_pct",
        name="Expected Conversion % (Exp Conv %)",
        category="advanced_efficiency",
        definition="The expected goal rate per unblocked shot attempt taken by the player.",
        formula="Exp Conv % = (round(xG, 2) / Unblocked Attempts) * 100",
        inputs=["individual_xg", "unblocked_attempts"],
        strength_context="All Game Situations",
        units="%",
        interpretation="Measures average shot selection quality. Higher percentages indicate a player who prioritizes high-danger slot shots over long-range perimeter shots.",
        caveats="Unblocked attempts include missed shots; players taking many low-probability perimeter shots will see lower conversion rates.",
        version="1.4.0",
        references_or_methodology="Calculated in PlayerSeasonService using 2-decimal rounded xG."
    ),
    "goals_per_60": MetricDefinition(
        key="goals_per_60",
        name="Goals per 60 Minutes (G/60)",
        category="individual_rates",
        definition="The rate of goals scored per 60 minutes of total ice time.",
        formula="G/60 = (Goals * 3600) / TOI_seconds",
        inputs=["goals", "toi_seconds"],
        strength_context="All Game Situations",
        units="goals/60 min",
        interpretation="Normalizes goal production across different ice time usage levels, enabling fair comparison between top-line and lower-line forwards.",
        caveats="Can be distorted for players with low total ice time; power play ice time artificially inflates overall G/60 rates.",
        version="1.0.0",
        references_or_methodology="Calculated in PlayerSeasonService."
    ),
    "xg_per_60": MetricDefinition(
        key="xg_per_60",
        name="Expected Goals per 60 Minutes (xG/60)",
        category="individual_rates",
        definition="The rate of individual expected goals generated per 60 minutes of total ice time.",
        formula="xG/60 = (round(xG, 2) * 3600) / TOI_seconds",
        inputs=["individual_xg", "toi_seconds"],
        strength_context="All Game Situations",
        units="goals/60 min",
        interpretation="Measures a skater's underlying rate of offensive threat generation independent of ice time or short-term shooting luck.",
        caveats="Power play deployment provides significantly higher xG/60 than even strength play.",
        version="1.4.0",
        references_or_methodology="Calculated in PlayerSeasonService using 2-decimal rounded xG to match SQL leaderboard sort sequence."
    )
}


# Grounded Production Model Cards Registry
MODEL_CARD_REGISTRY: Dict[str, ModelCard] = {
    "xg": ModelCard(
        key="xg",
        name="pucklens-xg-logistic",
        version="1.0.0",
        purpose="Estimates expected goal probability for unblocked shot attempts using spatial and situational event features.",
        model_type="LogisticRegressionXGModel",
        equation_or_method="Logit model P(Goal) = 1 / (1 + exp(-logit_odds)) fitted on 21 features with option_b_train_plus_validation_refit and HeuristicXGModel fallback.",
        target_output="Goal probability p in range [0.0, 1.0]",
        features=[
            "distance", "angle", "period", "period_seconds", "score_differential", "is_home",
            "empty_net", "time_since_prev_event", "distance_from_prev_event", "angle_change",
            "is_rebound", "is_rush", "is_turnover", "is_after_faceoff", "is_lateral_movement",
            "is_power_play", "is_shorthanded", "coordinates_missing", "shot_type",
            "strength_state", "prev_event_type"
        ],
        evaluation_metrics={
            "log_loss": 0.2127,
            "brier_score": 0.0562,
            "roc_auc": 0.7494,
            "expected_goals": 150.27,
            "actual_goals": 147.0,
            "total_shots": 2226
        },
        training_validation_approach="Chronological game-based split (113 train games / 9,860 shots, 24 val games / 2,176 shots, 25 test games / 2,226 shots). Selected Logistic Regression over Gradient Boosting based on lower validation log loss (0.2326 vs 0.2341), followed by refitting on combined train+val sets prior to test set evaluation.",
        assumptions=[
            "Shot outcomes conditional on spatial location and game context follow independent Bernoulli trials.",
            "Unblocked shot attempts represent all shots with a non-zero probability of resulting in a goal."
        ],
        limitations=[
            "Does not track real-time defender proximity or goaltender lateral movement across slot.",
            "Relies on heuristic baseline fallback if trained model artifact is unavailable."
        ],
        provenance={
            "trained_timestamp": "2026-09-07T00:14:59 UTC",
            "git_commit": "2fdde6db17522f61eed5558acfa9a0f1ab305d1b",
            "scikit_learn_version": "1.9.0",
            "platform": "Windows-11"
        },
        artifact_hash=None,  # xG model uses metadata.json without sha256 field
        version_info="v1.0.0 Production xG Pipeline. Model artifact stored at models/xg/xg_v1.pkl with models/xg/metadata.json."
    ),
    "win_probability": ModelCard(
        key="win_probability",
        name="pucklens-win",
        version="v1.4.0",
        purpose="Predicts pregame win probability for home and away teams in regular season NHL games.",
        model_type="HistGradientBoostingClassifier (with isotonic calibration)",
        equation_or_method="Histogram Gradient Boosting Decision Tree fitted on 11 rolling feature differentials and calibrated with isotonic regression.",
        target_output="Pregame Home Win Probability P(Home Win) in range (0.0, 1.0)",
        features=[
            "rest_differential",
            "home_is_b2b",
            "away_is_b2b",
            "l10_xgf_pct_diff",
            "l10_cf_pct_diff",
            "l10_goal_diff_per_game",
            "l20_xgf_pct_diff",
            "home_venue_l10_win_pct",
            "away_venue_l10_win_pct",
            "h2h_home_win_pct",
            "h2h_home_gd_avg"
        ],
        evaluation_metrics={
            "training_samples": 2624,
            "calibration_samples": 1312,
            "selection_metric": "log_loss",
            "calibration_method": "isotonic"
        },
        training_validation_approach="Trained on 20212022 and 20222023 seasons (2,624 games), hyperparameter selection on 20222023, calibrated on 20232024 season (1,312 games), with 20242025 reserved as excluded holdout.",
        assumptions=[
            "Rolling 10-game and 20-game xG% and Corsi% differentials capture relative team form.",
            "Rest differential and back-to-back schedule indicators capture short-term team fatigue."
        ],
        limitations=[
            "Does not directly include live starting goaltender Elo or GSAx ratings in the 11-feature model matrix.",
            "Roster scratches announced immediately prior to puck drop are not dynamically updated if pregame line combinations are fixed."
        ],
        provenance={
            "generated_timestamp": "2026-09-17T01:49:47 UTC",
            "git_commit_sha": "f38f7f90cec9774c05452bd53347bf8a06c05dc2",
            "scikit_learn_version": "1.9.0",
            "run_uuid": "57036064-badb-4fc9-aae7-93b8c5f36676"
        },
        artifact_hash="63cf3cec7d11b38004c590503c89b0a686ae4a9a350fd497bc93087e71bf58f9",
        version_info="v1.4.0 Frozen Win Probability Pipeline. Artifact stored at models/forecasting/pucklens-win-v1.4.0.pkl with SHA256 verification."
    ),
    "score_projection": ModelCard(
        key="score_projection",
        name="PuckLens Score Projection Model",
        version="v1.4.0",
        purpose="Projects expected team goal totals, joint score probability matrices, regulation win/tie odds, and over/under total goal distributions.",
        model_type="Independent Poisson (Production Model)",
        equation_or_method="Independent Poisson P(H=h, A=a) = Poisson(h; lambda_h) * Poisson(a; lambda_a). Evaluated Negative Binomial (alpha=0.0), Bivariate Poisson (lambda3=0.0), and Dixon-Coles (gamma=0.0543) as candidate models.",
        target_output="Expected home goals lambda_home, expected away goals lambda_away, and joint score probability matrix P(X=x, Y=y)",
        features=[
            "home_l10_gf_per_game",
            "home_l10_ga_per_game",
            "away_l10_gf_per_game",
            "away_l10_ga_per_game",
            "home_is_b2b",
            "away_is_b2b"
        ],
        evaluation_metrics={
            "training_samples": 3936,
            "training_seasons": ["20212022", "20222023", "20232024"],
            "dixon_coles_gamma": 0.0543,
            "bivariate_lambda3": 0.0,
            "neg_binomial_alpha": 0.0
        },
        training_validation_approach="Parameters fitted across 3,936 regular season games (20212022 to 20232024). Baseline attack and defense strength multipliers are applied to league average goals (3.05) with home attack multiplier (1.08) and B2B rest penalty (-0.10).",
        assumptions=[
            "Goal scoring events for home and away teams follow independent Poisson distributions conditional on team attack and defense rates.",
            "Official boxscore goal counts include the +1 shootout winner goal bonus for PregameFeatureService compatibility."
        ],
        limitations=[
            "Does not account for late-game empty net goal dynamics in Poisson tail probabilities.",
            "Independent Poisson assumes zero covariance between home and away goal scoring during regulation play."
        ],
        provenance={
            "fitted_at": "2026-09-18T01:57:18 UTC",
            "fitting_git_sha": "e1a492e8d703b1ac85f59d90e79f42c95e5aad6d",
            "training_data_snapshot_hash": "768412e304bd7305003d4577555475353f83fdf5e4dcc20d11085d8c3c7572e3",
            "parameter_payload_sha256": "c1587ea4d9e0fb6c586dd37c8d918cc8338b5488f03945ebbd40f89fa5c28c32",
            "parameter_artifact_file_sha256": "a6c6c20e7bdbe8f11a518ac8d7832ce65947ccba7ba0b2d15d6db87a5efbd701"
        },
        artifact_hash="a6c6c20e7bdbe8f11a518ac8d7832ce65947ccba7ba0b2d15d6db87a5efbd701",
        version_info="v1.4.0 Score Projection Candidate Parameters. Frozen candidate payload at models/forecasting/score_candidate_params_v1.4.0.json."
    ),
    "elo": ModelCard(
        key="elo",
        name="PuckLens Dynamic Elo System",
        version="1.4.0",
        purpose="Provides a continuous, leakage-safe team rating system updated dynamically postgame.",
        model_type="Dynamic Logistic Elo Rating Model",
        equation_or_method="Win prob P(Home) = 1 / (1 + 10^(-(R_home + 35 - R_away)/400)). Rating update shift = K * M * (Actual_Win - P(Home)) where M = (abs(goal_diff) + 3)^0.8 / (7.5 + 0.006 * max(0, winner_elo_diff)). Off-season regression R_new = 0.75 * R_old + 0.25 * 1500.",
        target_output="Team Elo rating R in range [1200, 1800] (baseline 1500.0)",
        features=[
            "home_elo",
            "away_elo",
            "home_score",
            "away_score",
            "is_home_advantage"
        ],
        evaluation_metrics={
            "initial_elo": 1500.0,
            "base_k_factor": 20.0,
            "home_advantage_points": 35.0,
            "season_regression_rate": 0.25
        },
        training_validation_approach="Chronological out-of-time evaluation across multi-season datasets. Guarantees zero future data leakage by recording pregame win probabilities prior to postgame rating updates.",
        assumptions=[
            "Team relative strength follows a logistic distribution with 400-point scale factor.",
            "Off-season team turnover is adequately modeled by 25% regression to the 1500.0 mean."
        ],
        limitations=[
            "Does not incorporate player-level injuries or trade deadline transactions directly into the rating until postgame updates occur.",
            "Does not track player-specific shifts or xG directly within the team rating equation."
        ],
        provenance={
            "service_module": "app.services.elo_service.EloService",
            "constants": "INITIAL_ELO=1500.0, BASE_K=20.0, HOME_ADVANTAGE=35.0, SEASON_REGRESSION=0.25"
        },
        artifact_hash=None,  # Code-defined mathematical service without serialized artifact file
        version_info="v1.4.0 Dynamic Elo Service. Defined in app/services/elo_service.py."
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
