import pytest
from app.services.elo_service import EloService

def test_elo_win_probability_equal_ratings():
    # At equal rating with 35 Home Advantage, Home team should have ~55% win probability
    p_home = EloService.get_win_probability(1500.0, 1500.0, home_advantage=35.0)
    assert 0.54 < p_home < 0.56

def test_elo_update_ratings():
    home_elo, away_elo = 1500.0, 1500.0
    # Home team wins 4-1
    new_home, new_away, p_home = EloService.update_ratings(home_elo, away_elo, home_score=4, away_score=1)
    assert new_home > 1500.0
    assert new_away < 1500.0
    assert new_home + new_away == 3000.0  # Zero-sum conserves total Elo

def test_elo_evaluation_metrics():
    preds = [
        {"p_home_win": 0.8, "actual_home_win": 1},
        {"p_home_win": 0.7, "actual_home_win": 1},
        {"p_home_win": 0.3, "actual_home_win": 0},
        {"p_home_win": 0.4, "actual_home_win": 0}
    ]
    metrics = EloService.evaluate_predictions(preds)
    assert metrics["accuracy"] == 100.0
    assert metrics["log_loss"] < 0.4
    assert metrics["brier_score"] < 0.1
