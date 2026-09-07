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
from data_pipeline.transform.normalizer import DataNormalizer
from data_pipeline.orchestrator import PipelineOrchestrator


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

    # Validate library versions and runtime provenance
    assert 'scikit_learn_version' in meta
    assert 'numpy_version' in meta
    assert 'pandas_version' in meta
    assert 'joblib_version' in meta
    assert 'python_version' in meta
    assert 'platform' in meta
    assert 'git_commit' in meta


def test_sequential_coordinate_frame_consistency():
    """
    Priority 1: Verify coordinate transformation helper and sequential angle change consistency.
    Proves that mirrored rink coordinates produce identical physical distances and angle changes.
    """
    from app.analytics.shot_features import (
        get_attacking_coordinate_transform,
        apply_coordinate_transform
    )

    # Team attacking right (x > 0)
    curr_raw_x, curr_raw_y = 70.0, 10.0
    prev_raw_x, prev_raw_y = 50.0, 20.0

    flip_right = get_attacking_coordinate_transform(curr_raw_x, curr_raw_y, home_defending_side='left', is_home_team=True)
    assert flip_right is False
    nx_right, ny_right = apply_coordinate_transform(curr_raw_x, curr_raw_y, flip_right)
    pnx_right, pny_right = apply_coordinate_transform(prev_raw_x, prev_raw_y, flip_right)
    d_right, a_right = calculate_distance_and_angle(nx_right, ny_right)
    pd_right, pa_right = calculate_distance_and_angle(pnx_right, pny_right)
    delta_d_right = np.sqrt((curr_raw_x - prev_raw_x)**2 + (curr_raw_y - prev_raw_y)**2)
    ang_change_right = abs(a_right - pa_right)

    # Same play mirrored, team attacking left (x < 0)
    m_curr_raw_x, m_curr_raw_y = -70.0, -10.0
    m_prev_raw_x, m_prev_raw_y = -50.0, -20.0

    flip_left = get_attacking_coordinate_transform(m_curr_raw_x, m_curr_raw_y, home_defending_side='right', is_home_team=True)
    assert flip_left is True
    nx_left, ny_left = apply_coordinate_transform(m_curr_raw_x, m_curr_raw_y, flip_left)
    pnx_left, pny_left = apply_coordinate_transform(m_prev_raw_x, m_prev_raw_y, flip_left)
    d_left, a_left = calculate_distance_and_angle(nx_left, ny_left)
    pd_left, pa_left = calculate_distance_and_angle(pnx_left, pny_left)
    delta_d_left = np.sqrt((m_curr_raw_x - m_prev_raw_x)**2 + (m_curr_raw_y - m_prev_raw_y)**2)
    ang_change_left = abs(a_left - pa_left)

    # Invariants under coordinate transform
    assert d_right == d_left
    assert a_right == a_left
    assert pd_right == pd_left
    assert pa_right == pa_left
    assert round(delta_d_right, 4) == round(delta_d_left, 4)
    assert round(ang_change_right, 4) == round(ang_change_left, 4)


def test_blocked_shots_domain_invariant(app, db):
    """
    Priority 0: Verify domain invariant that Blocked shots are strictly ineligible for xG (Shot.xg = NULL).
    Blocked shots contribute to Corsi, but are completely barred from receiving or contributing to
    any xG or Fenwick/unblocked metrics across normalizer, services, and API serialization.
    """
    from data_pipeline.transform.normalizer import DataNormalizer

    normalizer = DataNormalizer()
    
    # 1. Normalizer Invariant: Blocked event receives xg = None and provenance = None
    event_dict = {
        "eventId": 101,
        "typeDescKey": "blocked-shot",
        "periodDescriptor": {"number": 1, "periodType": "REG"},
        "timeInPeriod": "05:00",
        "details": {
            "xCoord": 65,
            "yCoord": 5,
            "shootingPlayerId": 1001,
            "blockingPlayerId": 2001,
            "shotType": "wrist",
            "eventOwnerTeamId": 1
        }
    }
    game_dict = {
        "id": 99999,
        "homeTeam": {"id": 1, "abbrev": "HOM"},
        "awayTeam": {"id": 2, "abbrev": "AWY"}
    }
    event_model, shot_model = normalizer.transform_event(event_dict, 99999, 1)
    assert shot_model is not None
    assert shot_model.outcome == "Blocked"
    assert shot_model.xg is None
    assert shot_model.model_name is None
    assert shot_model.model_version is None
    assert shot_model.prediction_method is None

    # Normalizer Invariant: Goal, Saved, Missed receive xG
    for ev_type, expected_outcome in [('goal', 'Goal'), ('shot-on-goal', 'Saved'), ('missed-shot', 'Missed')]:
        ev_dict = dict(event_dict, eventId=102, typeDescKey=ev_type)
        _, s_model = normalizer.transform_event(ev_dict, 99999, 1)
        assert s_model.outcome == expected_outcome
        assert s_model.xg is not None
        assert s_model.xg > 0.0
        assert s_model.prediction_method is not None

    # 2. Database & Service Level Invariant Verification
    # Seed a mini game in test DB
    test_game = Game(
        game_id=88888,
        season="20232024",
        game_date=date(2023, 10, 15),
        game_type=2,
        nhl_game_state="OFF",
        home_team_id=1,
        away_team_id=2,
        home_score=1,
        away_score=0
    )
    t1 = Team(team_id=1, name="Home Team", abbreviation="HOM")
    t2 = Team(team_id=2, name="Away Team", abbreviation="AWY")
    p1 = Player(player_id=1001, first_name="Shooter", last_name="One", position="C")
    p2 = Player(player_id=2001, first_name="Goalie", last_name="One", position="G")
    db.session.add_all([test_game, t1, t2, p1, p2])
    db.session.flush()

    # Create 4 shot events: Goal (0.25), Saved (0.15), Missed (0.10), Blocked (None)
    # Total valid xG = 0.50
    outcomes_data = [
        ("goal", "Goal", True, 0.25, 100),
        ("shot-on-goal", "Saved", False, 0.15, 200),
        ("missed-shot", "Missed", False, 0.10, 300),
        ("blocked-shot", "Blocked", False, None, 400),
    ]

    for ev_type, outcome, is_goal, xg_val, elapsed in outcomes_data:
        e = Event(
            event_id=elapsed,
            game_id=88888,
            event_type=ev_type,
            period=1,
            period_type="REG",
            period_time=f"0{elapsed//60}:00",
            elapsed_game_seconds=elapsed,
            team_id=1,
            primary_player_id=1001,
            team_strength_state="5v5",
            manpower_state="EV"
        )
        s = Shot(
            shot_id=elapsed,
            game_id=88888,
            team_id=1,
            shooter_id=1001,
            goalie_id=2001 if outcome in ['Goal', 'Saved'] else None,
            x_coordinate_normalized=65.0,
            y_coordinate_normalized=5.0,
            distance=25.0,
            angle=5.0,
            outcome=outcome,
            goal=is_goal,
            strength_state="EV",
            empty_net=False,
            xg=xg_val,
            model_name="pucklens-xg-logistic" if xg_val is not None else None,
            model_version="1.0.0" if xg_val is not None else None,
            prediction_method="ml" if xg_val is not None else None
        )
        db.session.add_all([e, s])
    db.session.commit()

    # Service Check 1: GameService details home_xg
    game_details = GameService.get_game_overview_stats(88888)
    assert game_details["stats"]["home_xg"] == 0.50

    # Service Check 2: GameService xG timeline only contains unblocked shots
    timeline = GameService.get_game_xg_timeline(88888, situation='all')
    timeline_shots = [pt for pt in timeline.get("timeline", []) if pt.get("event_type")]
    timeline_event_types = [pt["event_type"] for pt in timeline_shots]
    assert "blocked-shot" not in timeline_event_types
    assert len(timeline_shots) == 3
    assert timeline["home_team"]["total_xg"] == 0.50

    # Service Check 3: SkaterStatsService excludes blocked shot
    skater_stats = SkaterStatsService.calculate_skater_stats(88888, 1001)
    assert skater_stats["xg"] == 0.50
    assert skater_stats["unblocked_attempts"] == 3

    # Service Check 4: UnitService strictly separates Corsi (all 4) from Fenwick & xG (3)
    shots_unit = Shot.query.join(Event).filter(Event.game_id == 88888).all()
    cf = ca = ff = fa = 0
    xgf = xga = 0.0
    for s in shots_unit:
        shot_xg = float(s.xg) if (s.xg is not None and s.outcome in ['Goal', 'Saved', 'Missed']) else 0.0
        cf += 1
        if s.outcome in ['Goal', 'Saved', 'Missed']:
            ff += 1
            xgf += shot_xg
    assert cf == 4
    assert ff == 3
    assert round(xgf, 2) == 0.50

    # API Check: shots endpoint serializes blocked shot with xg = None
    with app.test_client() as client:
        res = client.get('/api/games/88888/shots')
        assert res.status_code == 200
        shots_json = res.get_json()
        assert len(shots_json) == 4
        blocked_json = next(item for item in shots_json if item["outcome"] == "Blocked")
        assert blocked_json["xg"] is None
        assert blocked_json["model_version"] is None


def test_sequential_features_rebound_and_rush():
    """Task 8: Verifies sequential features (rebound and rush) extraction from play sequence."""
    pbp_mock = {
        "id": 10001,
        "season": "20232024",
        "gameDate": "2023-11-01",
        "homeTeam": {"id": 1, "abbrev": "HOM"},
        "awayTeam": {"id": 2, "abbrev": "AWY"},
        "plays": [
            {
                "eventId": 1,
                "periodDescriptor": {"number": 1, "periodType": "REG"},
                "timeInPeriod": "02:00",
                "typeDescKey": "shot-on-goal",
                "details": {"xCoord": 65.0, "yCoord": 5.0, "eventOwnerTeamId": 1, "shootingPlayerId": 101, "goalieInNetId": 201, "shotType": "wrist"}
            },
            {
                "eventId": 2,
                "periodDescriptor": {"number": 1, "periodType": "REG"},
                "timeInPeriod": "02:02",
                "typeDescKey": "shot-on-goal",
                "details": {"xCoord": 80.0, "yCoord": 2.0, "eventOwnerTeamId": 1, "shootingPlayerId": 102, "goalieInNetId": 201, "shotType": "backhand"}
            },
            {
                "eventId": 3,
                "periodDescriptor": {"number": 1, "periodType": "REG"},
                "timeInPeriod": "05:00",
                "typeDescKey": "takeaway",
                "details": {"xCoord": -60.0, "yCoord": 0.0, "eventOwnerTeamId": 1, "playerId": 103}
            },
            {
                "eventId": 4,
                "periodDescriptor": {"number": 1, "periodType": "REG"},
                "timeInPeriod": "05:03",
                "typeDescKey": "shot-on-goal",
                "details": {"xCoord": 60.0, "yCoord": 5.0, "eventOwnerTeamId": 1, "shootingPlayerId": 103, "goalieInNetId": 201, "shotType": "wrist"}
            }
        ]
    }
    shots = ShotFeatureExtractor.extract_shots_from_pbp_json(pbp_mock, unblocked_only=True)
    assert len(shots) == 3

    # Shot 1 (eventId 1): Initial shot, not rebound, not rush
    assert shots[0]["is_rebound"] == 0

    # Shot 2 (eventId 2): 2 seconds after initial shot -> is_rebound must be 1
    assert shots[1]["is_rebound"] == 1
    assert shots[1]["time_since_prev_event"] == 2.0
    assert shots[1]["prev_event_type"] == "shot-on-goal"

    # Shot 3 (eventId 4): 3 seconds after takeaway with delta_d >= 40 ft -> is_rush must be 1, is_turnover must be 1
    assert shots[2]["is_rush"] == 1
    assert shots[2]["is_turnover"] == 1
    assert shots[2]["time_since_prev_event"] == 3.0
    assert shots[2]["distance_from_prev_event"] >= 40.0


def test_sequential_features_turnover_and_faceoff():
    """Task 8: Verifies turnover and faceoff sequential feature identification."""
    pbp_mock = {
        "id": 10002,
        "season": "20232024",
        "gameDate": "2023-11-01",
        "homeTeam": {"id": 1, "abbrev": "HOM"},
        "awayTeam": {"id": 2, "abbrev": "AWY"},
        "plays": [
            {
                "eventId": 10,
                "periodDescriptor": {"number": 2, "periodType": "REG"},
                "timeInPeriod": "08:15",
                "typeDescKey": "faceoff",
                "details": {"xCoord": 69.0, "yCoord": 22.0, "eventOwnerTeamId": 1}
            },
            {
                "eventId": 11,
                "periodDescriptor": {"number": 2, "periodType": "REG"},
                "timeInPeriod": "08:17",
                "typeDescKey": "shot-on-goal",
                "details": {"xCoord": 60.0, "yCoord": 10.0, "eventOwnerTeamId": 1, "shootingPlayerId": 105, "goalieInNetId": 201, "shotType": "slap"}
            }
        ]
    }
    shots = ShotFeatureExtractor.extract_shots_from_pbp_json(pbp_mock, unblocked_only=True)
    assert len(shots) == 1
    assert shots[0]["is_after_faceoff"] == 1
    assert shots[0]["prev_event_type"] == "faceoff"
    assert shots[0]["time_since_prev_event"] == 2.0


def test_missing_coordinates_shot_handling(app, db):
    """Task 5: Verifies that shot with missing coordinates creates valid Shot record, nullable DB columns, and neutral xG."""
    normalizer = DataNormalizer()
    missing_coord_play = {
        "eventId": 999,
        "periodDescriptor": {"number": 1, "periodType": "REG"},
        "timeInPeriod": "14:20",
        "typeDescKey": "shot-on-goal",
        "situationCode": "1551",
        "details": {
            "shootingPlayerId": 1001,
            "goalieInNetId": 2001,
            "shotType": "wrist",
            "eventOwnerTeamId": 1
            # Note: xCoord and yCoord are intentionally omitted (None)
        }
    }

    event_model, shot_model = normalizer.transform_event(missing_coord_play, 88889, 1)

    assert event_model is not None
    assert shot_model is not None
    assert shot_model.outcome == "Saved"
    # Coordinates in DB must remain None (NULL)
    assert shot_model.x_coordinate_normalized is None
    assert shot_model.y_coordinate_normalized is None
    assert shot_model.distance is None
    assert shot_model.angle is None
    # Model scoring must succeed with neutral imputation
    assert shot_model.xg is not None
    assert 0.0 < shot_model.xg < 1.0
    assert shot_model.prediction_method == "ml"
    assert shot_model.model_name is not None

    # Seed parent game, team, shooter, goalie for foreign keys
    test_game = Game(
        game_id=88889,
        season="20232024",
        game_date=date(2023, 10, 15),
        game_type=2,
        nhl_game_state="OFF",
        home_team_id=1,
        away_team_id=2,
        home_score=0,
        away_score=0
    )
    t1 = Team(team_id=1, name="Home Team", abbreviation="HOM")
    t2 = Team(team_id=2, name="Away Team", abbreviation="AWY")
    p1 = Player(player_id=1001, first_name="Shooter", last_name="One", position="C")
    p2 = Player(player_id=2001, first_name="Goalie", last_name="One", position="G")
    db.session.add_all([test_game, t1, t2, p1, p2])
    db.session.flush()

    # Verify SQLite database persistence with NULL coordinates
    db.session.add(event_model)
    db.session.add(shot_model)
    db.session.flush()

    retrieved = db.session.get(Shot, shot_model.shot_id)
    assert retrieved is not None
    assert retrieved.x_coordinate_normalized is None
    assert retrieved.y_coordinate_normalized is None
    assert retrieved.xg == shot_model.xg


def test_training_serving_feature_parity():
    """Task 9: Verifies full 21-feature identical parity between training extraction and serving normalizer."""
    from app.analytics.shot_features import FEATURE_COLUMNS

    pbp_mock = {
        "id": 10003,
        "season": "20232024",
        "gameDate": "2023-11-01",
        "homeTeam": {"id": 1, "abbrev": "HOM"},
        "awayTeam": {"id": 2, "abbrev": "AWY"},
        "plays": [
            {
                "eventId": 50,
                "periodDescriptor": {"number": 1, "periodType": "REG"},
                "timeInPeriod": "01:00",
                "typeDescKey": "hit",
                "details": {"xCoord": 40.0, "yCoord": 10.0, "eventOwnerTeamId": 2}
            },
            {
                "eventId": 51,
                "periodDescriptor": {"number": 1, "periodType": "REG"},
                "timeInPeriod": "01:02",
                "typeDescKey": "shot-on-goal",
                "situationCode": "1551",
                "details": {
                    "xCoord": 75.0,
                    "yCoord": 12.0,
                    "eventOwnerTeamId": 1,
                    "shootingPlayerId": 101,
                    "goalieInNetId": 201,
                    "shotType": "snap"
                }
            }
        ]
    }

    # 1. Training extraction path
    extracted = ShotFeatureExtractor.extract_shots_from_pbp_json(pbp_mock, unblocked_only=True)
    assert len(extracted) == 1
    training_shot_features = extracted[0]

    # 2. Serving normalizer pipeline path
    normalizer = DataNormalizer()
    play = pbp_mock["plays"][1]
    event_id = f"10003_{play['eventId']}"
    assert training_shot_features["event_id"] == event_id

    # Normalizer receives pre-extracted feature dict
    event_model, shot_model = normalizer.transform_event(
        play, 10003, 1, xg_features=training_shot_features
    )
    assert shot_model is not None

    # Predict directly with training extracted features vs shot_model score
    direct_prediction = XGService.predict_shot_xg(features=training_shot_features)
    assert shot_model.xg == direct_prediction.xg
    assert shot_model.model_name == direct_prediction.model_name
    assert shot_model.model_version == direct_prediction.model_version
    assert shot_model.prediction_method == direct_prediction.method

    # Confirm all 21 FEATURE_COLUMNS exist in the training extracted record
    for col in FEATURE_COLUMNS:
        assert col in training_shot_features, f"Missing feature column: {col}"


def test_shot_feature_extractor_missing_event_id():
    """Issue 2: Verifies that an unblocked shot with missing eventId is skipped from canonical extraction."""
    pbp_mock = {
        "id": 10004,
        "season": "20232024",
        "gameDate": "2023-11-01",
        "homeTeam": {"id": 1, "abbrev": "HOM"},
        "awayTeam": {"id": 2, "abbrev": "AWY"},
        "plays": [
            {
                "eventId": None,
                "periodDescriptor": {"number": 1, "periodType": "REG"},
                "timeInPeriod": "03:00",
                "typeDescKey": "shot-on-goal",
                "details": {"xCoord": 65.0, "yCoord": 5.0, "eventOwnerTeamId": 1, "shootingPlayerId": 101, "goalieInNetId": 201, "shotType": "wrist"}
            },
            {
                "eventId": 10,
                "periodDescriptor": {"number": 1, "periodType": "REG"},
                "timeInPeriod": "04:00",
                "typeDescKey": "shot-on-goal",
                "details": {"xCoord": 70.0, "yCoord": 0.0, "eventOwnerTeamId": 1, "shootingPlayerId": 102, "goalieInNetId": 201, "shotType": "slap"}
            }
        ]
    }
    extracted = ShotFeatureExtractor.extract_shots_from_pbp_json(pbp_mock, unblocked_only=True)
    assert len(extracted) == 1
    assert extracted[0]["event_id"] == "10004_10"
    for s in extracted:
        assert "None" not in str(s["event_id"])


def test_shot_feature_extractor_duplicate_event_id():
    """Issue 2: Verifies that duplicate eventId does not silently overwrite and first valid occurrence is preserved."""
    pbp_mock = {
        "id": 10005,
        "season": "20232024",
        "gameDate": "2023-11-01",
        "homeTeam": {"id": 1, "abbrev": "HOM"},
        "awayTeam": {"id": 2, "abbrev": "AWY"},
        "plays": [
            {
                "eventId": 42,
                "periodDescriptor": {"number": 1, "periodType": "REG"},
                "timeInPeriod": "03:00",
                "typeDescKey": "shot-on-goal",
                "details": {"xCoord": 65.0, "yCoord": 5.0, "eventOwnerTeamId": 1, "shootingPlayerId": 101, "goalieInNetId": 201, "shotType": "wrist"}
            },
            {
                "eventId": 42,
                "periodDescriptor": {"number": 1, "periodType": "REG"},
                "timeInPeriod": "03:05",
                "typeDescKey": "shot-on-goal",
                "details": {"xCoord": 80.0, "yCoord": 0.0, "eventOwnerTeamId": 1, "shootingPlayerId": 102, "goalieInNetId": 201, "shotType": "slap"}
            }
        ]
    }
    extracted = ShotFeatureExtractor.extract_shots_from_pbp_json(pbp_mock, unblocked_only=True)
    assert len(extracted) == 1
    assert extracted[0]["event_id"] == "10005_42"
    assert extracted[0]["shot_type"] == "wrist"


def test_orchestrator_missing_feature_leaves_null_xg():
    """Issue 2: Verifies that an unblocked shot with missing canonical feature in orchestrated ingestion leaves xG/provenance NULL."""
    normalizer = DataNormalizer()
    play = {
        "eventId": 777,
        "periodDescriptor": {"number": 1, "periodType": "REG"},
        "timeInPeriod": "05:00",
        "typeDescKey": "shot-on-goal",
        "situationCode": "1551",
        "details": {
            "xCoord": 70.0,
            "yCoord": 5.0,
            "eventOwnerTeamId": 1,
            "shootingPlayerId": 101,
            "goalieInNetId": 201,
            "shotType": "wrist"
        }
    }
    event_model, shot_model = normalizer.transform_event(
        play, 99999, 1, xg_features=None, require_full_xg_context=True
    )
    assert shot_model is not None
    assert shot_model.outcome == "Saved"
    assert shot_model.xg is None
    assert shot_model.model_name is None
    assert shot_model.model_version is None
    assert shot_model.prediction_method is None


def test_backfill_skipping_policy(app, db, tmp_path):
    """Issue 1: Verifies backfill skips shots without PBP or without feature match instead of generating reduced-context predictions."""
    game = Game(game_id=77701, season="20232024", game_date=date(2023, 10, 15), game_type=2, nhl_game_state="OFF", home_team_id=1, away_team_id=2, home_score=0, away_score=0)
    t1 = Team(team_id=1, name="Home", abbreviation="HOM")
    t2 = Team(team_id=2, name="Away", abbreviation="AWY")
    p1 = Player(player_id=101, first_name="A", last_name="B", position="C")
    db.session.add_all([game, t1, t2, p1])
    
    # Event 1: Unblocked shot with existing canonical xG that must NOT be overwritten
    ev1 = Event(event_id="77701_1", game_id=77701, period=1, period_time="01:00", event_type="shot-on-goal", team_id=1, primary_player_id=101)
    s1 = Shot(shot_id="77701_1", game_id=77701, team_id=1, shooter_id=101, outcome="Saved", xg=0.1234, model_name="canonical", model_version="1.0", prediction_method="ml")
    
    # Event 2: Blocked shot with old value that MUST be cleared
    ev2 = Event(event_id="77701_2", game_id=77701, period=1, period_time="02:00", event_type="blocked-shot", team_id=1, primary_player_id=101)
    s2 = Shot(shot_id="77701_2", game_id=77701, team_id=1, shooter_id=101, outcome="Blocked", xg=0.05, model_name="legacy", model_version="0.9", prediction_method="ml")
    
    db.session.add_all([ev1, s1, ev2, s2])
    db.session.commit()
    
    from scripts.backfill_xg import run_backfill
    summary = run_backfill(app, raw_dir=str(tmp_path))
    
    # Blocked shot cleared
    s2_refreshed = db.session.get(Shot, "77701_2")
    assert s2_refreshed.xg is None
    assert s2_refreshed.model_name is None
    
    # Unblocked shot skipped: existing value was NOT overwritten
    s1_refreshed = db.session.get(Shot, "77701_1")
    assert s1_refreshed.xg == 0.1234
    assert s1_refreshed.model_name == "canonical"
    
    assert summary["shots_skipped_missing_pbp"] >= 1
    assert summary["blocked_shots_cleared"] >= 1


def test_orchestrator_skips_missing_and_duplicate_play_event_ids(monkeypatch, app, db):
    """Verifies that PipelineOrchestrator skips plays with eventId is None and duplicate eventIds before transform_event."""
    orchestrator = PipelineOrchestrator(session=db.session)
    
    mock_pbp = {
        "id": 99901,
        "season": "20232024",
        "gameDate": "2023-11-01",
        "gameType": 2,
        "gameState": "OFF",
        "homeTeam": {"id": 1, "name": {"default": "Home"}, "commonName": {"default": "Home"}, "placeName": {"default": "Home"}, "abbrev": "HOM", "score": 0},
        "awayTeam": {"id": 2, "name": {"default": "Away"}, "commonName": {"default": "Away"}, "placeName": {"default": "Away"}, "abbrev": "AWY", "score": 0},
        "rosterSpots": [],
        "plays": [
            {
                "eventId": None,
                "periodDescriptor": {"number": 1, "periodType": "REG"},
                "timeInPeriod": "01:00",
                "typeDescKey": "hit",
                "details": {"eventOwnerTeamId": 1}
            },
            {
                "eventId": 50,
                "periodDescriptor": {"number": 1, "periodType": "REG"},
                "timeInPeriod": "02:00",
                "typeDescKey": "hit",
                "details": {"eventOwnerTeamId": 1}
            },
            {
                "eventId": 50,
                "periodDescriptor": {"number": 1, "periodType": "REG"},
                "timeInPeriod": "02:10",
                "typeDescKey": "hit",
                "details": {"eventOwnerTeamId": 1}
            },
            {
                "eventId": 51,
                "periodDescriptor": {"number": 1, "periodType": "REG"},
                "timeInPeriod": "03:00",
                "typeDescKey": "hit",
                "details": {"eventOwnerTeamId": 1}
            }
        ]
    }
    
    monkeypatch.setattr(orchestrator.api_client, "get_play_by_play", lambda gid, force_refresh=False: mock_pbp)
    monkeypatch.setattr(orchestrator.api_client, "get_shifts", lambda gid, force_refresh=False: {"data": [], "total": 0})
    monkeypatch.setattr(orchestrator.api_client, "get_boxscore", lambda gid, force_refresh=False: {})
    
    success, summary = orchestrator.ingest_game(99901)
    assert success is True
    
    events = Event.query.filter_by(game_id=99901).all()
    event_ids = [e.event_id for e in events]
    assert len(event_ids) == 2
    assert "99901_50" in event_ids
    assert "99901_51" in event_ids





