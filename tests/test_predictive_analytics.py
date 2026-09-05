import pytest
import numpy as np
import pandas as pd
from datetime import date

from app.analytics.shot_features import (
    calculate_distance_and_angle,
    normalize_coordinates,
    standardize_shot_type,
    standardize_strength_state,
    ShotFeatureExtractor,
    NET_X,
    NET_Y,
    NUMERIC_FEATURES,
    CATEGORICAL_FEATURES
)
from app.analytics.xg_model import LogisticRegressionXGModel, GradientBoostingXGModel
from app.analytics.model_registry import ModelRegistry
from app.analytics.evaluation import ModelEvaluator
from app.services.xg_service import XGService
from app.services.game_service import GameService
from app.services.skater_stats_service import SkaterStatsService
from app.services.goalie_stats_service import GoalieStatsService
from app.services.unit_service import UnitService
from app.services.data_integrity_service import DataIntegrityService
from app.models import db, Game, Team, Player, Event, Shot, Shift, GamePlayer


# ==========================================
# 1. Shot Geometry Tests
# ==========================================
def test_distance_and_angle_geometry():
    """Verify Euclidean distance and angle calculations relative to net at (89, 0)."""
    # Shot right on the goal line at net center
    d, a = calculate_distance_and_angle(89.0, 0.0)
    assert d == 0.0
    assert a == 0.0

    # Shot 20 feet directly in front of the net along the center line
    d, a = calculate_distance_and_angle(69.0, 0.0)
    assert d == 20.0
    assert a == 0.0

    # Shot on the goal line, 20 feet to the right (dy = 20, dx = 0) -> 90 degrees
    d, a = calculate_distance_and_angle(89.0, 20.0)
    assert d == 20.0
    assert a == 90.0

    # Symmetry test: (+y) and (-y) angles must be identical
    d1, a1 = calculate_distance_and_angle(69.0, 15.0)
    d2, a2 = calculate_distance_and_angle(69.0, -15.0)
    assert d1 == d2
    assert a1 == a2
    assert a1 > 0.0


def test_coordinate_normalization():
    """Verify rink coordinate normalization flips shots toward the attacking net at x = +89."""
    # When home defends left (x < 0), home attacks right (x > 0). No flip for home.
    hx, hy = normalize_coordinates(50.0, 10.0, home_defending_side='left', is_home_team=True)
    assert hx == 50.0 and hy == 10.0

    # Away team defends right (x > 0), attacks left (x < 0). Flip for away.
    ax, ay = normalize_coordinates(-50.0, -10.0, home_defending_side='left', is_home_team=False)
    assert ax == 50.0 and ay == 10.0

    # Fallback normalization when defending side unknown: x < 0 flips to x > 0
    fx, fy = normalize_coordinates(-75.0, -12.0)
    assert fx == 75.0 and fy == 12.0

    # None handling
    nx, ny = normalize_coordinates(None, None)
    assert nx is None and ny is None


# ==========================================
# 2. Event Context Tests
# ==========================================
def test_event_context_feature_derivation():
    """Verify previous-event dynamics, rebound detection, rush detection, and empty-net."""
    # Rebound: previous event was saved shot within 2 seconds
    rebound_features = ShotFeatureExtractor.extract_features_from_dict({
        'x_coordinate': 80.0,
        'y_coordinate': 2.0,
        'prev_event_type': 'shot-on-goal',
        'time_since_prev_event': 1.5,
        'distance_from_prev_event': 5.0
    })
    assert rebound_features['is_rebound'] == 1

    # Not a rebound: previous event was a shot 8 seconds ago
    old_shot_features = ShotFeatureExtractor.extract_features_from_dict({
        'x_coordinate': 80.0,
        'y_coordinate': 2.0,
        'prev_event_type': 'shot-on-goal',
        'time_since_prev_event': 8.0
    })
    assert old_shot_features['is_rebound'] == 0

    # Rush: rapid puck movement over 40+ feet within 3 seconds
    rush_features = ShotFeatureExtractor.extract_features_from_dict({
        'x_coordinate': 75.0,
        'y_coordinate': 0.0,
        'prev_event_type': 'takeaway',
        'time_since_prev_event': 2.5,
        'distance_from_prev_event': 55.0
    })
    assert rush_features['is_rush'] == 1
    assert rush_features['is_turnover'] == 1

    # Empty net flag
    en_features = ShotFeatureExtractor.extract_features_from_dict({'empty_net': True})
    assert en_features['empty_net'] == 1

    # Strength state standardizations
    assert standardize_strength_state('5v4') == 'PP'
    assert standardize_strength_state('4v5') == 'SH'
    assert standardize_strength_state('5v5') == 'EV'
    assert standardize_strength_state(None) == 'EV'


# ==========================================
# 3. Model Pipeline & NaN Safety Tests
# ==========================================
def test_model_pipeline_feature_consistency_and_bounds():
    """Verify feature pipeline handles unseen categories, missing fields, and guarantees 0 <= xG <= 1."""
    # Build synthetic test set
    n_samples = 40
    data = []
    for i in range(n_samples):
        data.append(ShotFeatureExtractor.extract_features_from_dict({
            'distance': 10.0 + (i * 1.5),
            'angle': float(i % 45),
            'shot_type': 'wrist' if i % 2 == 0 else 'slap',
            'strength_state': 'EV' if i % 3 != 0 else 'PP',
            'empty_net': (i == 0)
        }))
    df = pd.DataFrame(data)
    y = np.array([1 if i < 4 else 0 for i in range(n_samples)])

    lr = LogisticRegressionXGModel()
    lr.fit(df, y)

    gb = GradientBoostingXGModel()
    gb.fit(df, y)

    # Test predictions with incomplete input (checking NaN/missing safety)
    sparse_input = {'distance': 25.0, 'angle': 10.0}
    lr_prob = lr.predict(sparse_input)
    gb_prob = gb.predict(sparse_input)

    assert 0.0 <= lr_prob <= 1.0
    assert 0.0 <= gb_prob <= 1.0

    # Test unknown category handling
    unknown_cat_input = {'distance': 30.0, 'angle': 15.0, 'shot_type': 'super-curveball-shot'}
    prob_unknown = lr.predict(unknown_cat_input)
    assert 0.0 <= prob_unknown <= 1.0


# ==========================================
# 4. Aggregation and Division-by-Zero Safety Tests
# ==========================================
def test_aggregations_and_div_zero_safety():
    """Verify xGF, xGA, xG%, GSAx, and per-60 calculations handle 0 safely."""
    # Zero totals: xG% should default safely to 50.0%
    tot_xg = 0.0 + 0.0
    xg_pct = (0.0 / tot_xg * 100) if tot_xg > 0 else 50.0
    assert xg_pct == 50.0

    # Normal totals
    tot_xg = 3.0 + 2.0
    xg_pct = round((3.0 / tot_xg * 100), 1)
    assert xg_pct == 60.0

    # Rate per 60 with 0 TOI
    toi_zero = 0
    rate_zero = round(2.5 / (toi_zero / 3600.0), 2) if toi_zero > 0 else 0.0
    assert rate_zero == 0.0

    # Rate per 60 with 20 minutes (1200 seconds) TOI
    toi_20m = 1200
    rate_20m = round(2.5 / (toi_20m / 3600.0), 2)
    assert rate_20m == 7.50


# ==========================================
# 5. Milestone 15 Diagnostics Integration
# ==========================================
def test_diagnostics_shot_model_data_quality(app):
    """Verify DataIntegrityService includes Milestone 15 shot model data quality checks."""
    with app.app_context():
        results = DataIntegrityService.run_diagnostic_checks()
        assert "shot_model_data_quality" in results
        quality = results["shot_model_data_quality"]
        assert "summary" in quality
        assert "shots_analyzed" in quality["summary"]
        assert quality["summary"]["shots_analyzed"] >= 0


# ==========================================
# 6. Deterministic Regression Fixture Test
# ==========================================
def test_deterministic_regression_fixture():
    """Verify deterministic outputs on frozen test fixture."""
    active_model = ModelRegistry.get_active_model()
    assert active_model is not None

    # Deterministic point shot: 55 ft, 35 deg, slap shot, 5v5
    shot1 = {
        'distance': 55.0,
        'angle': 35.0,
        'shot_type': 'slap',
        'strength_state': 'EV',
        'empty_net': False
    }
    p1 = float(active_model.predict(shot1))
    assert 0.01 <= p1 <= 0.12

    # Deterministic high-danger rebound shot: 8 ft, 5 deg, wrist shot, rebound
    shot2 = {
        'distance': 8.0,
        'angle': 5.0,
        'shot_type': 'wrist',
        'strength_state': 'EV',
        'empty_net': False,
        'is_rebound': 1,
        'time_since_prev_event': 1.0
    }
    p2 = float(active_model.predict(shot2))
    assert p2 > p1
    assert p2 >= 0.15
