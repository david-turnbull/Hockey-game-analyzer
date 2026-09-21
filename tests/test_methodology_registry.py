"""
Tests for Stage 3 Metric & Model Methodology Registry.
Verifies repository grounding, completeness, unique keys, metadata integrity,
artifact hashes, API endpoint availability, Jinja template rendering, and zero analytical regression.
"""

import pytest
from flask import render_template_string
from app.services.methodology_registry import MethodologyRegistry, MetricDefinition, ModelCard


def test_required_metrics_exist_and_unique():
    """Verifies that all 9 mandatory metrics exist in the central registry with unique keys."""
    required_keys = [
        "cf_pct",
        "ff_pct",
        "on_ice_xg_pct",
        "xg",
        "goals_above_expected",
        "shooting_pct",
        "expected_conversion_pct",
        "goals_per_60",
        "xg_per_60"
    ]
    metrics = MethodologyRegistry.list_metrics()
    metric_keys = [m.key for m in metrics]

    assert len(metric_keys) == len(set(metric_keys)), "Metric keys must be unique"

    for key in required_keys:
        metric = MethodologyRegistry.get_metric(key)
        assert metric is not None, f"Required metric key '{key}' missing from registry"
        assert isinstance(metric, MetricDefinition)
        assert metric.key == key


def test_expanded_metric_metadata_completeness():
    """Verifies that all metric definitions contain robust, non-empty metadata fields including inputs and methodology."""
    metrics = MethodologyRegistry.list_metrics()
    assert len(metrics) >= 9

    for m in metrics:
        d = m.to_dict()
        assert d["key"]
        assert d["name"]
        assert d["category"] in ["possession_5v5", "individual_counting", "individual_rates", "advanced_efficiency"]
        assert len(d["definition"]) > 10
        assert len(d["formula"]) > 3
        assert isinstance(d["inputs"], list) and len(d["inputs"]) > 0
        assert d["strength_context"]
        assert d["units"]
        assert len(d["interpretation"]) > 10
        assert len(d["caveats"]) > 10
        assert d["version"]
        assert d["references_or_methodology"]


def test_required_model_cards_exist_and_unique():
    """Verifies that all 4 mandatory production model cards exist in the central registry with unique keys."""
    required_keys = [
        "xg",
        "win_probability",
        "score_projection",
        "elo"
    ]
    cards = MethodologyRegistry.list_model_cards()
    card_keys = [c.key for c in cards]

    assert len(card_keys) == len(set(card_keys)), "Model card keys must be unique"

    for key in required_keys:
        card = MethodologyRegistry.get_model_card(key)
        assert card is not None, f"Required model card '{key}' missing from registry"
        assert isinstance(card, ModelCard)
        assert card.key == key


def test_grounded_model_card_provenance_and_artifact_hashes():
    """Verifies that model cards reflect actual repository artifacts, features, and SHA256 hashes."""
    # 1. xG Model Card Grounding
    xg_card = MethodologyRegistry.get_model_card("xg")
    assert xg_card.name == "pucklens-xg-logistic"
    assert xg_card.version == "1.0.0"
    assert xg_card.model_type == "LogisticRegressionXGModel"
    assert len(xg_card.features) == 21
    assert xg_card.evaluation_metrics["log_loss"] == 0.2127
    assert xg_card.evaluation_metrics["roc_auc"] == 0.7494

    # 2. Win Probability Model Card Grounding
    win_card = MethodologyRegistry.get_model_card("win_probability")
    assert win_card.name == "pucklens-win"
    assert win_card.version == "v1.4.0"
    assert win_card.model_type == "HistGradientBoostingClassifier (with isotonic calibration)"
    assert win_card.artifact_hash == "63cf3cec7d11b38004c590503c89b0a686ae4a9a350fd497bc93087e71bf58f9"
    assert len(win_card.features) == 11
    assert "rest_differential" in win_card.features
    assert "l10_xgf_pct_diff" in win_card.features

    # 3. Score Projection Model Card Grounding
    score_card = MethodologyRegistry.get_model_card("score_projection")
    assert score_card.version == "v1.4.0"
    assert "Independent Poisson" in score_card.model_type
    assert score_card.artifact_hash == "c1587ea4d9e0fb6c586dd37c8d918cc8338b5488f03945ebbd40f89fa5c28c32"
    assert score_card.evaluation_metrics["training_samples"] == 3936

    # 4. Elo Model Card Grounding
    elo_card = MethodologyRegistry.get_model_card("elo")
    assert elo_card.version == "1.4.0"
    assert elo_card.evaluation_metrics["initial_elo"] == 1500.0
    assert elo_card.evaluation_metrics["base_k_factor"] == 20.0
    assert elo_card.evaluation_metrics["home_advantage_points"] == 35.0
    assert elo_card.evaluation_metrics["season_regression_rate"] == 0.25


def test_metric_category_filtering():
    """Verifies filtering metric definitions by category."""
    possession_metrics = MethodologyRegistry.list_metrics(category="possession_5v5")
    assert len(possession_metrics) == 3
    keys = [m.key for m in possession_metrics]
    assert set(keys) == {"cf_pct", "ff_pct", "on_ice_xg_pct"}


def test_full_methodology_dictionary():
    """Verifies to_dict conversion for API consumers."""
    data = MethodologyRegistry.get_all_methodology()
    assert "metrics" in data
    assert "models" in data
    assert len(data["metrics"]) >= 9
    assert len(data["models"]) >= 4


def test_methodology_api_routes(client):
    """Verifies REST API endpoints for methodology metadata."""
    resp = client.get("/api/v1/methodology")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "metrics" in data and "models" in data

    resp_m = client.get("/api/v1/methodology/metrics?category=possession_5v5")
    assert resp_m.status_code == 200
    m_list = resp_m.get_json()
    assert len(m_list) == 3

    resp_card = client.get("/api/v1/methodology/models/xg")
    assert resp_card.status_code == 200
    card_data = resp_card.get_json()
    assert card_data["key"] == "xg"
    assert card_data["name"] == "pucklens-xg-logistic"

    resp_404 = client.get("/api/v1/methodology/models/nonexistent_model")
    assert resp_404.status_code == 404


def test_real_jinja_template_rendering(app):
    """Verifies that Jinja context processor enables template rendering of methodology metrics."""
    with app.test_request_context("/"):
        rendered_metric = render_template_string("{{ methodology_registry.get_metric('cf_pct').name }}")
        assert rendered_metric == "Corsi For % (CF%)"

        rendered_model = render_template_string("{{ methodology_registry.get_model_card('win_probability').name }}")
        assert rendered_model == "pucklens-win"
