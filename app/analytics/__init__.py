"""
PuckLens Predictive Analytics Module (v1.2).
Provides expected goals (xG) feature engineering, model training, evaluation, and model registry.
"""

from app.analytics.shot_features import ShotFeatureExtractor
from app.analytics.xg_model import BaseXGModel, LogisticRegressionXGModel, GradientBoostingXGModel
from app.analytics.model_registry import ModelRegistry

__all__ = [
    "ShotFeatureExtractor",
    "BaseXGModel",
    "LogisticRegressionXGModel",
    "GradientBoostingXGModel",
    "ModelRegistry"
]
