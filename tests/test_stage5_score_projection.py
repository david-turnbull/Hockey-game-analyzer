import pytest
import hashlib
from pathlib import Path
from app.analytics.forecasting.score_projection import PoissonScoreModel

EXPECTED_WIN_MODEL_SHA = "63cf3cec7d11b38004c590503c89b0a686ae4a9a350fd497bc93087e71bf58f9"

def test_frozen_win_model_sha256():
    model_path = Path("models/forecasting/pucklens-win-v1.4.0.pkl")
    assert model_path.exists(), "Win model artifact missing"
    with open(model_path, "rb") as f:
        actual_sha = hashlib.sha256(f.read()).hexdigest()
    assert actual_sha == EXPECTED_WIN_MODEL_SHA, f"Win model SHA mismatch: {actual_sha}"

def test_adaptive_matrix_support_mass():
    # Test for standard expected goals
    lmbda_h, lmbda_a = 3.2, 2.8
    matrix = PoissonScoreModel.generate_joint_matrix(lmbda_h, lmbda_a, model_type="poisson", max_goals=15)
    total_mass = sum(matrix[h][a] for h in range(15) for a in range(15))
    assert total_mass > 0.99999, f"Probability mass truncation detected: total_mass={total_mass}"

def test_score_projection_display_matrix_structure():
    sample_features = {
        "home_l10_gf_per_game": 3.2,
        "home_l10_ga_per_game": 2.5,
        "away_l10_gf_per_game": 2.8,
        "away_l10_ga_per_game": 3.1,
        "home_is_b2b": 0,
        "away_is_b2b": 0
    }
    proj = PoissonScoreModel.project_score_distribution(sample_features, max_goals=15, display_max_goals=10)
    
    assert "disclaimer_label" in proj
    assert proj["total_probability_mass"] > 0.99999
    assert len(proj["score_matrix"]) == 10
    assert len(proj["score_matrix"][0]) == 10
    
    # 3-class regulation outcomes sum
    sum_3class = proj["home_win_probability_regulation"] + proj["away_win_probability_regulation"] + proj["regulation_tie_probability"]
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

def test_shootout_target_deduction():
    # Shootout home win: boxscore 4-3
    box_h, box_a = 4, 3
    # Subtract 1 shootout goal from winner
    reg_h = box_h - 1
    reg_a = box_a
    assert reg_h == reg_a == 3
    
    # Shootout away win: boxscore 2-3
    box_h, box_a = 2, 3
    reg_h = box_h
    reg_a = box_a - 1
    assert reg_h == reg_a == 2
