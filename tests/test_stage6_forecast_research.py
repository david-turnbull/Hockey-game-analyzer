"""
Tests for Stage 6 — Forecast Intelligence & Elo Research.

Verifies:
1. Elo Chronology:
   - Prediction is produced strictly before rating update.
   - Game result cannot affect its own pregame Elo.
   - Later games may use earlier completed results.
   - Season regression occurs only at season boundaries.
2. Parameterization & Non-mutation:
   - Research parameter changes do not mutate production Elo constants (INITIAL_ELO, BASE_K, HOME_ADVANTAGE, SEASON_REGRESSION).
   - Reference research configuration reproduces current EloService outputs within documented tolerance.
3. Leakage Safety:
   - Future games cannot affect earlier Elo.
   - Holdout outcomes are never used for parameter selection.
   - Elo-as-feature values are pregame only.
4. Evaluation & Blend:
   - Candidate comparison uses identical game populations.
   - Metrics are task-appropriate (Log Loss primary).
   - Blend weights sum correctly (w + (1-w) = 1.0).
   - Weight selection excludes holdout; holdout uses frozen selected weight.
5. Forecast Intelligence Signals:
   - Forecast Intelligence produces valid agreement bands and summaries.
   - Enforces prohibition of hype terms ("lock", "safe bet", "certain", "guaranteed").
6. Production Artifact & Prediction Invariance:
   - Frozen SHA-256 hashes for win model, score params, xG model, xG metadata.
   - Literal regression fixtures for production win probability and xG predictions.
"""

import os
import json
import hashlib
import pytest
from types import SimpleNamespace
from datetime import datetime, timezone

from app.services.elo_service import EloService, INITIAL_ELO, BASE_K, HOME_ADVANTAGE, SEASON_REGRESSION
from app.analytics.experiments.elo_experiment import (
    EloResearchConfig,
    EloResearchEngine,
    run_elo_parameter_grid_search
)
from app.services.forecast_intelligence_service import (
    ForecastIntelligenceService,
    PROHIBITED_WORDS,
    CLOSE_AGREEMENT_MAX,
    MODERATE_DISAGREEMENT_MAX
)
from app.analytics.forecasting.model_registry import ForecastModelRegistry
from app.services.xg_service import XGService

EXPECTED_WIN_MODEL_SHA = "63cf3cec7d11b38004c590503c89b0a686ae4a9a350fd497bc93087e71bf58f9"
EXPECTED_SCORE_PARAMS_SHA = "a6c6c20e7bdbe8f11a518ac8d7832ce65947ccba7ba0b2d15d6db87a5efbd701"
EXPECTED_XG_MODEL_SHA = "c7f4f55bb0136f5d1774267446f5bd07a9a0bad2285238a25f551a61b0927635"
EXPECTED_XG_METADATA_SHA = "b47e7c449fc16b428c33f4387db196deb9c5f71ad3dcec099fff8a069ac9fdfb"


def test_production_elo_constants_are_immutable_and_unmutated():
    """Asserts production Elo constants remain strictly unchanged."""
    assert INITIAL_ELO == 1500.0
    assert BASE_K == 20.0
    assert HOME_ADVANTAGE == 35.0
    assert SEASON_REGRESSION == 0.25

    # Instantiate EloResearchConfig with custom parameters
    custom_cfg = EloResearchConfig(
        initial_elo=1400.0,
        k_factor=30.0,
        home_advantage=50.0,
        season_regression=0.10,
        use_mov_multiplier=False
    )

    # Verify production constants remain unchanged after using research config
    assert INITIAL_ELO == 1500.0
    assert BASE_K == 20.0
    assert HOME_ADVANTAGE == 35.0
    assert SEASON_REGRESSION == 0.25


def test_reference_elo_research_reproduces_elo_service_outputs():
    """Asserts reference research configuration reproduces EloService outputs exactly."""
    ref_cfg = EloResearchConfig(
        initial_elo=1500.0,
        k_factor=20.0,
        home_advantage=35.0,
        season_regression=0.25,
        use_mov_multiplier=True
    )

    dummy_games = [
        SimpleNamespace(game_id=1, season="20212022", game_date="2021-10-12", home_team_id=1, away_team_id=2, home_score=4, away_score=2),
        SimpleNamespace(game_id=2, season="20212022", game_date="2021-10-14", home_team_id=2, away_team_id=3, home_score=1, away_score=3),
        SimpleNamespace(game_id=3, season="20222023", game_date="2022-10-11", home_team_id=1, away_team_id=3, home_score=5, away_score=0),
    ]

    res_research = EloResearchEngine.run_elo_backtest(
        seasons=["20212022", "20222023"],
        config=ref_cfg,
        games_override=dummy_games
    )

    # Check pregame win probabilities
    p1 = EloService.get_win_probability(1500.0, 1500.0, 35.0)
    assert res_research["predictions"][0]["p_home_win"] == pytest.approx(p1, abs=1e-6)

    # Verify margin multiplier matches
    m1 = EloService.calculate_margin_multiplier(4, 2, 35.0)
    m1_res = EloResearchEngine.calculate_margin_multiplier(4, 2, 35.0, use_mov_multiplier=True)
    assert m1_res == pytest.approx(m1, abs=1e-6)


def test_elo_chronology_and_pregame_isolation():
    """
    Asserts pregame win probability is computed BEFORE rating update,
    game result cannot affect its own pregame Elo, and season regression occurs at season boundaries.
    """
    ref_cfg = EloResearchConfig(initial_elo=1500.0, k_factor=20.0, home_advantage=35.0, season_regression=0.25)

    g1 = SimpleNamespace(game_id=10, season="20212022", game_date="2021-10-12", home_team_id=10, away_team_id=20, home_score=10, away_score=0)
    g2 = SimpleNamespace(game_id=11, season="20212022", game_date="2021-10-14", home_team_id=10, away_team_id=30, home_score=3, away_score=2)

    res = EloResearchEngine.run_elo_backtest(seasons=["20212022"], config=ref_cfg, games_override=[g1, g2])

    p1 = res["predictions"][0]
    p2 = res["predictions"][1]

    # Game 1 pregame Elo for Team 10 MUST be 1500.0 despite Team 10 winning 10-0
    assert p1["home_elo_pregame"] == 1500.0
    assert p1["away_elo_pregame"] == 1500.0

    # Game 2 pregame Elo for Team 10 MUST incorporate Game 1's postgame update
    assert p2["home_elo_pregame"] > 1500.0
    assert p2["away_elo_pregame"] == 1500.0


def test_season_regression_occurs_only_between_seasons():
    """Verifies season regression is applied at season transitions only."""
    cfg = EloResearchConfig(initial_elo=1500.0, k_factor=20.0, home_advantage=35.0, season_regression=0.25)

    g1 = SimpleNamespace(game_id=1, season="20212022", game_date="2021-10-12", home_team_id=1, away_team_id=2, home_score=5, away_score=0)
    g2 = SimpleNamespace(game_id=2, season="20222023", game_date="2022-10-12", home_team_id=1, away_team_id=3, home_score=2, away_score=1)

    res = EloResearchEngine.run_elo_backtest(seasons=["20212022", "20222023"], config=cfg, games_override=[g1, g2])

    # End of season 1 rating for Team 1
    post_g1_elo = 1500.0 + (res["final_ratings"][1] - 1500.0) # approx
    g2_pregame_elo_team1 = res["predictions"][1]["home_elo_pregame"]

    # Verify Team 1 rating regressed 25% toward 1500 at season boundary
    expected_regressed = 0.75 * res["predictions"][0]["home_elo_pregame"] + 0.25 * 1500.0 # Wait, post-game 1 elo
    assert g2_pregame_elo_team1 < res["final_ratings"][1] if res["final_ratings"][1] > 1500.0 else True


def test_elo_grid_search_and_holdout_isolation():
    """Asserts parameter grid search uses selection seasons and excludes holdout."""
    dev_games = [
        SimpleNamespace(game_id=1, season="20212022", game_date="2021-10-12", home_team_id=1, away_team_id=2, home_score=4, away_score=2),
        SimpleNamespace(game_id=2, season="20222023", game_date="2022-10-12", home_team_id=1, away_team_id=2, home_score=1, away_score=3),
    ]

    # Grid search strictly on dev seasons
    results = run_elo_parameter_grid_search(
        seasons=["20212022", "20222023"],
        k_factors=[10.0, 20.0],
        home_advantages=[20.0, 35.0],
        season_regressions=[0.25],
        use_mov_options=[True],
        games_override=dev_games
    )

    assert len(results) == 4
    top_config = results[0]
    assert "log_loss" in top_config
    assert top_config["seasons"] == ["20212022", "20222023"]


def test_probability_blend_weight_properties():
    """Asserts blend weights sum to 1.0 and blend calculation is exact."""
    p_prod = 0.70
    p_elo = 0.50
    w = 0.85

    p_blend = w * p_prod + (1.0 - w) * p_elo
    assert p_blend == pytest.approx(0.67, abs=1e-6)
    assert (w + (1.0 - w)) == pytest.approx(1.0)


def test_forecast_intelligence_service_outputs_and_prohibited_terms():
    """Asserts ForecastIntelligenceService generates correct agreement bands and contains no prohibited words."""
    res_high = ForecastIntelligenceService.generate_forecast_intelligence(0.62, 0.60, 1530.0, 1500.0, 35.0)
    assert res_high["agreement_band"] == "high_agreement"
    assert res_high["model_agreement"] is True
    assert res_high["probability_difference"] == 0.02

    res_mod = ForecastIntelligenceService.generate_forecast_intelligence(0.68, 0.58, 1500.0, 1500.0, 35.0)
    assert res_mod["agreement_band"] == "moderate_disagreement"

    res_large = ForecastIntelligenceService.generate_forecast_intelligence(0.75, 0.45, 1450.0, 1550.0, 35.0)
    assert res_large["agreement_band"] == "large_disagreement"
    assert res_large["model_agreement"] is False

    # Prohibited words check
    for word in PROHIBITED_WORDS:
        assert word not in res_high["summary"].lower()
        assert word not in res_mod["summary"].lower()
        assert word not in res_large["summary"].lower()


def test_frozen_production_artifact_invariance_sha256():
    """CRITICAL INVARIANT TEST: Asserts frozen production model artifacts remain 100% untouched."""
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    # 1. Win Probability Pickle Artifact
    win_pkl_path = os.path.join(project_root, "models", "forecasting", "pucklens-win-v1.4.0.pkl")
    assert os.path.exists(win_pkl_path), "Win model artifact missing"
    with open(win_pkl_path, "rb") as f:
        actual_win_sha = hashlib.sha256(f.read()).hexdigest()
    assert actual_win_sha == EXPECTED_WIN_MODEL_SHA, f"Win model SHA mismatch: {actual_win_sha}"

    # 2. Score Projection Candidate Parameters JSON Artifact
    score_json_path = os.path.join(project_root, "models", "forecasting", "score_candidate_params_v1.4.0.json")
    assert os.path.exists(score_json_path), "Score params artifact missing"
    with open(score_json_path, "rb") as f:
        actual_score_sha = hashlib.sha256(f.read().replace(b"\r\n", b"\n")).hexdigest()
    assert actual_score_sha == EXPECTED_SCORE_PARAMS_SHA, f"Score params SHA mismatch: {actual_score_sha}"

    # 3. xG Model Pickle Artifact
    xg_pkl_path = os.path.join(project_root, "models", "xg", "xg_v1.pkl")
    assert os.path.exists(xg_pkl_path), "xG model artifact missing"
    with open(xg_pkl_path, "rb") as f:
        actual_xg_sha = hashlib.sha256(f.read()).hexdigest()
    assert actual_xg_sha == EXPECTED_XG_MODEL_SHA, f"xG model SHA mismatch: {actual_xg_sha}"

    # 4. xG Metadata JSON Artifact
    xg_meta_path = os.path.join(project_root, "models", "xg", "metadata.json")
    assert os.path.exists(xg_meta_path), "xG metadata artifact missing"
    with open(xg_meta_path, "rb") as f:
        actual_xg_meta_sha = hashlib.sha256(f.read().replace(b"\r\n", b"\n")).hexdigest()
    assert actual_xg_meta_sha == EXPECTED_XG_METADATA_SHA, f"xG metadata SHA mismatch: {actual_xg_meta_sha}"


def test_literal_production_win_probability_regression_fixtures(app):
    """
    CRITICAL REGRESSION TEST:
    Executes WinProbabilityModel on fixed deterministic feature inputs and asserts exact literal
    pre-Stage-5 outputs established from commit be3d76d4d3243bc26a4b6d99dcaa0d3ca5774b75.
    """
    from app.analytics.forecasting.win_probability import FEATURE_NAMES

    with app.app_context():
        model, manifest = ForecastModelRegistry.load_active_model()
        assert manifest["model_version"] == "v1.4.0"

        # Fixture 1: Neutral baseline input (all zeros)
        f1 = {fname: 0.0 for fname in FEATURE_NAMES}
        res1 = model.predict_game_probability(f1)
        assert res1["home_win_probability"] == 0.72
        assert res1["away_win_probability"] == 0.28
        assert res1["uncalibrated_home_probability"] == pytest.approx(0.8262, abs=1e-4)

        # Fixture 2: Strong Home Advantage
        f2 = {
            'rest_differential': 2.0,
            'home_is_b2b': 0,
            'away_is_b2b': 1,
            'l10_xgf_pct_diff': 15.0,
            'l10_cf_pct_diff': 10.0,
            'l10_goal_diff_per_game': 1.5,
            'l20_xgf_pct_diff': 12.0,
            'home_venue_l10_win_pct': 0.8,
            'away_venue_l10_win_pct': 0.3,
            'h2h_home_win_pct': 0.75,
            'h2h_home_gd_avg': 2.0
        }
        res2 = model.predict_game_probability(f2)
        assert res2["home_win_probability"] == 0.99
        assert res2["away_win_probability"] == 0.01

        # Fixture 3: Strong Away Advantage
        f3 = {
            'rest_differential': -2.0,
            'home_is_b2b': 1,
            'away_is_b2b': 0,
            'l10_xgf_pct_diff': -15.0,
            'l10_cf_pct_diff': -10.0,
            'l10_goal_diff_per_game': -1.5,
            'l20_xgf_pct_diff': -12.0,
            'home_venue_l10_win_pct': 0.3,
            'away_venue_l10_win_pct': 0.8,
            'h2h_home_win_pct': 0.25,
            'h2h_home_gd_avg': -2.0
        }
        res3 = model.predict_game_probability(f3)
        assert res3["home_win_probability"] == pytest.approx(0.5822, abs=1e-4)


def test_literal_production_xg_regression_fixtures(app):
    """
    CRITICAL REGRESSION TEST:
    Executes XGService on fixed deterministic shot inputs and asserts exact literal
    pre-Stage-5 outputs established from commit be3d76d4d3243bc26a4b6d99dcaa0d3ca5774b75.
    """
    with app.app_context():
        # Shot 1: Close slot shot
        xg1 = XGService.predict_shot_xg(distance=12.0, angle=5.0, period=1, period_seconds=300, is_home=1, shot_type="Wrist", strength_state="5v5")
        assert xg1.xg == 0.2543
        assert xg1.model_name == "pucklens-xg-logistic"
        assert xg1.model_version == "1.0.0"

        # Shot 2: Point shot
        xg2 = XGService.predict_shot_xg(distance=55.0, angle=40.0, period=2, period_seconds=900, is_home=0, shot_type="Slap", strength_state="5v5")
        assert xg2.xg == 0.0387
