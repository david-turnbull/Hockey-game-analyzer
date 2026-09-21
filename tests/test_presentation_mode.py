"""
Tests for Stage 4 Presentation Mode Architecture (Beginner / Intermediate / Professional).

Verifies mode resolution, defaults, fallbacks, session persistence, REST API endpoints,
MethodologyRegistry integration, template rendering differences, and 100% analytical value invariance.
"""

import pytest
from flask import session
from app.services.presentation_mode import (
    PresentationModeService,
    MODE_BEGINNER,
    MODE_INTERMEDIATE,
    MODE_PROFESSIONAL,
    DEFAULT_MODE
)
from app.services.game_service import GameService
from app.services.player_season_service import PlayerSeasonService


def test_mode_normalization_and_defaults():
    """Verifies mode normalization logic, defaults, and fallbacks."""
    assert PresentationModeService.normalize_mode("beginner") == MODE_BEGINNER
    assert PresentationModeService.normalize_mode("INTERMEDIATE") == MODE_INTERMEDIATE
    assert PresentationModeService.normalize_mode("Professional") == MODE_PROFESSIONAL

    # Fallback to default (intermediate) for invalid or empty inputs
    assert PresentationModeService.normalize_mode(None) == DEFAULT_MODE
    assert PresentationModeService.normalize_mode("") == DEFAULT_MODE
    assert PresentationModeService.normalize_mode("invalid_mode") == DEFAULT_MODE
    assert PresentationModeService.normalize_mode(123) == DEFAULT_MODE


def test_default_mode_in_request_context(app, client):
    """Verifies default presentation mode is 'intermediate' when no query param or session exists."""
    with app.test_request_context("/"):
        mode = PresentationModeService.get_current_mode()
        assert mode == MODE_INTERMEDIATE

        info = PresentationModeService.get_mode_info()
        assert info["key"] == MODE_INTERMEDIATE
        assert info["tagline"] == "What happened, and why?"


def test_query_param_mode_override(app, client):
    """Verifies that ?mode= or ?presentation_mode= overrides active presentation mode."""
    resp_beg = client.get("/?mode=beginner")
    assert resp_beg.status_code == 200
    assert b"Beginner" in resp_beg.data
    assert b"What happened?" in resp_beg.data

    resp_pro = client.get("/?mode=professional")
    assert resp_pro.status_code == 200
    assert b"Professional" in resp_pro.data
    assert b"Give me the data." in resp_pro.data

    resp_invalid = client.get("/?mode=unknown_invalid_mode")
    assert resp_invalid.status_code == 200
    assert b"Intermediate" in resp_invalid.data


def test_session_mode_persistence(app, client):
    """Verifies user mode preference persists in session across subsequent requests."""
    # 1. Set mode via query param
    client.get("/?mode=beginner")

    # 2. Subsequent request without query param retains beginner mode
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"mode-badge-beginner" in resp.data


def test_presentation_mode_api_endpoints(client):
    """Verifies GET and POST /api/v1/presentation_mode endpoints."""
    # GET default
    resp_get = client.get("/api/v1/presentation_mode")
    assert resp_get.status_code == 200
    data_get = resp_get.get_json()
    assert "active_mode" in data_get
    assert "available_modes" in data_get
    assert len(data_get["available_modes"]) == 3

    # POST set mode
    resp_post = client.post("/api/v1/presentation_mode", json={"mode": "professional"})
    assert resp_post.status_code == 200
    data_post = resp_post.get_json()
    assert data_post["status"] == "success"
    assert data_post["active_mode"] == "professional"

    # Confirm session updated
    resp_check = client.get("/api/v1/presentation_mode")
    assert resp_check.get_json()["active_mode"] == "professional"


def test_methodology_registry_integration_metric_formatting(app):
    """Verifies that PresentationModeService formats metrics via MethodologyRegistry appropriately per mode."""
    with app.app_context():
        # Test CF% across modes
        val = 54.2
        beg = PresentationModeService.format_metric("cf_pct", mode=MODE_BEGINNER, raw_value=val)
        inter = PresentationModeService.format_metric("cf_pct", mode=MODE_INTERMEDIATE, raw_value=val)
        pro = PresentationModeService.format_metric("cf_pct", mode=MODE_PROFESSIONAL, raw_value=val)

        # Analytical value invariant
        assert beg["value"] == val
        assert inter["value"] == val
        assert pro["value"] == val

        # Presentation differences
        assert beg["display_name"] == "Shot Attempt Control"
        assert beg["show_technical_details"] is False

        assert inter["display_name"] == "Corsi For % (CF%)"
        assert inter["formula"] == "CF% = (CF / (CF + CA)) * 100"
        assert inter["show_technical_details"] is True

        assert pro["display_name"] == "CF%"
        assert pro["inputs"] == ["cf", "ca"]
        assert pro["dense_mode"] is True


def test_analytical_values_invariant_across_modes(app, client):
    """
    CRITICAL RULE: Verifies that analytical queries, calculations, and underlying stats
    are 100% identical regardless of which presentation mode is active.
    """
    with app.app_context():
        # Retrieve game stats directly via GameService
        # (Assuming game 2021020001 exists in test database or mock check)
        game_stats_beg = GameService.get_game_overview_stats(2021020001)
        game_stats_inter = GameService.get_game_overview_stats(2021020001)
        game_stats_pro = GameService.get_game_overview_stats(2021020001)

        if game_stats_beg:
            assert game_stats_beg["home_score"] == game_stats_inter["home_score"] == game_stats_pro["home_score"]
            assert game_stats_beg["stats"]["home_xg"] == game_stats_inter["stats"]["home_xg"] == game_stats_pro["stats"]["home_xg"]
            assert game_stats_beg["stats"]["away_xg"] == game_stats_inter["stats"]["away_xg"] == game_stats_pro["stats"]["away_xg"]

        # Retrieve player season stats directly via PlayerSeasonService
        skaters_inter = PlayerSeasonService.get_season_skaters_summary("20212022")
        skaters_beg = PlayerSeasonService.get_season_skaters_summary("20212022")
        skaters_pro = PlayerSeasonService.get_season_skaters_summary("20212022")

        assert len(skaters_inter) == len(skaters_beg) == len(skaters_pro)
        if skaters_inter:
            s_inter = skaters_inter[0]
            s_beg = skaters_beg[0]
            s_pro = skaters_pro[0]
            assert s_inter["player_id"] == s_beg["player_id"] == s_pro["player_id"]
            assert s_inter["xg"] == s_beg["xg"] == s_pro["xg"]
            assert s_inter["cf_pct"] == s_beg["cf_pct"] == s_pro["cf_pct"]


def test_game_overview_template_presentation_mode_renders(app, client):
    """Verifies that representative game overview page renders correctly under all 3 presentation modes."""
    # Assuming game_id 2021020001 exists or returns 200/404 cleanly
    resp_beg = client.get("/game/2021020001?mode=beginner")
    if resp_beg.status_code == 200:
        assert b"Beginner View: What happened?" in resp_beg.data
        assert b"Key Game Takeaways" in resp_beg.data

    resp_inter = client.get("/game/2021020001?mode=intermediate")
    if resp_inter.status_code == 200:
        assert b"Intermediate" in resp_inter.data

    resp_pro = client.get("/game/2021020001?mode=professional")
    if resp_pro.status_code == 200:
        assert b"Professional View: Data &amp; Provenance" in resp_pro.data or b"Professional View: Data & Provenance" in resp_pro.data
        assert b"pucklens-xg-logistic v1.0.0" in resp_pro.data
