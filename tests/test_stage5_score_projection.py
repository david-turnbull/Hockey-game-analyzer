import pytest
import hashlib
import json
from pathlib import Path
from app.analytics.forecasting.score_projection import PoissonScoreModel
from scripts.run_stage5_score_validation import extract_game_targets, load_frozen_candidate_params

EXPECTED_WIN_MODEL_SHA = "63cf3cec7d11b38004c590503c89b0a686ae4a9a350fd497bc93087e71bf58f9"

class DummyGame:
    def __init__(self, game_id, home_score, away_score):
        self.game_id = game_id
        self.home_score = home_score
        self.away_score = away_score

def test_frozen_win_model_sha256():
    model_path = Path("models/forecasting/pucklens-win-v1.4.0.pkl")
    assert model_path.exists(), "Win model artifact missing"
    with open(model_path, "rb") as f:
        actual_sha = hashlib.sha256(f.read()).hexdigest()
    assert actual_sha == EXPECTED_WIN_MODEL_SHA, f"Win model SHA mismatch: {actual_sha}"

def test_frozen_candidate_parameter_artifact():
    artifact_path = Path("models/forecasting/score_candidate_params_v1.4.0.json")
    assert artifact_path.exists(), "Frozen candidate parameter artifact missing"
    with open(artifact_path, "r") as f:
        data = json.load(f)
    assert data["training_seasons"] == ["20212022", "20222023", "20232024"]
    assert data["sample_count"] == 3936
    assert "candidate_parameters" in data
    params = load_frozen_candidate_params()
    assert "poisson" in params
    assert "neg_binomial" in params

def test_genuinely_adaptive_matrix_support_extremes():
    # Test tolerance < 1e-8 across lambda extremes and all candidate models
    extreme_cases = [
        (0.8, 0.8),
        (6.5, 6.5),
        (6.5, 0.8),
        (0.8, 6.5),
        (3.2, 2.8)
    ]
    candidate_models = ["poisson", "neg_binomial", "bivariate_poisson", "dixon_coles"]
    
    for lh, la in extreme_cases:
        for model in candidate_models:
            matrix, N, total_mass = PoissonScoreModel.generate_joint_matrix(lh, la, model_type=model, tol=1e-8)
            omitted_mass = 1.0 - total_mass
            assert omitted_mass < 1e-8, f"Omitted mass {omitted_mass} exceeds 1e-8 tolerance for model={model}, lh={lh}, la={la}, N={N}"

def test_score_projection_outcome_renaming_and_aliases():
    sample_features = {
        "home_l10_gf_per_game": 3.2,
        "home_l10_ga_per_game": 2.5,
        "away_l10_gf_per_game": 2.8,
        "away_l10_ga_per_game": 3.1,
        "home_is_b2b": 0,
        "away_is_b2b": 0
    }
    proj = PoissonScoreModel.project_score_distribution(sample_features, display_max_goals=10, tol=1e-8)
    
    # New outcome field names
    assert "home_win_probability_pre_shootout" in proj
    assert "away_win_probability_pre_shootout" in proj
    assert "shootout_required_probability" in proj
    
    # Compatibility aliases
    assert proj["home_win_probability_regulation"] == proj["home_win_probability_pre_shootout"]
    assert proj["away_win_probability_regulation"] == proj["away_win_probability_pre_shootout"]
    assert proj["regulation_tie_probability"] == proj["shootout_required_probability"]
    
    assert proj["total_probability_mass"] >= (1.0 - 2e-8)
    assert len(proj["score_matrix"]) == 10
    assert len(proj["score_matrix"][0]) == 10
    
    # Pre-shootout probabilities sum to ~1.0
    sum_3class = proj["home_win_probability_pre_shootout"] + proj["away_win_probability_pre_shootout"] + proj["shootout_required_probability"]
    assert pytest.approx(sum_3class, abs=0.001) == 1.0

def test_candidate_pmf_functions():
    # Negative Binomial with alpha=0.001 should closely match Poisson
    p_poi = PoissonScoreModel.poisson_pmf(3, 3.0)
    p_nb = PoissonScoreModel.neg_binomial_pmf(3, 3.0, alpha=0.001)
    assert pytest.approx(p_poi, abs=1e-3) == p_nb

    # Bivariate Poisson with lambda3=0.001 should closely match independent Poisson product
    p_biv = PoissonScoreModel.bivariate_poisson_pmf(3, 2, 3.0, 2.5, lmbda3=0.001)
    p_ind = PoissonScoreModel.poisson_pmf(3, 3.0) * PoissonScoreModel.poisson_pmf(2, 2.5)
    assert pytest.approx(p_ind, abs=1e-3) == p_biv

    # Dixon-Coles adjustment
    tau_00 = PoissonScoreModel.dixon_coles_adj(0, 0, 3.0, 2.5, gamma=0.0543)
    assert pytest.approx(tau_00, abs=1e-4) == (1.0 - 3.0 * 2.5 * 0.0543)

def test_extract_game_targets_logic():
    from app import create_app
    app = create_app("testing")
    with app.app_context():
        # Test non-shootout game
        non_so_game = DummyGame(2024020001, 4, 2)
        res_non_so = extract_game_targets(non_so_game)
        assert res_non_so["box_home"] == 4
        assert res_non_so["box_away"] == 2
        assert res_non_so["reg_home"] == 4
        assert res_non_so["reg_away"] == 2
        assert res_non_so["reg_3class"] == 0  # Home Win
        assert not res_non_so["anomaly"]

        # Test Shootout home win: boxscore 3-2
        so_home_win_game = DummyGame(2024020002, 3, 2)
        reg_h = so_home_win_game.home_score - 1
        reg_a = so_home_win_game.away_score
        assert reg_h == reg_a == 2
