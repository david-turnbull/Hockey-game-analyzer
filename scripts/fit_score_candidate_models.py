#!/usr/bin/env python
"""
Training-only candidate score model parameter fitting script for PuckLens v1.4.

Fits candidate count model parameters strictly on training seasons:
- 20212022
- 20222023
- 20232024

Filters:
- game_type == 'R'
- data_source == 'nhl_api'
- gameState in ['OFF', 'FINAL', 'OVER']

Outputs frozen parameter artifact:
- models/forecasting/score_candidate_params_v1.4.0.json
"""

import sys
import os
import math
import json
import datetime
import subprocess
import logging
import numpy as np
from pathlib import Path
from scipy.optimize import minimize

root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from app import create_app
from app.models import db, Game, Event
from app.services.pregame_feature_service import PregameFeatureService
from app.analytics.forecasting.score_projection import PoissonScoreModel

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

TRAIN_SEASONS = ["20212022", "20222023", "20232024"]

def get_git_sha() -> str:
    try:
        output = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root_dir).decode("utf-8").strip()
        return output
    except Exception as e:
        logger.warning(f"Could not retrieve git SHA: {e}")
        return "unknown"

def extract_reg_ot_goals(game: Game) -> tuple[int, int]:
    has_so = db.session.query(Event.event_id).filter(
        Event.game_id == game.game_id,
        Event.period_type == 'SO'
    ).first() is not None

    if has_so:
        if game.home_score > game.away_score:
            return game.home_score - 1, game.away_score
        elif game.away_score > game.home_score:
            return game.home_score, game.away_score - 1
        else:
            return game.home_score, game.away_score
    return game.home_score, game.away_score

def fit_candidate_parameters():
    app = create_app("development")
    with app.app_context():
        logger.info("Preloading stats for pregame feature service...")
        PregameFeatureService.preload_all_stats()

        logger.info(f"Querying training games for seasons {TRAIN_SEASONS}...")
        games = Game.query.filter(
            Game.season.in_(TRAIN_SEASONS),
            Game.game_type == 'R',
            Game.data_source == 'nhl_api',
            Game.nhl_game_state.in_(['OFF', 'FINAL', 'OVER'])
        ).order_by(Game.game_date, Game.game_id).all()

        sample_count = len(games)
        logger.info(f"Loaded {sample_count} training games.")
        assert sample_count > 0, "No training games found matching filters!"

        actual_h = []
        actual_a = []
        pred_h = []
        pred_a = []

        for g in games:
            feats = PregameFeatureService.get_pregame_features(g)
            lh, la = PoissonScoreModel.calculate_expected_goals(feats)
            rh, ra = extract_reg_ot_goals(g)

            actual_h.append(rh)
            actual_a.append(ra)
            pred_h.append(lh)
            pred_a.append(la)

        ah = np.array(actual_h)
        aa = np.array(actual_a)
        ph = np.array(pred_h)
        pa = np.array(pred_a)

        # 1. Negative Binomial alpha (overdispersion ratio (Var - Mean) / Mean^2)
        disp_h = (np.var(ah) - np.mean(ah)) / (np.mean(ah) ** 2)
        disp_a = (np.var(aa) - np.mean(aa)) / (np.mean(aa) ** 2)
        alpha_raw = float((disp_h + disp_a) / 2.0)
        # Hockey goal counts exhibit slight under-dispersion (Var < Mean), so alpha is floored at 0.001
        alpha_est = max(0.001, round(alpha_raw, 4))
        logger.info(f"Estimated Negative Binomial alpha: {alpha_est} (raw: {alpha_raw:.4f})")

        # 2. Bivariate Poisson lambda3 (residual goal covariance Cov(e_h, e_a))
        cov_res = float(np.cov(ah - ph, aa - pa)[0, 1])
        lambda3_est = max(0.001, round(cov_res, 4))
        logger.info(f"Estimated Bivariate Poisson lambda3: {lambda3_est} (raw covariance: {cov_res:.4f})")

        # 3. Dixon-Coles gamma (minimizing NLL on low-score tie adjustments)
        def dc_nll(gamma_val):
            g_val = gamma_val[0]
            nll = 0.0
            for h_act, a_act, lh, la in zip(ah, aa, ph, pa):
                tau = PoissonScoreModel.dixon_coles_adj(int(h_act), int(a_act), lh, la, gamma=g_val)
                p_cell = tau * PoissonScoreModel.poisson_pmf(int(h_act), lh) * PoissonScoreModel.poisson_pmf(int(a_act), la)
                nll -= math.log(max(1e-15, p_cell))
            return nll

        res = minimize(dc_nll, [0.0], bounds=[(-0.1, 0.1)])
        gamma_est = round(float(res.x[0]), 4)
        logger.info(f"Estimated Dixon-Coles gamma: {gamma_est}")

        artifact = {
            "model_version": "v1.4.0",
            "artifact_type": "score_candidate_frozen_parameters",
            "git_sha": get_git_sha(),
            "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "training_seasons": TRAIN_SEASONS,
            "sample_count": sample_count,
            "filters": {
                "game_type": "R",
                "data_source": "nhl_api",
                "game_state": ["OFF", "FINAL", "OVER"]
            },
            "fitting_methodology": {
                "poisson": "Baseline expected goals (lh, la) from PregameFeatureService",
                "neg_binomial": "Method of moments over-dispersion ratio alpha = max(0.001, (Var - Mean) / Mean^2)",
                "bivariate_poisson": "Residual goal covariance lambda3 = max(0.001, Cov(e_h, e_a))",
                "dixon_coles": "Maximum likelihood estimation minimizing NLL for low-score tie multiplier tau(h, a; gamma)"
            },
            "candidate_parameters": {
                "poisson": {},
                "neg_binomial": {"alpha": alpha_est},
                "bivariate_poisson": {"lambda3": lambda3_est},
                "dixon_coles": {"gamma": gamma_est}
            }
        }

        output_dir = Path(root_dir) / "models" / "forecasting"
        output_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = output_dir / "score_candidate_params_v1.4.0.json"

        with open(artifact_path, "w") as f:
            json.dump(artifact, f, indent=2)

        logger.info(f"Successfully saved frozen parameter artifact to {artifact_path}")

if __name__ == "__main__":
    fit_candidate_parameters()
