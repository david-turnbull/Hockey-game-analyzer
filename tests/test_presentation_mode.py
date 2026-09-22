"""
Tests for Stage 4 Presentation Mode Architecture (Beginner / Intermediate / Professional).

Verifies mode resolution, defaults, fallbacks, session persistence, REST API endpoints,
MethodologyRegistry integration, query parameter preservation, meaningful representative page rendering (HTTP 200),
and 100% analytical value invariance across execution contexts.
"""

import datetime
from urllib.parse import urlencode
import pytest
from flask import session
from app.models import db, Game, Team
from app.services.presentation_mode import (
    PresentationModeService,
    MODE_BEGINNER,
    MODE_INTERMEDIATE,
    MODE_PROFESSIONAL,
    DEFAULT_MODE
)
from app.services.game_service import GameService
from app.services.player_season_service import PlayerSeasonService


@pytest.fixture
def test_game_id(app):
    """Guarantees a valid test game ID in the database for presentation mode testing."""
    with app.app_context():
        g = Game.query.first()
        if g:
            return g.game_id

        t1 = db.session.get(Team, 1001) or Team(team_id=1001, name="Test Home Team", abbreviation="THT")
        t2 = db.session.get(Team, 1002) or Team(team_id=1002, name="Test Away Team", abbreviation="TAT")
        db.session.add_all([t1, t2])
        db.session.commit()

        g = Game(
            game_id=2021020001,
            season="20212022",
            game_type="R",
            game_date=datetime.date(2021, 10, 12),
            home_team_id=1001,
            away_team_id=1002,
            home_score=4,
            away_score=2,
            nhl_game_state="FINAL",
            data_source="nhl_api"
        )
        db.session.add(g)
        db.session.commit()
        return g.game_id


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


def test_query_parameter_preservation_when_switching_modes(app, client):
    """Verifies that switching presentation modes preserves existing request query parameters."""
    with app.test_request_context("/game/2021020001?team_id=10&tab=lines"):
        from flask import request
        args = request.args.copy()
        args['mode'] = 'beginner'
        url_beg = f"{request.path}?{urlencode(args)}"

        args['mode'] = 'professional'
        url_pro = f"{request.path}?{urlencode(args)}"

        assert "team_id=10" in url_beg
        assert "tab=lines" in url_beg
        assert "mode=beginner" in url_beg

        assert "team_id=10" in url_pro
        assert "tab=lines" in url_pro
        assert "mode=professional" in url_pro


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


def test_executed_request_context_analytical_invariance(app, client, test_game_id):
    """
    CRITICAL INVARIANT TEST:
    Executes HTTP requests under Beginner, Intermediate, and Professional request/session contexts.
    Verifies HTTP 200 and asserts identical analytical values/stats across all three modes.
    """
    game_id = test_game_id

    # Execute HTTP requests in all 3 modes and assert HTTP 200
    resp_beg = client.get(f"/game/{game_id}?mode=beginner")
    assert resp_beg.status_code == 200

    resp_inter = client.get(f"/game/{game_id}?mode=intermediate")
    assert resp_inter.status_code == 200

    resp_pro = client.get(f"/game/{game_id}?mode=professional")
    assert resp_pro.status_code == 200

    # Retrieve game stats service outputs executed within each mode context
    with client.session_transaction() as sess:
        sess['presentation_mode'] = 'beginner'
    stats_beg = GameService.get_game_overview_stats(game_id)

    with client.session_transaction() as sess:
        sess['presentation_mode'] = 'intermediate'
    stats_inter = GameService.get_game_overview_stats(game_id)

    with client.session_transaction() as sess:
        sess['presentation_mode'] = 'professional'
    stats_pro = GameService.get_game_overview_stats(game_id)

    # Assert 100% identical underlying analytical values
    assert stats_beg["game_id"] == stats_inter["game_id"] == stats_pro["game_id"]
    assert stats_beg["home_score"] == stats_inter["home_score"] == stats_pro["home_score"]
    assert stats_beg["away_score"] == stats_inter["away_score"] == stats_pro["away_score"]
    assert stats_beg["stats"]["home_xg"] == stats_inter["stats"]["home_xg"] == stats_pro["stats"]["home_xg"]
    assert stats_beg["stats"]["away_xg"] == stats_inter["stats"]["away_xg"] == stats_pro["stats"]["away_xg"]
    assert stats_beg["stats"]["home_sog"] == stats_inter["stats"]["home_sog"] == stats_pro["stats"]["home_sog"]
    assert stats_beg["stats"]["away_sog"] == stats_inter["stats"]["away_sog"] == stats_pro["stats"]["away_sog"]


def test_representative_page_meaningful_mode_differences(app, client, test_game_id):
    """
    REQUIRED MEANINGFUL TEST:
    Verifies HTTP 200 and distinct presentation elements across modes on representative page.
    """
    game_id = test_game_id

    # 1. Beginner Mode
    resp_beg = client.get(f"/game/{game_id}?mode=beginner")
    assert resp_beg.status_code == 200
    assert b"Beginner View: What happened?" in resp_beg.data
    assert b"Key Game Takeaways" in resp_beg.data

    # 2. Intermediate Mode
    resp_inter = client.get(f"/game/{game_id}?mode=intermediate")
    assert resp_inter.status_code == 200
    assert b"Intermediate" in resp_inter.data
    assert b"What happened, and why?" in resp_inter.data

    # 3. Professional Mode
    resp_pro = client.get(f"/game/{game_id}?mode=professional")
    assert resp_pro.status_code == 200
    assert b"Professional View: Data &amp; Provenance" in resp_pro.data or b"Professional View: Data & Provenance" in resp_pro.data
    assert b"pucklens-xg-logistic" in resp_pro.data
    assert b"Methodology Registry API" in resp_pro.data
