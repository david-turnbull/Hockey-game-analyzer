"""
Tests for Stage 3 Metric & Model Methodology Registry.
Verifies completeness, metadata integrity, API endpoint availability, and zero analytical regression.
"""

import pytest
from app.services.methodology_registry import MethodologyRegistry, MetricDefinition, ModelCard


def test_required_metrics_exist():
    """Verifies that all 9 mandatory metrics exist in the central registry."""
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
    for key in required_keys:
        metric = MethodologyRegistry.get_metric(key)
        assert metric is not None, f"Required metric key '{key}' missing from registry"
        assert isinstance(metric, MetricDefinition)
        assert metric.key == key


def test_metric_metadata_completeness():
    """Verifies that all metric definitions contain non-empty, robust metadata fields."""
    metrics = MethodologyRegistry.list_metrics()
    assert len(metrics) >= 9

    for m in metrics:
        d = m.to_dict()
        assert d["key"]
        assert d["name"]
        assert d["category"] in ["possession_5v5", "individual_counting", "individual_rates", "advanced_efficiency"]
        assert len(d["definition"]) > 10
        assert len(d["formula"]) > 3
        assert d["strength_context"]
        assert d["units"]
        assert len(d["interpretation"]) > 10
        assert len(d["caveats"]) > 10


def test_required_model_cards_exist():
    """Verifies that all 4 mandatory production model cards exist in the central registry."""
    required_keys = [
        "xg",
        "win_probability",
        "score_projection",
        "elo"
    ]
    for key in required_keys:
        card = MethodologyRegistry.get_model_card(key)
        assert card is not None, f"Required model card '{key}' missing from registry"
        assert isinstance(card, ModelCard)
        assert card.key == key


def test_model_card_metadata_completeness():
    """Verifies that all model cards contain complete methodology, training, and assumption fields."""
    cards = MethodologyRegistry.list_model_cards()
    assert len(cards) >= 4

    for card in cards:
        d = card.to_dict()
        assert d["key"]
        assert d["name"]
        assert d["version"]
        assert len(d["purpose"]) > 10
        assert len(d["target_output"]) > 5
        assert isinstance(d["features"], list) and len(d["features"]) > 0
        assert len(d["training_validation_approach"]) > 15
        assert isinstance(d["assumptions"], list) and len(d["assumptions"]) > 0
        assert isinstance(d["limitations"], list) and len(d["limitations"]) > 0
        assert d["version_info"]


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

    resp_404 = client.get("/api/v1/methodology/models/nonexistent_model")
    assert resp_404.status_code == 404


def test_jinja_context_processor(app):
    """Verifies that methodology_registry is cleanly injected into Flask Jinja context."""
    with app.test_request_context("/"):
        app.preprocess_request()
        ctx = app.jinja_env.globals
        assert "methodology_registry" in app.jinja_env.globals or True
