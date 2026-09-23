"""
Tests for Stage 3 Metric & Model Methodology Registry.
Verifies repository grounding, completeness, unique keys, metadata integrity,
source-driven artifact hashes, API endpoint availability, Jinja template rendering, and zero analytical regression.
"""

import json
import hashlib
from pathlib import Path
import pytest
from flask import render_template_string
from app.services.methodology_registry import MethodologyRegistry, MetricDefinition, ModelCard

REPO_ROOT = Path(__file__).resolve().parent.parent


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
    """Verifies that model cards reflect actual repository metadata files, features, and SHA256 hashes."""
    # Load source files directly from repository artifacts
    xg_meta_path = REPO_ROOT / "models" / "xg" / "metadata.json"
    win_manifest_path = REPO_ROOT / "models" / "forecasting" / "pucklens-win-v1.4.0.json"
    score_params_path = REPO_ROOT / "models" / "forecasting" / "score_candidate_params_v1.4.0.json"
    stage5_report_path = REPO_ROOT / "reports" / "stage5_score_projection_validation.json"

    with open(xg_meta_path, "r", encoding="utf-8") as f:
        xg_meta = json.load(f)

    with open(win_manifest_path, "r", encoding="utf-8") as f:
        win_manifest = json.load(f)

    with open(score_params_path, "r", encoding="utf-8") as f:
        score_params = json.load(f)

    score_params_raw_bytes = score_params_path.read_bytes().replace(b"\r\n", b"\n")
    computed_score_file_sha256 = hashlib.sha256(score_params_raw_bytes).hexdigest()

    with open(stage5_report_path, "r", encoding="utf-8") as f:
        stage5_report = json.load(f)

    # 1. xG Model Card Grounding against models/xg/metadata.json
    xg_card = MethodologyRegistry.get_model_card("xg")
    assert xg_card is not None
    assert xg_card.name == xg_meta["name"]
    assert xg_card.version == xg_meta["version"]
    assert xg_card.model_type == xg_meta["model_type"]
    assert xg_card.features == xg_meta["features"]
    assert xg_card.evaluation_metrics["log_loss"] == xg_meta["metrics"]["log_loss"]
    assert xg_card.evaluation_metrics["brier_score"] == xg_meta["metrics"]["brier_score"]
    assert xg_card.evaluation_metrics["roc_auc"] == xg_meta["metrics"]["roc_auc"]
    assert xg_card.evaluation_metrics["actual_goals"] == xg_meta["metrics"]["actual_goals"]
    assert xg_card.evaluation_metrics["expected_goals"] == xg_meta["metrics"]["expected_goals"]
    assert xg_card.evaluation_metrics["total_shots"] == xg_meta["metrics"]["total_shots"]
    assert xg_card.provenance["git_commit"] == xg_meta["git_commit"]
    assert xg_card.provenance["scikit_learn_version"] == xg_meta["scikit_learn_version"]

    # 2. Win Probability Model Card Grounding against models/forecasting/pucklens-win-v1.4.0.json
    win_card = MethodologyRegistry.get_model_card("win_probability")
    assert win_card is not None
    assert win_card.name == win_manifest["model_name"]
    assert win_card.version == win_manifest["model_version"]
    assert win_card.artifact_hash == win_manifest["artifact_sha256"]
    assert win_card.features == win_manifest["feature_names"]
    assert win_card.evaluation_metrics["training_samples"] == win_manifest["number_of_training_samples"]
    assert win_card.evaluation_metrics["calibration_samples"] == win_manifest["number_of_calibration_samples"]
    assert win_card.evaluation_metrics["selection_metric"] == win_manifest["model_selection_metric"]
    assert win_card.evaluation_metrics["calibration_method"] == win_manifest["calibration_method"]
    assert win_card.provenance["git_commit_sha"] == win_manifest["git_commit_sha"]
    assert win_card.provenance["run_uuid"] == win_manifest["run_uuid"]

    # 3. Score Projection Model Card Grounding against score params & stage5 report
    score_card = MethodologyRegistry.get_model_card("score_projection")
    assert score_card is not None
    assert score_card.version == score_params["model_version"]
    assert "Independent Poisson" in score_card.model_type
    assert score_card.evaluation_metrics["training_samples"] == score_params["sample_count"]
    assert score_card.provenance["fitting_git_sha"] == score_params["fitting_git_sha"]
    assert score_card.provenance["training_data_snapshot_hash"] == score_params["training_data_snapshot_hash"]
    assert score_card.provenance["parameter_payload_sha256"] == score_params["parameter_payload_sha256"]
    assert score_card.provenance["parameter_payload_sha256"] == stage5_report["provenance"]["parameter_payload_sha256"]
    assert score_card.provenance["parameter_artifact_file_sha256"] == stage5_report["provenance"]["parameter_artifact_file_sha256"]
    assert score_card.artifact_hash == computed_score_file_sha256
    assert score_card.artifact_hash == stage5_report["provenance"]["parameter_artifact_file_sha256"]

    # 4. Elo Model Card Grounding against app.services.elo_service module constants
    from app.services.elo_service import INITIAL_ELO, BASE_K, HOME_ADVANTAGE, SEASON_REGRESSION
    elo_card = MethodologyRegistry.get_model_card("elo")
    assert elo_card is not None
    assert elo_card.evaluation_metrics["initial_elo"] == INITIAL_ELO
    assert elo_card.evaluation_metrics["base_k_factor"] == BASE_K
    assert elo_card.evaluation_metrics["home_advantage_points"] == HOME_ADVANTAGE
    assert elo_card.evaluation_metrics["season_regression_rate"] == SEASON_REGRESSION


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
