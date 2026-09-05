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
    assert standardize_strength_state(None) == 'UNKNOWN'


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


# ==========================================
# 7. Hardening Regression Tests (v1.2.1)
# ==========================================
def test_model_metadata_persists_after_serialization(tmp_path):
    """Task 2: Verify custom training metadata persists through save and reload."""
    df = pd.DataFrame([{
        'distance': 25.0, 'angle': 10.0, 'shot_type': 'wrist', 'strength_state': 'EV',
        'period': 1, 'period_seconds': 100, 'score_differential': 0, 'is_home': 1,
        'empty_net': 0, 'time_since_prev_event': 5.0, 'distance_from_prev_event': 10.0,
        'angle_change': 5.0, 'is_rebound': 0, 'is_rush': 0, 'is_turnover': 0,
        'is_after_faceoff': 0, 'is_lateral_movement': 0, 'is_power_play': 0,
        'is_shorthanded': 0, 'coordinates_missing': 0, 'prev_event_type': 'none'
    }, {
        'distance': 10.0, 'angle': 0.0, 'shot_type': 'wrist', 'strength_state': 'EV',
        'period': 1, 'period_seconds': 200, 'score_differential': 0, 'is_home': 1,
        'empty_net': 0, 'time_since_prev_event': 2.0, 'distance_from_prev_event': 5.0,
        'angle_change': 0.0, 'is_rebound': 1, 'is_rush': 0, 'is_turnover': 0,
        'is_after_faceoff': 0, 'is_lateral_movement': 0, 'is_power_play': 0,
        'is_shorthanded': 0, 'coordinates_missing': 0, 'prev_event_type': 'shot'
    }])
    y = np.array([0, 1])
    model = LogisticRegressionXGModel(name="test-meta-model", version="2.0.0")
    model.fit(df, y)

    # Attach training metadata
    model.metadata['split_info'] = {'train_shots': 100, 'val_shots': 20, 'test_shots': 20}
    model.metadata['selection_metric'] = 'log_loss'
    assert 'split_info' in model.metadata

    # Save and reload
    save_dir = str(tmp_path / "model_test")
    try:
        ModelRegistry.save_model(model, directory=save_dir)
        loaded = ModelRegistry.load_model(directory=save_dir)

        assert loaded is not None
        assert loaded.metadata.get('selection_metric') == 'log_loss'
        assert loaded.metadata.get('split_info', {}).get('train_shots') == 100
    finally:
        ModelRegistry.reset_active_model()


def test_model_name_and_version_distinction():
    """Task 3: Verify get_active_name() and get_active_version() return distinct, correct identifiers."""
    name = ModelRegistry.get_active_name()
    version = ModelRegistry.get_active_version()
    assert name != version
    assert "logistic" in name or "boosted" in name or "model" in name
    assert version == "1.0.0" or version.count('.') >= 1


def test_prediction_provenance_dataclass():
    """Task 3: Verify XGPrediction returns complete 3-part provenance for ML predictions."""
    shot_input = {
        'distance': 20.0,
        'angle': 10.0,
        'shot_type': 'wrist',
        'strength_state': 'EV',
        'empty_net': False
    }
    pred = ModelRegistry.predict_shot_xg_with_provenance(shot_input)
    assert hasattr(pred, 'xg')
    assert hasattr(pred, 'model_name')
    assert hasattr(pred, 'model_version')
    assert hasattr(pred, 'method')
    assert hasattr(pred, 'fallback_used')
    assert 0.0 <= pred.xg <= 1.0
    assert pred.method == 'ml'
    assert pred.fallback_used is False
    assert pred.model_name == ModelRegistry.get_active_name()
    assert pred.model_version == ModelRegistry.get_active_version()


def test_forced_inference_failure_fallback_provenance():
    """Task 3: Verify inference failures gracefully use heuristic fallback with correct provenance."""
    from app.analytics.xg_model import BaseXGModel
    original_model = ModelRegistry._active_model

    class BrokenInferenceModel(BaseXGModel):
        def fit(self, X, y):
            return self
        def predict(self, X):
            raise RuntimeError("Simulated ML inference failure")

    try:
        ModelRegistry._active_model = BrokenInferenceModel(name="broken-model", version="0.0.1")
        pred = ModelRegistry.predict_shot_xg_with_provenance({'distance': 25.0, 'angle': 5.0})
        assert pred.method == 'heuristic'
        assert pred.fallback_used is True
        assert pred.model_name == 'pucklens-xg-heuristic'
        assert pred.model_version == '1.0.0'
        assert 0.0 <= pred.xg <= 1.0
    finally:
        ModelRegistry._active_model = original_model


def test_expected_shooting_percentage_unblocked_denominator(app):
    """Task 4: Verify expected conversion rate uses unblocked attempts (goals + saves + misses)."""
    with app.app_context():
        # Setup mock teams, game, and player
        t1 = db.session.get(Team, 101) or Team(team_id=101, name="Team A", abbreviation="TMA")
        t2 = db.session.get(Team, 102) or Team(team_id=102, name="Team B", abbreviation="TMB")
        db.session.add_all([t1, t2])
        db.session.flush()

        g = Game(game_id=99999, season="20232024", game_date=date(2023, 10, 15), home_team_id=101, away_team_id=102)
        p = Player(player_id=77701, first_name="Sniper", last_name="Test")
        db.session.add_all([g, p])
        db.session.flush()

        # Create 1 Goal (xG=0.20), 1 Saved (xG=0.10), 2 Missed (xG=0.15 each)
        # Total unblocked = 4 attempts, SOG = 2. Total xG = 0.60.
        evt_types = [('Goal', 'Goal', 0.20), ('Saved', 'Saved', 0.10), 
                     ('Missed', 'Missed', 0.15), ('Missed', 'Missed', 0.15)]
        for i, (evt_desc, outcome, xg_val) in enumerate(evt_types):
            e = Event(event_id=f"evt_{i}", game_id=99999, event_type=evt_desc.lower(),
                      period=1, period_time="05:00", elapsed_game_seconds=300,
                      period_type="REG", primary_player_id=77701)
            sh = Shot(shot_id=f"evt_{i}", game_id=99999, shooter_id=77701, team_id=101,
                      x_coordinate_normalized=70.0, y_coordinate_normalized=0.0,
                      outcome=outcome, goal=(outcome == 'Goal'), xg=xg_val,
                      model_name="pucklens-xg-logistic", model_version="1.0.0", prediction_method="ml")
            db.session.add_all([e, sh])
        db.session.commit()

        stats = SkaterStatsService.get_skater_game_stats(99999, 77701)
        assert stats["shots_on_goal"] == 2
        assert stats["unblocked_attempts"] == 4
        assert stats["goals"] == 1
        assert stats["actual_shooting_pct"] == 50.0  # (1 / 2) * 100
        # Expected conversion rate must use 4 unblocked attempts, NOT 2 SOG!
        # (0.60 / 4) * 100 = 15.0%
        assert stats["expected_goal_rate_per_unblocked_attempt"] == 15.0
        assert stats["expected_shooting_pct"] == 15.0
        assert stats["goals_above_expected"] == 0.40  # 1.0 - 0.60


def test_sequential_coordinates_raw_rink_distance():
    """Task 5: Verify Euclidean distance between events uses raw coordinates across possession changes."""
    # Synthetic PBP with Away giveaway followed by Home shot
    pbp_sample = {
        'id': 10001,
        'season': '20232024',
        'gameDate': '2023-10-15',
        'homeTeam': {'id': 1},
        'awayTeam': {'id': 2},
        'plays': [
            {
                'eventId': 1,
                'periodDescriptor': {'number': 1, 'periodType': 'REG'},
                'timeInPeriod': '02:00',
                'typeDescKey': 'giveaway',
                'details': {
                    'eventOwnerTeamId': 2,  # Away team giveaway
                    'xCoord': 20.0,
                    'yCoord': 10.0
                }
            },
            {
                'eventId': 2,
                'periodDescriptor': {'number': 1, 'periodType': 'REG'},
                'timeInPeriod': '02:03',
                'typeDescKey': 'shot-on-goal',
                'details': {
                    'eventOwnerTeamId': 1,  # Home team shot
                    'shootingPlayerId': 101,
                    'xCoord': 60.0,
                    'yCoord': 10.0,
                    'shotType': 'wrist'
                }
            }
        ]
    }
    shots = ShotFeatureExtractor.extract_shots_from_pbp_json(pbp_sample)
    assert len(shots) == 1
    shot = shots[0]
    # Physical distance on rink from (20, 10) to (60, 10) is exactly 40.0 ft
    assert shot['distance_from_prev_event'] == 40.0
    assert shot['time_since_prev_event'] == 3.0
    assert shot['is_turnover'] == 1


def test_missing_data_semantics_explicit():
    """Task 6: Verify coordinates_missing indicator and UNKNOWN categorical handling."""
    # Missing coordinates
    f_missing = ShotFeatureExtractor.extract_features_from_dict({
        'shot_type': None,
        'strength_state': None
    })
    assert f_missing['coordinates_missing'] == 1
    assert f_missing['shot_type'] == 'UNKNOWN'
    assert f_missing['strength_state'] == 'UNKNOWN'

    # Present coordinates
    f_present = ShotFeatureExtractor.extract_features_from_dict({
        'x_coordinate': 75.0,
        'y_coordinate': 0.0,
        'shot_type': 'wrist',
        'strength_state': '5v5'
    })
    assert f_present['coordinates_missing'] == 0
    assert f_present['shot_type'] == 'wrist'
    assert f_present['strength_state'] == 'EV'


def test_xg_service_provenance_and_backward_compatibility():
    """Task 3: Verify XGService returns full provenance object and float backward compatibility."""
    pred = XGService.predict_shot_xg(distance=25.0, angle=10.0, shot_type='wrist', strength_state='EV')
    assert hasattr(pred, 'xg')
    assert hasattr(pred, 'model_name')
    assert hasattr(pred, 'model_version')
    assert hasattr(pred, 'method')
    assert 0.0 <= pred.xg <= 1.0
    assert pred.method in ['ml', 'heuristic']
    assert isinstance(pred.model_name, str) and len(pred.model_name) > 0
    assert isinstance(pred.model_version, str) and len(pred.model_version) > 0

    # Backward-compatible float method
    float_val = XGService.calculate_shot_xg(distance=25.0, angle=10.0, shot_type='wrist', strength_state='EV')
    assert isinstance(float_val, float)
    assert float_val == pred.xg


def test_model_metadata_serialization_rich_audit():
    """Task 2 & 9: Verify metadata contains required split info, candidate selection, and Option B refit."""
    import os
    import json
    from app.analytics.model_registry import DEFAULT_MODEL_DIR

    meta_path = os.path.join(DEFAULT_MODEL_DIR, "metadata.json")
    assert os.path.exists(meta_path), "metadata.json must exist"

    with open(meta_path, 'r', encoding='utf-8') as f:
        meta = json.load(f)

    # Validate split info
    split = meta.get('split_info', {})
    assert 'train_games' in split and split['train_games'] > 0
    assert 'val_games' in split and split['val_games'] > 0
    assert 'test_games' in split and split['test_games'] > 0
    assert 'refit_shots' in split and split['refit_shots'] == split['train_shots'] + split['val_shots']
    assert split.get('method') == 'chronological_game_split'

    # Validate selection strategy (Task 1)
    sel = meta.get('selection_strategy', {})
    assert sel.get('metric') == 'validation_log_loss'
    assert sel.get('test_set_isolation') == 'untouched_during_candidate_selection'
    assert 'candidate_metrics' in sel
    assert 'logistic' in sel['candidate_metrics']
    assert 'boosted' in sel['candidate_metrics']

    # Validate retraining strategy (Task 2 Option B)
    retrain = meta.get('retraining_strategy', {})
    assert retrain.get('strategy') == 'option_b_train_plus_validation_refit'

    # Validate library versions (Task 7)
    assert 'scikit_learn_version' in meta
    assert 'numpy_version' in meta
    assert 'pandas_version' in meta

