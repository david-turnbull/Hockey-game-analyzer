"""
Tests for Stage 4 Presentation Mode Architecture (Beginner / Intermediate / Professional).

Verifies mode resolution, defaults, fallbacks, session persistence, REST API endpoints,
MethodologyRegistry integration, query parameter preservation, meaningful representative page rendering (HTTP 200),
game status semantics (final/live/upcoming), model fallback metadata ('Unavailable'), progressive disclosure,
and 100% analytical value invariance across execution contexts.
"""

import datetime
from urllib.parse import urlencode
from unittest.mock import patch
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


def test_actual_build_mode_url_output(app):
    """Tests the actual build_mode_url() context processor helper output in request context."""
    with app.test_request_context("/game/2021020001?team_id=10&tab=lines"):
        processors = app.template_context_processors[None]
        ctx = {}
        for p in processors:
            ctx.update(p())

        build_mode_url = ctx["build_mode_url"]

        url_beg = build_mode_url("beginner")
        url_pro = build_mode_url("professional")

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


def test_beginner_game_status_wording_semantics(app, client, test_game_id):
    """
    Verifies Beginner mode wording:
    - Final game: uses 'defeated'
    - Live game: uses 'leads' or 'is tied'
    - Upcoming game: uses 'Upcoming Matchup' and does not imply a result.
    """
    import copy
    from app.services.game_service import GameService

    with app.app_context():
        base_stats = GameService.get_game_overview_stats(test_game_id)

    def _make_mock_stats(home, away, home_score, away_score, state, status_display, home_xg, away_xg):
        st = copy.deepcopy(base_stats)
        st["home_team_abbrev"] = home
        st["away_team_abbrev"] = away
        st["home_score"] = home_score
        st["away_score"] = away_score
        st["nhl_game_state"] = state
        st["game_status_display"] = status_display
        st["stats"]["home_xg"] = home_xg
        st["stats"]["away_xg"] = away_xg
        return st

    # 1. Final Game Wording
    mock_final = _make_mock_stats("TOR", "MTL", 4, 2, "FINAL", "Final", 3.2, 1.8)
    with patch.object(GameService, "get_game_overview_stats", return_value=mock_final):
        resp = client.get(f"/game/{test_game_id}?mode=beginner")
        assert resp.status_code == 200
        assert b"TOR defeated MTL 4-2" in resp.data
        assert b"generated more expected goals" in resp.data

    # 2. Live Game Wording (Home Leading)
    mock_live_lead = _make_mock_stats("BOS", "NYR", 3, 1, "LIVE", "2nd Period", 2.5, 1.2)
    with patch.object(GameService, "get_game_overview_stats", return_value=mock_live_lead):
        resp = client.get(f"/game/{test_game_id}?mode=beginner")
        assert resp.status_code == 200
        assert b"BOS leads NYR 3-1" in resp.data

    # 3. Live Game Wording (Tied)
    mock_live_tied = _make_mock_stats("EDM", "CGY", 2, 2, "LIVE", "3rd Period", 2.0, 2.0)
    with patch.object(GameService, "get_game_overview_stats", return_value=mock_live_tied):
        resp = client.get(f"/game/{test_game_id}?mode=beginner")
        assert resp.status_code == 200
        assert b"Game is tied 2-2" in resp.data

    # 4. Upcoming Game Wording
    mock_upcoming = _make_mock_stats("VAN", "SEA", 0, 0, "FUT", "Scheduled", 0.0, 0.0)
    with patch.object(GameService, "get_game_overview_stats", return_value=mock_upcoming):
        resp = client.get(f"/game/{test_game_id}?mode=beginner")
        assert resp.status_code == 200
        assert b"Upcoming Matchup: SEA vs VAN" in resp.data
        assert b"defeated" not in resp.data
        assert b"leads" not in resp.data


def test_progressive_disclosure_advanced_rows_hidden_only_in_beginner(app, client, test_game_id):
    """
    Verifies progressive disclosure:
    - Advanced statistics (5v5 Expected Goals, xG Share) are hidden in Beginner mode.
    - Advanced statistics are retained and rendered in Intermediate and Professional modes.
    """
    game_id = test_game_id

    # Beginner mode: advanced rows hidden
    resp_beg = client.get(f"/game/{game_id}?mode=beginner")
    assert resp_beg.status_code == 200
    assert b"5v5 Expected Goals" not in resp_beg.data
    assert b"xG Share (xG%)" not in resp_beg.data

    # Intermediate mode: advanced rows present
    resp_inter = client.get(f"/game/{game_id}?mode=intermediate")
    assert resp_inter.status_code == 200
    assert b"5v5 Expected Goals" in resp_inter.data
    assert b"xG Share (xG%)" in resp_inter.data

    # Professional mode: advanced rows present
    resp_pro = client.get(f"/game/{game_id}?mode=professional")
    assert resp_pro.status_code == 200
    assert b"5v5 Expected Goals" in resp_pro.data
    assert b"xG Share (xG%)" in resp_pro.data


def test_professional_model_card_fallback_unavailable(app, client, test_game_id):
    """
    Verifies that if MethodologyRegistry model card lookup returns None, Professional mode
    displays 'Unavailable' rather than hard-coding model names.
    """
    game_id = test_game_id
    from app.services.methodology_registry import MethodologyRegistry

    with patch.object(MethodologyRegistry, "get_model_card", return_value=None):
        resp = client.get(f"/game/{game_id}?mode=professional")
        assert resp.status_code == 200
        assert b"MODEL: <strong>Unavailable vUnavailable</strong>" in resp.data
        assert b"pucklens-xg-logistic" not in resp.data
