import pytest
import hashlib
import json
from datetime import date
from pathlib import Path
from app import create_app
from app.models import db, Game, Event, Team
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
    assert "fitting_git_sha" in data
    assert "fitted_at" in data
    assert "training_data_snapshot_hash" in data
    assert "parameter_payload_sha256" in data

    params, meta, file_sha = load_frozen_candidate_params()
    assert "poisson" in params
    assert "neg_binomial" in params
    assert len(file_sha) == 64

def test_genuinely_adaptive_matrix_support_and_normalization():
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
            norm_matrix, N, raw_mass, norm_mass = PoissonScoreModel.generate_joint_matrix(lh, la, model_type=model, tol=1e-8)
            
            # Verify matrix cells sum exactly to 1.0 (within floating point precision)
            sum_norm = sum(norm_matrix[h][a] for h in range(N) for a in range(N))
            assert abs(sum_norm - 1.0) < 1e-8, f"Normalized matrix sum {sum_norm} deviates from 1.0 for model={model}, lh={lh}, la={la}"
            assert abs(norm_mass - 1.0) < 1e-8
            assert raw_mass > 0.95, f"Raw total mass {raw_mass} too low for model={model}"

def test_boundary_collapse_mathematical_equivalences():
    # alpha = 0.0 collapses Negative Binomial to Poisson
    p_poi = PoissonScoreModel.poisson_pmf(3, 3.0)
    p_nb_0 = PoissonScoreModel.neg_binomial_pmf(3, 3.0, alpha=0.0)
    assert p_poi == p_nb_0

    # lambda3 = 0.0 collapses Bivariate Poisson to independent Poisson product
    p_biv_0 = PoissonScoreModel.bivariate_poisson_pmf(3, 2, 3.0, 2.5, lmbda3=0.0)
    p_ind = PoissonScoreModel.poisson_pmf(3, 3.0) * PoissonScoreModel.poisson_pmf(2, 2.5)
    assert pytest.approx(p_ind, abs=1e-12) == p_biv_0

    # Full matrix collapse: NB(alpha=0.0) matches Poisson matrix cell-by-cell
    mat_poi, N1, r1, n1 = PoissonScoreModel.generate_joint_matrix(3.2, 2.8, model_type="poisson", alpha=0.0)
    mat_nb, N2, r2, n2 = PoissonScoreModel.generate_joint_matrix(3.2, 2.8, model_type="neg_binomial", alpha=0.0)
    assert N1 == N2
    for h in range(N1):
        for a in range(N1):
            assert pytest.approx(mat_poi[h][a], abs=1e-12) == mat_nb[h][a]

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
    
    assert proj["total_probability_mass"] == 1.0
    assert len(proj["score_matrix"]) == 10
    assert len(proj["score_matrix"][0]) == 10
    
    # Pre-shootout probabilities sum to 1.0
    sum_3class = proj["home_win_probability_pre_shootout"] + proj["away_win_probability_pre_shootout"] + proj["shootout_required_probability"]
    assert pytest.approx(sum_3class, abs=0.001) == 1.0

def test_extract_game_targets_logic():
    app = create_app("testing")
    with app.app_context():
        db.create_all()
        try:
            # Create team fixtures
            t1 = Team(team_id=1, abbreviation='AAA', name='Team A')
            t2 = Team(team_id=2, abbreviation='BBB', name='Team B')
            db.session.add_all([t1, t2])
            db.session.commit()

            # 1. Non-shootout game: Boxscore 4-2
            g_reg = Game(game_id=999901, season="20242025", game_date=date(2024, 10, 15), home_team_id=1, away_team_id=2, game_type='R', data_source='nhl_api', nhl_game_state='FINAL', home_score=4, away_score=2)
            db.session.add(g_reg)
            db.session.commit()

            res_reg = extract_game_targets(g_reg)
            assert res_reg["has_so"] is False
            assert res_reg["box_home"] == 4
            assert res_reg["box_away"] == 2
            assert res_reg["reg_home"] == 4
            assert res_reg["reg_away"] == 2
            assert res_reg["reg_3class"] == 0  # Home win
            assert res_reg["anomaly"] is False

            # 2. Home Shootout Win: Boxscore 3-2 with Event SO
            g_so_home = Game(game_id=999902, season="20242025", game_date=date(2024, 10, 15), home_team_id=1, away_team_id=2, game_type='R', data_source='nhl_api', nhl_game_state='FINAL', home_score=3, away_score=2)
            so_event_1 = Event(event_id="999902_1", game_id=999902, period=5, period_type='SO', event_type='SHOT', period_time='00:00')
            db.session.add(g_so_home)
            db.session.add(so_event_1)
            db.session.commit()

            res_so_home = extract_game_targets(g_so_home)
            assert res_so_home["has_so"] is True
            assert res_so_home["reg_home"] == 2
            assert res_so_home["reg_away"] == 2
            assert res_so_home["reg_3class"] == 2  # Shootout required (tie)
            assert res_so_home["anomaly"] is False

            # 3. Away Shootout Win: Boxscore 2-3 with Event SO
            g_so_away = Game(game_id=999903, season="20242025", game_date=date(2024, 10, 15), home_team_id=1, away_team_id=2, game_type='R', data_source='nhl_api', nhl_game_state='FINAL', home_score=2, away_score=3)
            so_event_2 = Event(event_id="999903_1", game_id=999903, period=5, period_type='SO', event_type='SHOT', period_time='00:00')
            db.session.add(g_so_away)
            db.session.add(so_event_2)
            db.session.commit()

            res_so_away = extract_game_targets(g_so_away)
            assert res_so_away["has_so"] is True
            assert res_so_away["reg_home"] == 2
            assert res_so_away["reg_away"] == 2
            assert res_so_away["reg_3class"] == 2  # Shootout required (tie)
            assert res_so_away["anomaly"] is False

            # 4. Shootout Anomaly Case: Boxscore 4-2 with Event SO (reg scores unequal after adjustment)
            g_so_anom = Game(game_id=999904, season="20242025", game_date=date(2024, 10, 15), home_team_id=1, away_team_id=2, game_type='R', data_source='nhl_api', nhl_game_state='FINAL', home_score=4, away_score=2)
            so_event_3 = Event(event_id="999904_1", game_id=999904, period=5, period_type='SO', event_type='SHOT', period_time='00:00')
            db.session.add(g_so_anom)
            db.session.add(so_event_3)
            db.session.commit()

            res_so_anom = extract_game_targets(g_so_anom)
            assert res_so_anom["has_so"] is True
            assert res_so_anom["reg_home"] == 3
            assert res_so_anom["reg_away"] == 2
            assert res_so_anom["anomaly"] is True

        finally:
            db.session.rollback()
            db.drop_all()
