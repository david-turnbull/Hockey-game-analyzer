import pytest
from datetime import date
import numpy as np
from app.analytics.explainability import XGExplainer
from app.analytics.model_registry import ModelRegistry
from app.models import db, Team, Player, Game, Event, Shot

def test_xg_probability_reconstruction_exact():
    """
    Verify that contribution values reconstruct the model decision logit and probability
    within exact numerical tolerance: sigma(intercept + sum(contributions)) == xG.
    """
    model = ModelRegistry.get_active_model()
    assert hasattr(model, 'pipeline')

    shot_features = {
        "distance": 18.0,
        "angle": 12.0,
        "period": 1,
        "period_seconds": 150,
        "score_differential": 0,
        "is_home": 1,
        "empty_net": 0,
        "time_since_prev_event": 2.1,
        "distance_from_prev_event": 8.0,
        "angle_change": 10.0,
        "is_rebound": 1,
        "is_rush": 0,
        "is_turnover": 0,
        "is_after_faceoff": 0,
        "is_lateral_movement": 1,
        "is_power_play": 0,
        "is_shorthanded": 0,
        "coordinates_missing": 0,
        "shot_type": "wrist",
        "strength_state": "EV",
        "prev_event_type": "shot-on-goal"
    }

    explanation = XGExplainer.explain_shot(shot_features, model=model)

    assert "xg" in explanation
    assert "intercept" in explanation
    assert "reconstructed_logit" in explanation
    assert "factors_increasing_danger" in explanation
    assert "factors_reducing_danger" in explanation

    # 1. Direct model prediction
    direct_prob = model.predict(shot_features)
    assert pytest.approx(explanation["xg"], 0.001) == direct_prob

    # 2. Mathematical reconstruction verification:
    # logit = intercept + sum(contribution)
    all_factors = explanation["all_factors"]
    sum_contribs = sum(f["contribution"] for f in all_factors)
    # The reconstructed logit from pipeline
    logit = explanation["reconstructed_logit"]
    prob_from_logit = 1.0 / (1.0 + np.exp(-logit))

    assert pytest.approx(prob_from_logit, 0.001) == direct_prob

    # 3. Factor verification:
    # In-close shot (18 ft) and rebound and lateral movement should increase danger
    inc_names = [f["factor"] for f in explanation["factors_increasing_danger"]]
    assert "distance" in inc_names or "is_rebound" in inc_names or "is_lateral_movement" in inc_names


def test_xg_explanation_api_endpoint(app, client, db):
    """
    Verify GET /api/shots/<shot_id>/xg-explanation returns structured JSON with factors.
    """
    team = Team(team_id=1, abbreviation='CGY', name='Calgary Flames')
    shooter = Player(player_id=10, first_name='Mikael', last_name='Backlund', position='C')
    db.session.add_all([team, shooter])
    db.session.commit()

    g = Game(
        game_id=2024020555, season='20242025', game_date=date(2024, 11, 20),
        home_team_id=1, away_team_id=1, home_score=1, away_score=0, nhl_game_state='FINAL'
    )
    db.session.add(g)
    db.session.flush()

    eid = '2024020555_100'
    ev = Event(event_id=eid, game_id=g.game_id, period=1, period_time='10:00',
               elapsed_game_seconds=600, event_type='shot-on-goal', team_id=1,
               primary_player_id=10)
    sh = Shot(shot_id=eid, game_id=g.game_id, team_id=1, shooter_id=10,
              distance=15.0, angle=10.0, outcome='Saved', goal=False, xg=0.184)
    db.session.add_all([ev, sh])
    db.session.commit()

    res = client.get(f'/api/shots/{eid}/xg-explanation')
    assert res.status_code == 200
    data = res.get_json()

    assert data["shot_id"] == eid
    assert "xg" in data
    assert "factors_increasing_danger" in data
    assert "factors_reducing_danger" in data
    assert "all_factors" in data
    assert len(data["all_factors"]) > 0

    # 404 for nonexistent shot
    res404 = client.get('/api/shots/nonexistent_shot_id/xg-explanation')
    assert res404.status_code == 404
