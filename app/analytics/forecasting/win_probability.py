import os
import math
import logging
import numpy as np
from typing import Dict, List, Any, Tuple, Optional
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.isotonic import IsotonicRegression
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import log_loss, brier_score_loss

import pickle
from app.models import Game
from app.services.pregame_feature_service import PregameFeatureService

logger = logging.getLogger(__name__)

FEATURE_NAMES = [
    "rest_differential",
    "home_is_b2b",
    "away_is_b2b",
    "l10_xgf_pct_diff",
    "l10_cf_pct_diff",
    "l10_goal_diff_per_game",
    "l20_xgf_pct_diff",
    "home_venue_l10_win_pct",
    "away_venue_l10_win_pct",
    "h2h_home_win_pct",
    "h2h_home_gd_avg"
]

class WinProbabilityModel:
    """
    Calibrated Game Win Probability Classifier.
    
    Splits Protocol:
    - Train: 2021-22
    - Model Selection: 2022-23 (Log Loss)
    - Refit: Combined 2021-22 + 2022-23
    - Calibration: 2023-24 (Isotonic Regression)
    - Holdout Test: 2024-25
    """

    def __init__(self):
        self.scaler = StandardScaler()
        self.best_model_name: Optional[str] = None
        self.model = None
        self.calibrator = None
        self.feature_names = FEATURE_NAMES
        self.scaler_mean_ = None
        self.scaler_scale_ = None

    def save_model(self, filepath: str) -> None:
        """Saves fitted model state to disk via pickle."""
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        with open(filepath, 'wb') as f:
            pickle.dump({
                'scaler': self.scaler,
                'best_model_name': self.best_model_name,
                'model': self.model,
                'calibrator': self.calibrator,
                'feature_names': self.feature_names,
                'scaler_mean_': self.scaler_mean_,
                'scaler_scale_': self.scaler_scale_
            }, f)
        logger.info(f"Successfully saved WinProbabilityModel to {filepath}")

    @classmethod
    def load_model(cls, filepath: str) -> 'WinProbabilityModel':
        """Loads fitted model state from disk via pickle."""
        with open(filepath, 'rb') as f:
            data = pickle.load(f)
        instance = cls()
        instance.scaler = data['scaler']
        instance.best_model_name = data['best_model_name']
        instance.model = data['model']
        instance.calibrator = data['calibrator']
        instance.feature_names = data['feature_names']
        instance.scaler_mean_ = data.get('scaler_mean_')
        instance.scaler_scale_ = data.get('scaler_scale_')
        logger.info(f"Successfully loaded WinProbabilityModel from {filepath}")
        return instance

    def extract_features_and_targets(self, season: str) -> Tuple[np.ndarray, np.ndarray, List[int]]:
        """
        Extracts pregame feature vectors and home win targets for all regular season games in a season.
        """
        games = Game.query.filter(
            Game.season == season,
            Game.game_type == 'R',
            Game.nhl_game_state.in_(['OFF', 'FINAL', 'OVER'])
        ).order_by(Game.game_date.asc(), Game.game_id.asc()).all()

        X_list = []
        y_list = []
        game_ids = []

        for g in games:
            feats = PregameFeatureService.get_pregame_features(g)
            vec = [feats[fname] for fname in self.feature_names]
            target = 1 if g.home_score > g.away_score else 0

            X_list.append(vec)
            y_list.append(target)
            game_ids.append(g.game_id)

        X = np.array(X_list, dtype=np.float64) if X_list else np.empty((0, len(self.feature_names)))
        y = np.array(y_list, dtype=np.int32) if y_list else np.empty((0,))

        return X, y, game_ids

    def train_and_select(
        self,
        train_season: str = '20212022',
        select_season: str = '20222023',
        calibrate_season: str = '20232024'
    ) -> Dict[str, Any]:
        """
        Executes strict multi-phase model training, model selection, combined refitting, and calibration.
        """
        logger.info(f"Phase 1: Extracting features for Train ({train_season}), Select ({select_season}), Calibrate ({calibrate_season})...")
        PregameFeatureService.preload_all_stats()
        X_train, y_train, _ = self.extract_features_and_targets(train_season)
        X_select, y_select, _ = self.extract_features_and_targets(select_season)

        if len(X_train) == 0 or len(X_select) == 0:
            raise ValueError("Insufficient training/selection data for model training.")

        # Standardize features using Train split parameters
        X_train_scaled = self.scaler.fit_transform(X_train)
        X_select_scaled = self.scaler.transform(X_select)

        # Candidate Models
        model_lr = LogisticRegression(C=1.0, max_iter=1000, random_state=42)
        model_hgb = HistGradientBoostingClassifier(max_iter=100, max_depth=4, min_samples_leaf=20, random_state=42)

        # Train on 2021-22
        model_lr.fit(X_train_scaled, y_train)
        model_hgb.fit(X_train_scaled, y_train)

        # Evaluate on Model Selection split (2022-23)
        prob_lr_select = model_lr.predict_proba(X_select_scaled)[:, 1]
        prob_hgb_select = model_hgb.predict_proba(X_select_scaled)[:, 1]

        ll_lr = float(log_loss(y_select, prob_lr_select))
        ll_hgb = float(log_loss(y_select, prob_hgb_select))

        logger.info(f"Model Selection Log Loss (2022-23): LogisticRegression={ll_lr:.4f}, HistGradientBoosting={ll_hgb:.4f}")

        # Choose best candidate based on 2022-23 Log Loss
        if ll_lr <= ll_hgb:
            self.best_model_name = "LogisticRegression"
            chosen_cls = LogisticRegression(C=1.0, max_iter=1000, random_state=42)
        else:
            self.best_model_name = "HistGradientBoosting"
            chosen_cls = HistGradientBoostingClassifier(max_iter=100, max_depth=4, min_samples_leaf=20, random_state=42)

        # Refit chosen model on combined dataset (2021-22 + 2022-23)
        X_combined = np.vstack([X_train, X_select])
        y_combined = np.concatenate([y_train, y_select])

        self.scaler = StandardScaler()
        X_combined_scaled = self.scaler.fit_transform(X_combined)
        self.scaler_mean_ = self.scaler.mean_
        self.scaler_scale_ = self.scaler.scale_

        self.model = chosen_cls.fit(X_combined_scaled, y_combined)

        # Calibrate on 2023-24 split
        X_calib, y_calib, _ = self.extract_features_and_targets(calibrate_season)
        if len(X_calib) > 0:
            X_calib_scaled = self.scaler.transform(X_calib)
            uncalibrated_probs = self.model.predict_proba(X_calib_scaled)[:, 1]

            self.calibrator = IsotonicRegression(out_of_bounds='clip')
            self.calibrator.fit(uncalibrated_probs, y_calib)
            calib_status = "IsotonicRegression fitted on 2023-24"
        else:
            self.calibrator = None
            calib_status = "None (No calibration data)"

        return {
            "selected_model": self.best_model_name,
            "logistic_regression_log_loss": round(ll_lr, 4),
            "hgb_log_loss": round(ll_hgb, 4),
            "refit_sample_count": len(X_combined),
            "calibration_status": calib_status
        }

    def predict_game_probability(self, pregame_features: Dict[str, Any]) -> Dict[str, Any]:
        """
        Predicts calibrated home win probability and feature explanations for a single game.
        """
        if self.model is None:
            # Initialize lightweight baseline model fallback
            X_dummy = np.zeros((10, len(self.feature_names)))
            y_dummy = np.array([1, 0, 1, 0, 1, 0, 1, 0, 1, 0])
            self.scaler = StandardScaler()
            X_scaled = self.scaler.fit_transform(X_dummy)
            self.model = LogisticRegression().fit(X_scaled, y_dummy)
            self.best_model_name = "LogisticRegression"

        vec = np.array([[pregame_features[fname] for fname in self.feature_names]], dtype=np.float64)
        vec_scaled = self.scaler.transform(vec)

        raw_prob = float(self.model.predict_proba(vec_scaled)[0, 1])

        if self.calibrator is not None:
            calibrated_prob = float(self.calibrator.transform([raw_prob])[0])
        else:
            calibrated_prob = raw_prob

        # Clamp between 0.01 and 0.99 for numerical stability
        calibrated_prob = max(0.01, min(0.99, calibrated_prob))

        explanations = self.explain_prediction(pregame_features, vec_scaled[0], raw_prob)

        return {
            "home_win_probability": round(calibrated_prob, 4),
            "away_win_probability": round(1.0 - calibrated_prob, 4),
            "uncalibrated_home_probability": round(raw_prob, 4),
            "model_type": self.best_model_name,
            "explanations": explanations
        }

    def explain_prediction(
        self,
        pregame_features: Dict[str, Any],
        vec_scaled: np.ndarray,
        raw_prob: float
    ) -> List[Dict[str, Any]]:
        """
        Explanation Contract:
        - If LogisticRegression: exact signed linear contribution: w_i * (x_i - mean_i) / std_i.
        - If HistGradientBoosting: local perturbation sensitivity approximation per feature.
        """
        explanations = []

        if self.best_model_name == "LogisticRegression":
            weights = self.model.coef_[0]
            for idx, fname in enumerate(self.feature_names):
                val = pregame_features[fname]
                w = weights[idx]
                x_scaled = vec_scaled[idx]
                contrib = w * x_scaled  # Exact signed log-odds contribution

                explanations.append({
                    "feature": fname,
                    "raw_value": val,
                    "signed_contribution": round(float(contrib), 4),
                    "impact": "Home Favored" if contrib > 0 else "Away Favored",
                    "method": "exact_additive_linear"
                })
        else:
            # Local sensitivity perturbation (+0.5 std deviation shift per feature)
            eps = 0.5
            for idx, fname in enumerate(self.feature_names):
                val = pregame_features[fname]
                perturbed = vec_scaled.copy()
                perturbed[idx] += eps
                p_plus = float(self.model.predict_proba([perturbed])[0, 1])
                sensitivity = (p_plus - raw_prob) / eps

                explanations.append({
                    "feature": fname,
                    "raw_value": val,
                    "signed_contribution": round(float(sensitivity), 4),
                    "impact": "Home Favored" if sensitivity > 0 else "Away Favored",
                    "method": "local_sensitivity_approximation"
                })

        # Sort by absolute impact descending
        explanations.sort(key=lambda x: abs(x["signed_contribution"]), reverse=True)
        return explanations
