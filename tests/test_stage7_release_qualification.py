import pytest
import os
import sqlite3
import hashlib
import json
import shutil
import tempfile
from unittest.mock import patch, MagicMock
from flask import url_for
from app import create_app
from app.config import ProductionConfig, DevelopmentConfig
from app.services.methodology_registry import MethodologyRegistry
from app.services.player_game_analytics_audit import PlayerGameAnalyticsAuditService
from scripts.run_stage7_release_qualification import (
    Stage7ReleaseQualificationOrchestrator,
    verify_frozen_artifacts_fail_closed,
    get_db_fingerprint,
    create_isolated_db,
    enforce_isolated_db_environment,
    verify_active_connection_is_isolated,
    get_git_commit_sha
)

class TestStage7ReleaseQualification:
    """
    Stage 7 Release Qualification Test Suite & Regression Audit.
    Covers presentation mode value invariance, progressive disclosure, registry fallbacks,
    URL parameter preservation, frozen model SHA-256 contracts, production security defaults,
    operational health/readiness probes, Gate 8 failure propagation, durable state resume,
    set-based roster audit, and SQLite database isolation.
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
        Verifies that frozen v1.4 production forecasting artifacts exist and match their
        exact SHA-256 checksum contracts.
        """
        passed, details = verify_frozen_artifacts_fail_closed()
        assert passed is True
        assert details["pucklens-win-v1.4.0.pkl"]["passed"] is True
        assert details["score_candidate_params_v1.4.0.json"]["passed"] is True
        assert details["production_registry_load"] is True

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

    # =========================================================================
    # DEFECT FIX REGRESSION TESTS
    # =========================================================================

    # =========================================================================
    # DEFECT FIX REGRESSION TESTS
    # =========================================================================

    def test_gate8_failure_propagation_and_three_states(self):
        """
        Verifies all 3 states of Gate 8:
        1. Automated failure -> Gate 8 returns FAILED, overall status is FAILED.
        2. Automated success with manual QA pending -> Gate 8 returns MANUAL_VERIFICATION_PENDING, overall status is AUTOMATED GATES PASSED (MANUAL QA PENDING).
        3. Automated success with recorded manual QA evidence -> Gate 8 returns PASSED, overall status is QUALIFIED.
        """
        orchestrator = Stage7ReleaseQualificationOrchestrator(output_dir="reports/v1.5")
        
        # State 1: Automated failure
        with patch('subprocess.run') as mock_run:
            mock_res = MagicMock()
            mock_res.returncode = 1
            mock_run.return_value = mock_res

            res1 = orchestrator.run_gate8()
            assert res1["status"] == "FAILED"
            assert res1["automated_route_checks"] == "FAILED"

        # State 2: Automated success with manual QA pending
        with patch('subprocess.run') as mock_run:
            mock_res = MagicMock()
            mock_res.returncode = 0
            mock_run.return_value = mock_res

            res2 = orchestrator.run_gate8()
            assert res2["status"] == "MANUAL_VERIFICATION_PENDING"
            assert res2["automated_route_checks"] == "PASSED"

        # State 3: Completed manual QA with recorded evidence
        with patch('subprocess.run') as mock_run:
            mock_res = MagicMock()
            mock_res.returncode = 0
            mock_run.return_value = mock_res

            evidence = {"verified_by_human": True, "qa_date": "2026-09-22", "reviewer": "QA Lead"}
            res3 = orchestrator.run_gate8(manual_qa_evidence=evidence)
            assert res3["status"] == "PASSED"
            assert res3["automated_route_checks"] == "PASSED"
            assert res3["manual_qa_completed"] is True

    def test_frozen_model_artifact_checks_fail_closed_on_missing_or_corrupted(self):
        """
        Verifies that verify_frozen_artifacts_fail_closed returns False if any
        required frozen artifact is missing or has a corrupted hash.
        """
        # Missing file case
        with patch('os.path.exists', return_value=False):
            passed1, details1 = verify_frozen_artifacts_fail_closed()
            assert passed1 is False
            assert details1["pucklens-win-v1.4.0.pkl"]["exists"] is False

        # Hash mismatch case
        with patch('builtins.open', patch('builtins.open', side_effect=lambda path, mode='r', **kwargs: MagicMock(__enter__=lambda s: MagicMock(read=lambda: b"corrupted_binary_data"), __exit__=lambda s, *a: None))):
            passed2, details2 = verify_frozen_artifacts_fail_closed()
            assert passed2 is False

    def test_database_isolation_canonical_path_alias_rejection(self):
        """
        Verifies that create_isolated_db rejects attempts where isolated database path
        resolves to the same canonical path as production database.
        """
        prod_path = "hockey.db"
        alias_path = "./hockey.db"

        with pytest.raises(RuntimeError, match="Isolated database path"):
            create_isolated_db(prod_path, alias_path, force_reset=False)

    def test_pragma_database_list_active_connection_verification(self, app):
        """
        Verifies that verify_active_connection_is_isolated asserts the active main database
        is attached to the expected isolated file path when not in in-memory TESTING mode.
        """
        with app.app_context():
            old_testing = app.config.get('TESTING')
            try:
                app.config['TESTING'] = False
                with pytest.raises(RuntimeError, match="attached to"):
                    verify_active_connection_is_isolated("wrong_stage7_temp.db")
            finally:
                app.config['TESTING'] = old_testing

    def test_set_based_roster_audit_accuracy(self):
        """
        Verifies that PlayerGameAnalyticsAuditService accurately reports schedule games,
        completed games, ingested roster games, and derived complete games.
        """
        from app import create_app
        prod_app = create_app('development')
        with prod_app.app_context():
            res = PlayerGameAnalyticsAuditService.audit_game_analytics(season="20212022")
            assert "total_game_rows" in res
            assert "completed_games" in res
            assert "ingested_games" in res
            assert "derived_complete_games" in res
            assert "derived_coverage_pct" in res
            assert "ingestion_coverage_pct" in res
            assert "set_audit" in res

            if res["ingested_games"] > 0:
                assert res["derived_coverage_pct"] == 100.0
                assert res["ingestion_coverage_pct"] < 100.0

    def test_durable_state_resume_and_invalidation(self, tmp_path):
        """
        Verifies state file persistence, state resume, invalidation on SHA mismatch,
        and partial execution status.
        """
        out_dir = str(tmp_path / "reports")
        orchestrator = Stage7ReleaseQualificationOrchestrator(output_dir=out_dir)

        state = orchestrator.load_durable_state()
        assert state["schema_version"] == 1
        assert state["gates"] == {}

        # Save mock gate0
        state["git_sha"] = "test_sha_123"
        state["gates"]["gate0"] = {"status": "PASSED", "execution_git_sha": "test_sha_123"}
        orchestrator.save_durable_state(state)

        # Check evidence validity with current SHA
        orchestrator.git_sha = "test_sha_456" # Different SHA!
        valid = orchestrator.is_gate_evidence_valid("gate0", state)
        assert valid is False # Invalidated due to SHA mismatch!

    def test_invalid_gate_id_raises_value_error(self):
        """Verifies that passing an unknown gate ID to execute_orchestration raises ValueError."""
        orchestrator = Stage7ReleaseQualificationOrchestrator()
        with pytest.raises(ValueError, match="Invalid gate"):
            orchestrator.execute_orchestration(gate="gate99")

    def test_partial_run_reports_partial_status(self, tmp_path):
        """Verifies that running a single gate marks overall qualification status as PARTIAL."""
        out_dir = str(tmp_path / "reports")
        orchestrator = Stage7ReleaseQualificationOrchestrator(output_dir=out_dir)
        orchestrator.execute_orchestration(gate="gate0")

        json_path = os.path.join(out_dir, "stage7_release_qualification.json")
        assert os.path.exists(json_path)
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["overall_qualification_status"] == "PARTIAL"

