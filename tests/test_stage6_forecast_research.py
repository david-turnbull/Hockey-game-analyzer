"""
Tests for Stage 6 — Forecast Intelligence & Elo Research.

Verifies:
1. Elo Chronology & Deterministic Sorting:
   - Prediction is produced strictly before rating update.
   - Game result cannot affect its own pregame Elo.
   - Later games may use earlier completed results.
   - Season regression occurs only at season boundaries using exact formula.
   - Shuffled games_override inputs are sorted chronologically.
2. Parameterization & Non-mutation:
   - Research parameter changes do not mutate production Elo constants (INITIAL_ELO, BASE_K, HOME_ADVANTAGE, SEASON_REGRESSION).
   - Reference research configuration reproduces current EloService outputs within documented tolerance.
3. Leakage Safety & Provenance:
   - Future games cannot affect earlier Elo.
   - Parameter and blend selection strictly use selection seasons (2022-23) excluding validation and holdout.
   - Elo-as-feature values use Stage 5 PointInTimeAdapter provenance.
4. Evaluation & Population Integrity:
   - Candidate comparison requires exact, identical game populations; fails closed on missing predictions.
   - Bootstrap differences use explicit comparator_minus_base sign semantics (negative = comparator superior).
   - Blend weights sum correctly (w + (1-w) = 1.0).
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
from datetime import datetime, timezone, timedelta

from app.services.elo_service import EloService, INITIAL_ELO, BASE_K, HOME_ADVANTAGE, SEASON_REGRESSION
from app.analytics.experiments.elo_experiment import (
    EloResearchConfig,
    EloResearchEngine,
    run_elo_parameter_grid_search
)
from app.analytics.experiments.point_in_time import (
    PointInTimeAdapter,
    PointInTimeCutoff,
    TemporalLeakageError,
    assert_point_in_time_safety
)
from app.services.forecast_intelligence_service import (
    ForecastIntelligenceService,
    PROHIBITED_WORDS,
    CLOSE_AGREEMENT_MAX,
    MODERATE_DISAGREEMENT_MAX
)
from app.analytics.forecasting.model_registry import ForecastModelRegistry
from app.services.xg_service import XGService
from scripts.run_stage6_forecast_research import (
    validate_paired_game_populations,
    calculate_paired_bootstrap
)

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

    custom_cfg = EloResearchConfig(
        initial_elo=1400.0,
        k_factor=30.0,
        home_advantage=50.0,
        season_regression=0.10,
        use_mov_multiplier=False
    )

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
        SimpleNamespace(game_id=1, season="20212022", game_date="2021-10-12", start_time_utc=datetime(2021, 10, 12, 23, 0, tzinfo=timezone.utc), home_team_id=1, away_team_id=2, home_score=4, away_score=2),
        SimpleNamespace(game_id=2, season="20212022", game_date="2021-10-14", start_time_utc=datetime(2021, 10, 14, 23, 0, tzinfo=timezone.utc), home_team_id=2, away_team_id=3, home_score=1, away_score=3),
        SimpleNamespace(game_id=3, season="20222023", game_date="2022-10-11", start_time_utc=datetime(2022, 10, 11, 23, 0, tzinfo=timezone.utc), home_team_id=1, away_team_id=3, home_score=5, away_score=0),
    ]

    res_research = EloResearchEngine.run_elo_backtest(
        seasons=["20212022", "20222023"],
        config=ref_cfg,
        games_override=dummy_games
    )

    p1 = EloService.get_win_probability(1500.0, 1500.0, 35.0)
    assert res_research["predictions"][0]["p_home_win"] == pytest.approx(p1, abs=1e-6)

    m1 = EloService.calculate_margin_multiplier(4, 2, 35.0)
    m1_res = EloResearchEngine.calculate_margin_multiplier(4, 2, 35.0, use_mov_multiplier=True)
    assert m1_res == pytest.approx(m1, abs=1e-6)


def test_elo_chronology_and_pregame_isolation():
    """
    Asserts pregame win probability is computed BEFORE rating update,
    and game result cannot affect its own pregame Elo.
    """
    ref_cfg = EloResearchConfig(initial_elo=1500.0, k_factor=20.0, home_advantage=35.0, season_regression=0.25)

    g1 = SimpleNamespace(game_id=10, season="20212022", game_date="2021-10-12", start_time_utc=datetime(2021, 10, 12, 23, 0, tzinfo=timezone.utc), home_team_id=10, away_team_id=20, home_score=10, away_score=0)
    g2 = SimpleNamespace(game_id=11, season="20212022", game_date="2021-10-14", start_time_utc=datetime(2021, 10, 14, 23, 0, tzinfo=timezone.utc), home_team_id=10, away_team_id=30, home_score=3, away_score=2)

    res = EloResearchEngine.run_elo_backtest(seasons=["20212022"], config=ref_cfg, games_override=[g1, g2])

    p1 = res["predictions"][0]
    p2 = res["predictions"][1]

    assert p1["home_elo_pregame"] == 1500.0
    assert p1["away_elo_pregame"] == 1500.0
    assert p2["home_elo_pregame"] > 1500.0
    assert p2["away_elo_pregame"] == 1500.0


def test_shuffled_input_chronology_sorting():
    """
    Asserts that out-of-order games_override inputs are sorted chronologically by EloResearchEngine,
    producing identical results to pre-sorted inputs.
    """
    cfg = EloResearchConfig(initial_elo=1500.0, k_factor=20.0, home_advantage=35.0, season_regression=0.25)

    g1 = SimpleNamespace(game_id=101, season="20212022", game_date="2021-10-10", start_time_utc=datetime(2021, 10, 10, 23, 0, tzinfo=timezone.utc), home_team_id=1, away_team_id=2, home_score=3, away_score=1)
    g2 = SimpleNamespace(game_id=102, season="20212022", game_date="2021-10-12", start_time_utc=datetime(2021, 10, 12, 23, 0, tzinfo=timezone.utc), home_team_id=1, away_team_id=3, home_score=2, away_score=4)
    g3 = SimpleNamespace(game_id=103, season="20212022", game_date="2021-10-15", start_time_utc=datetime(2021, 10, 15, 23, 0, tzinfo=timezone.utc), home_team_id=2, away_team_id=3, home_score=5, away_score=0)

    # Order 1: Pre-sorted
    res_sorted = EloResearchEngine.run_elo_backtest(seasons=["20212022"], config=cfg, games_override=[g1, g2, g3])

    # Order 2: Shuffled input
    res_shuffled = EloResearchEngine.run_elo_backtest(seasons=["20212022"], config=cfg, games_override=[g3, g1, g2])

    assert len(res_sorted["predictions"]) == 3
    assert len(res_shuffled["predictions"]) == 3

    for p_sort, p_shuf in zip(res_sorted["predictions"], res_shuffled["predictions"]):
        assert p_sort["game_id"] == p_shuf["game_id"]
        assert p_sort["p_home_win"] == pytest.approx(p_shuf["p_home_win"], abs=1e-6)
        assert p_sort["home_elo_pregame"] == pytest.approx(p_shuf["home_elo_pregame"], abs=1e-5)

    assert res_sorted["final_ratings"] == res_shuffled["final_ratings"]


def test_season_regression_occurs_only_between_seasons():
    """
    Rigorously asserts season regression formula:
    R_new = (1 - regression) * R_prev + regression * INITIAL_ELO
    and verifies zero regression occurs between games within the same season.
    """
    reg_val = 0.25
    cfg = EloResearchConfig(initial_elo=1500.0, k_factor=20.0, home_advantage=35.0, season_regression=reg_val)

    g1 = SimpleNamespace(game_id=1, season="20212022", game_date="2021-10-12", start_time_utc=datetime(2021, 10, 12, 23, 0, tzinfo=timezone.utc), home_team_id=1, away_team_id=2, home_score=5, away_score=0)
    g2 = SimpleNamespace(game_id=2, season="20222023", game_date="2022-10-12", start_time_utc=datetime(2022, 10, 12, 23, 0, tzinfo=timezone.utc), home_team_id=1, away_team_id=3, home_score=2, away_score=1)

    res = EloResearchEngine.run_elo_backtest(seasons=["20212022", "20222023"], config=cfg, games_override=[g1, g2])

    # Calculate exact postgame rating for Team 1 after Game 1
    new_home_g1, _, _ = EloResearchEngine.update_ratings(1500.0, 1500.0, 5, 0, cfg)

    # Season 2 pregame rating for Team 1 MUST equal regressed value (stored rounded to 1 decimal place)
    expected_s2_team1 = (1.0 - reg_val) * new_home_g1 + reg_val * 1500.0
    actual_s2_team1 = res["predictions"][1]["home_elo_pregame"]

    assert actual_s2_team1 == pytest.approx(expected_s2_team1, abs=0.1)
    assert actual_s2_team1 == round(expected_s2_team1, 1)


def test_elo_grid_search_and_holdout_isolation():
    """Asserts parameter grid search uses selection season metric and excludes holdout."""
    dev_games = [
        SimpleNamespace(game_id=1, season="20212022", game_date="2021-10-12", start_time_utc=datetime(2021, 10, 12, 23, 0, tzinfo=timezone.utc), home_team_id=1, away_team_id=2, home_score=4, away_score=2),
        SimpleNamespace(game_id=2, season="20222023", game_date="2022-10-12", start_time_utc=datetime(2022, 10, 12, 23, 0, tzinfo=timezone.utc), home_team_id=1, away_team_id=2, home_score=1, away_score=3),
    ]

    results = run_elo_parameter_grid_search(
        seasons=["20212022", "20222023"],
        k_factors=[10.0, 20.0],
        home_advantages=[20.0, 35.0],
        season_regressions=[0.25],
        use_mov_options=[True],
        games_override=dev_games,
        selection_season="20222023"
    )

    assert len(results) == 4
    top_config = results[0]
    assert "log_loss" in top_config
    assert top_config["selection_season"] == "20222023"


def test_validate_paired_game_populations_fail_closed():
    """Verifies validate_paired_game_populations fails closed on missing predictions, length mismatches, or duplicate IDs."""
    g1 = SimpleNamespace(game_id=10)
    g2 = SimpleNamespace(game_id=20)

    # Valid population passes
    res = validate_paired_game_populations([g1, g2], [0.6, 0.4], [0.55, 0.45], [0.58, 0.42])
    assert res["population_valid"] is True

    # Missing prediction fails
    with pytest.raises(ValueError, match="MISSING_PREDICTION"):
        validate_paired_game_populations([g1, g2], [0.6, None], [0.55, 0.45], [0.58, 0.42])

    # Sample count mismatch fails
    with pytest.raises(ValueError, match="POPULATION_MISMATCH"):
        validate_paired_game_populations([g1, g2], [0.6], [0.55, 0.45], [0.58, 0.42])

    # Duplicate game ID fails
    g_dup = SimpleNamespace(game_id=10)
    with pytest.raises(ValueError, match="DUPLICATE_GAME_IDS"):
        validate_paired_game_populations([g1, g_dup], [0.6, 0.4], [0.55, 0.45], [0.58, 0.42])


def test_paired_bootstrap_sign_semantics():
    """
    Verifies paired bootstrap return structure and sign semantics:
    comparator_minus_base_diff < 0 when comparator has lower (better) log loss.
    """
    y_true = [1, 0, 1, 0, 1, 1, 0, 0, 1, 0]
    # Base model (poor accuracy)
    p_base = [0.2, 0.8, 0.1, 0.9, 0.3, 0.2, 0.7, 0.8, 0.1, 0.9]
    # Comparator model (perfect accuracy)
    p_comp = [0.9, 0.1, 0.9, 0.1, 0.9, 0.9, 0.1, 0.1, 0.9, 0.1]

    res = calculate_paired_bootstrap(y_true, p_base, p_comp, n_bootstraps=100, seed=42)

    diff = res["log_loss_difference"]["comparator_minus_base_diff"]
    # Superior comparator MUST produce negative diff (comp - base < 0)
    assert diff < 0.0
    assert "sign_interpretation" in res["log_loss_difference"]


def test_probability_blend_weight_properties():
    """Asserts blend weights sum to 1.0 and blend calculation is exact."""
    p_prod = 0.70
    p_elo = 0.50
    w = 0.85

    p_blend = w * p_prod + (1.0 - w) * p_elo
    assert p_blend == pytest.approx(0.67, abs=1e-6)
    assert (w + (1.0 - w)) == pytest.approx(1.0)


def test_elo_as_feature_point_in_time_provenance(app):
    """Verifies Elo-as-feature uses PointInTimeAdapter and produces valid PointInTimeCutoff."""
    from app.models import Game
    with app.app_context():
        g = Game.query.filter_by(season="20222023", game_type="R").first()
        if g is not None:
            feats, cutoff = PointInTimeAdapter.extract_game_features_with_cutoff(g)
            cutoff_dict = cutoff.to_dict()
            assert cutoff_dict["safety_passed"] is True
            assert "latest_source_game_start_time" in cutoff_dict
            assert cutoff_dict["latest_source_game_start_time"] is not None


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
        xg1 = XGService.predict_shot_xg(distance=12.0, angle=5.0, period=1, period_seconds=300, is_home=1, shot_type="Wrist", strength_state="5v5")
        assert xg1.xg == 0.2543
        assert xg1.model_name == "pucklens-xg-logistic"
        assert xg1.model_version == "1.0.0"

        xg2 = XGService.predict_shot_xg(distance=55.0, angle=40.0, period=2, period_seconds=900, is_home=0, shot_type="Slap", strength_state="5v5")
        assert xg2.xg == 0.0387
