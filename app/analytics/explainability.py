import logging
from typing import Dict, List, Any, Optional
import numpy as np
import pandas as pd
from app.analytics.model_registry import ModelRegistry
from app.analytics.xg_model import LogisticRegressionXGModel, BaseXGModel
from app.analytics.shot_features import ShotFeatureExtractor, NUMERIC_FEATURES, CATEGORICAL_FEATURES
from app.models import db, Shot, Event, Game

logger = logging.getLogger(__name__)

class XGExplainer:
    """
    Transparent contribution explainer for Logistic Regression Expected Goals models.
    Deconstructs linear feature contributions to the logit:
    logit = intercept + sum(beta_i * x_i)
    p = 1 / (1 + exp(-logit))
    """

    @classmethod
    def explain_shot(
        cls,
        shot_features: Dict[str, Any],
        model: Optional[BaseXGModel] = None
    ) -> Dict[str, Any]:
        """
        Calculates individual feature contributions and human-interpretable contextual factors
        for a single shot attempt.
        """
        if model is None:
            model = ModelRegistry.get_active_model()

        if not hasattr(model, 'pipeline') or model.pipeline is None:
            raise ValueError("Active model does not expose a pipeline representation for explanation.")

        pipeline = model.pipeline
        preprocessor = pipeline.named_steps.get('preprocessor')
        classifier = pipeline.named_steps.get('classifier')

        if not preprocessor or not classifier or not hasattr(classifier, 'coef_'):
            raise ValueError("Model pipeline must contain a linear classifier with exposed coefficients.")

        # 1. Format input DataFrame and run through preprocessor
        df = model._ensure_dataframe(shot_features)
        X_trans = preprocessor.transform(df)
        if hasattr(X_trans, 'toarray'):
            X_trans = X_trans.toarray()
        vec = X_trans[0]

        feature_names = preprocessor.get_feature_names_out()
        coefs = classifier.coef_[0]
        intercept = float(classifier.intercept_[0])

        raw_dict = df.iloc[0].to_dict()

        # 2. Compute individual feature contributions: c_k = w_k * v_k
        contributions = vec * coefs
        total_logit = intercept + float(np.sum(contributions))
        predicted_xg = round(float(1.0 / (1.0 + np.exp(-total_logit))), 4)

        # 3. Group contributions into meaningful hockey factors
        factor_map = {}
        for idx, col_name in enumerate(feature_names):
            contrib = float(contributions[idx])
            val = float(vec[idx])

            # Strip sklearn prefix (e.g. 'num__distance' -> 'distance', 'cat__shot_type_wrist' -> 'shot_type')
            if col_name.startswith('num__'):
                clean_name = col_name[5:]
                group_key = clean_name
            elif col_name.startswith('cat__'):
                parts = col_name[5:].split('_', 1)
                group_key = parts[0]
            else:
                group_key = col_name

            if group_key not in factor_map:
                factor_map[group_key] = 0.0
            factor_map[group_key] += contrib

        # 4. Generate readable descriptions
        factors_list = []
        for feat_name, contrib in factor_map.items():
            if abs(contrib) < 0.001:
                continue

            desc = cls._format_factor_description(feat_name, contrib, raw_dict)
            factors_list.append({
                "factor": feat_name,
                "contribution": round(contrib, 4),
                "impact": "danger_increase" if contrib > 0 else "danger_decrease",
                "description": desc
            })

        # Sort: factors increasing danger descending, factors reducing danger ascending (most negative first)
        increasing = [f for f in factors_list if f["contribution"] > 0]
        increasing.sort(key=lambda x: -x["contribution"])

        reducing = [f for f in factors_list if f["contribution"] < 0]
        reducing.sort(key=lambda x: x["contribution"])

        return {
            "xg": predicted_xg,
            "model_name": getattr(model, 'name', ModelRegistry.get_active_name()),
            "model_version": getattr(model, 'version', ModelRegistry.get_active_version()),
            "intercept": round(intercept, 4),
            "reconstructed_logit": round(total_logit, 4),
            "factors_increasing_danger": increasing,
            "factors_reducing_danger": reducing,
            "all_factors": increasing + reducing
        }

    @classmethod
    def explain_shot_by_id(cls, shot_id: str) -> Optional[Dict[str, Any]]:
        """
        Loads shot and event from DB and derives complete xG factor explanations.
        """
        shot = db.session.get(Shot, shot_id)
        if not shot:
            return None

        event = shot.event or db.session.get(Event, shot_id)
        if not event:
            return None

        gid = shot.game_id or (event.game_id if event else None)
        game = db.session.get(Game, gid) if gid else None
        is_home = (shot.team_id == game.home_team_id) if game else False

        features = {
            "distance": shot.distance if shot.distance is not None else 30.0,
            "angle": shot.angle if shot.angle is not None else 0.0,
            "period": event.period if event else 1,
            "period_seconds": (
                (event.elapsed_game_seconds % 1200)
                if (event and event.elapsed_game_seconds is not None)
                else 0
            ),
            "score_differential": 0,
            "is_home": 1 if is_home else 0,
            "empty_net": 1 if shot.empty_net else 0,
            "time_since_prev_event": 3.0,
            "distance_from_prev_event": 10.0,
            "angle_change": 0.0,
            "is_rebound": 0,
            "is_rush": 0,
            "is_turnover": 0,
            "is_after_faceoff": 0,
            "is_lateral_movement": 0,
            "is_power_play": 1 if shot.strength_state == 'PP' else 0,
            "is_shorthanded": 1 if shot.strength_state == 'SH' else 0,
            "coordinates_missing": 0 if (shot.x_coordinate_normalized is not None) else 1,
            "shot_type": shot.shot_type.lower() if shot.shot_type else 'wrist',
            "strength_state": shot.strength_state or 'EV',
            "prev_event_type": 'faceoff'
        }

        explanation = cls.explain_shot(features)
        explanation["shot_id"] = shot_id
        if shot.xg is not None:
            explanation["recorded_db_xg"] = round(shot.xg, 4)
        return explanation

    @staticmethod
    def _format_factor_description(feat_name: str, contrib: float, raw: Dict[str, Any]) -> str:
        """
        Creates clear, non-causal contextual descriptions of factor contributions.
        """
        sign = "+" if contrib > 0 else "-"
        if feat_name == "distance":
            dist = raw.get("distance", 30.0)
            if contrib > 0:
                return f"{sign} shot from {dist:.0f} ft (in-close shooting distance)"
            else:
                return f"{sign} shot from {dist:.0f} ft (perimeter shooting distance)"

        elif feat_name == "angle":
            ang = raw.get("angle", 0.0)
            if contrib > 0:
                return f"{sign} centered shooting angle ({ang:.0f}° from net center)"
            else:
                return f"{sign} wide shooting angle ({ang:.0f}° from net center)"

        elif feat_name == "is_rebound":
            t = raw.get("time_since_prev_event")
            t_str = f" within {t:.1f}s" if t else ""
            return f"{sign} rebound attempt{t_str}"

        elif feat_name == "is_lateral_movement":
            return f"{sign} lateral puck movement before release"

        elif feat_name == "is_rush":
            return f"{sign} shot off odd-man or rapid rush transition"

        elif feat_name == "is_turnover":
            return f"{sign} shot following defensive turnover"

        elif feat_name == "is_after_faceoff":
            return f"{sign} quick shot directly off faceoff win"

        elif feat_name == "empty_net":
            return f"{sign} empty net (uncontested goal attempt)"

        elif feat_name == "shot_type":
            st = str(raw.get("shot_type", "wrist")).title()
            return f"{sign} {st} shot attempt"

        elif feat_name == "strength_state":
            st = raw.get("strength_state", "EV")
            return f"{sign} {st} strength state"

        elif feat_name == "is_power_play":
            return f"{sign} power play manpower advantage"

        elif feat_name == "is_shorthanded":
            return f"{sign} shorthanded situation"

        elif feat_name == "score_differential":
            sd = raw.get("score_differential", 0)
            return f"{sign} game state ({sd:+d} goal differential)"

        else:
            clean = feat_name.replace('_', ' ').title()
            return f"{sign} {clean} context"
