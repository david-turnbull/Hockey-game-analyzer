import pytest
from app.analytics.forecasting.score_projection import PoissonScoreModel

def test_poisson_score_projection():
    dummy_features = {
        "home_l10_gf_per_game": 3.5,
        "home_l10_ga_per_game": 2.2,
        "away_l10_gf_per_game": 2.8,
        "away_l10_ga_per_game": 3.1,
        "home_is_b2b": 0,
        "away_is_b2b": 1
    }

    res = PoissonScoreModel.project_score_distribution(dummy_features)

    assert "projected hockey-goal score distribution (excluding shootout bonus)" in res["disclaimer_label"]
    assert res["expected_home_goals"] > 0
    assert res["expected_away_goals"] > 0

    matrix = res["score_matrix"]
    assert len(matrix) == 10
    assert len(matrix[0]) == 10

    # Total matrix probability should sum close to 1.0
    total_prob = sum(sum(row) for row in matrix)
    assert 0.98 < total_prob <= 1.0

    # Verify top scorelines
    assert len(res["top_scorelines"]) == 5
    assert "totals_projections" in res
