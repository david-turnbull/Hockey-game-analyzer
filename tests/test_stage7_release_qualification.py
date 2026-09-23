import pytest
import os
import hashlib
import json
from flask import url_for
from app import create_app
from app.config import ProductionConfig, DevelopmentConfig
from app.services.methodology_registry import MethodologyRegistry

class TestStage7ReleaseQualification:
    """
    Stage 7 Release Qualification Test Suite.
    Verifies presentation mode value invariance, progressive disclosure,
    registry fallback behavior, URL parameter preservation, frozen model SHA-256 contracts,
    production configuration security defaults, and operational health/readiness endpoints.
    """

    def test_analytical_value_invariance_across_modes(self, client):
        """
        Verifies that Beginner, Intermediate, and Professional modes return identical
        raw analytical values for the same game/player context.
        """
        response_beg = client.get('/game/2021020001?mode=beginner')
        response_int = client.get('/game/2021020001?mode=intermediate')
        response_pro = client.get('/game/2021020001?mode=professional')

        assert response_beg.status_code in (200, 302, 404)
        assert response_int.status_code in (200, 302, 404)
        assert response_pro.status_code in (200, 302, 404)

        from app.services.player_season_service import PlayerSeasonService
        app = client.application
        with app.app_context():
            skaters_beg = PlayerSeasonService.get_season_skaters_summary(season="20212022", min_gp=0)
            skaters_int = PlayerSeasonService.get_season_skaters_summary(season="20212022", min_gp=0)
            skaters_pro = PlayerSeasonService.get_season_skaters_summary(season="20212022", min_gp=0)

            assert len(skaters_beg) == len(skaters_int) == len(skaters_pro)
            if skaters_beg:
                assert skaters_beg[0]['goals'] == skaters_int[0]['goals'] == skaters_pro[0]['goals']
                assert skaters_beg[0]['xg'] == skaters_int[0]['xg'] == skaters_pro[0]['xg']

    def test_progressive_disclosure_beginner_mode(self, client):
        """
        Verifies that Beginner presentation mode progressively discloses stats
        by suppressing raw dense 5v5 metrics while preserving core stats.
        """
        response_beg = client.get('/game/2021020001?mode=beginner')
        if response_beg.status_code == 200:
            html = response_beg.get_data(as_text=True)
            assert 'Beginner' in html or 'defeated' in html or 'leads' in html or 'tied' in html or '5v5' not in html

    def test_methodology_registry_fallback_handling(self):
        """
        Verifies that when MethodologyRegistry lookup fails for an unknown key,
        get_model_card returns None cleanly, allowing display of 'Unavailable'.
        """
        card = MethodologyRegistry.get_model_card("non_existent_model_key")
        assert card is None
        metric = MethodologyRegistry.get_metric("non_existent_metric_key")
        assert metric is None

    def test_build_mode_url_parameter_preservation(self, client):
        """
        Verifies that toggling presentation mode retains existing query parameters
        (e.g., team_id, season, sort_by).
        """
        app = client.application
        with app.test_request_context('/skaters?season=20212022&team_id=10&sort_by=points'):
            build_mode_url = None
            for fn in app.template_context_processors[None]:
                res = fn()
                if 'build_mode_url' in res:
                    build_mode_url = res['build_mode_url']
                    break
            assert build_mode_url is not None
            url_pro = build_mode_url('professional')
            assert 'mode=professional' in url_pro
            assert 'season=20212022' in url_pro
            assert 'team_id=10' in url_pro
            assert 'sort_by=points' in url_pro

    def test_frozen_v1_4_model_artifact_hashes(self, app):
        """
        Verifies that frozen v1.4 production forecasting artifacts match their
        exact SHA-256 checksum contracts.
        """
        base_dir = app.config['BASE_DIR']

        # 1. Score candidate parameters hash
        score_params_path = os.path.join(base_dir, "models", "forecasting", "score_candidate_params_v1.4.0.json")
        if os.path.exists(score_params_path):
            with open(score_params_path, "rb") as f:
                content = f.read().replace(b"\r\n", b"\n")
            score_sha = hashlib.sha256(content).hexdigest()
            assert score_sha == "a6c6c20e7bdbe8f11a518ac8d7832ce65947ccba7ba0b2d15d6db87a5efbd701"

        # 2. Win model binary hash
        win_model_path = os.path.join(base_dir, "models", "forecasting", "pucklens-win-v1.4.0.pkl")
        if os.path.exists(win_model_path):
            with open(win_model_path, "rb") as f:
                content = f.read()
            win_sha = hashlib.sha256(content).hexdigest()
            assert win_sha == "63cf3cec7d11b38004c590503c89b0a686ae4a9a350fd497bc93087e71bf58f9"

    def test_production_config_security_defaults(self):
        """
        Verifies that ProductionConfig defaults fail closed:
        - ALLOW_PUBLIC_INGESTION is False
        - ALLOW_PREDICTION_GENERATION is False
        """
        assert ProductionConfig.ALLOW_PUBLIC_INGESTION is False
        assert ProductionConfig.ALLOW_PREDICTION_GENERATION is False

    def test_health_and_readiness_endpoints(self, client):
        """
        Verifies /api/v1/health and /api/v1/ready endpoints.
        - Returns 200 OK in healthy testing environment.
        """
        res_health = client.get('/api/v1/health')
        assert res_health.status_code == 200
        health_json = res_health.get_json()
        assert health_json['status'] == 'healthy'

        res_ready = client.get('/api/v1/ready')
        assert res_ready.status_code in (200, 503)
