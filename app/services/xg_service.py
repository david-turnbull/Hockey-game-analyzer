from typing import Optional, Dict, Any, Union
from app.analytics.model_registry import ModelRegistry, XGPrediction
from app.services.xg_models import HeuristicXGModel, ExpectedGoalsModel


class XGService:
    """
    Service class that acts as the entrypoint for expected goals (xG) calculations,
    delegating to the active registered predictive machine learning model.
    Maintains compatibility with legacy heuristic callers and provides full prediction provenance.
    """
    _override_model: Optional[Union[ExpectedGoalsModel, Any]] = None

    @classmethod
    def set_model(cls, model: Any) -> None:
        """Sets a custom or heuristic model override (useful for testing or fallback)."""
        cls._override_model = model

    @classmethod
    def reset_model(cls) -> None:
        """Resets model override back to active ModelRegistry model."""
        cls._override_model = None

    @classmethod
    def get_active_model_name(cls) -> str:
        """Returns the identifier/name of the current active xG model."""
        if cls._override_model is not None:
            return getattr(cls._override_model, 'name', 'custom-model')
        return ModelRegistry.get_active_name()

    @classmethod
    def get_active_model_version(cls) -> str:
        """Returns the version string of the current active xG model."""
        if cls._override_model is not None:
            return getattr(cls._override_model, 'version', getattr(cls._override_model, 'name', 'custom-model'))
        return ModelRegistry.get_active_version()

    @classmethod
    def predict_shot_xg(cls, distance: Optional[float] = None, angle: Optional[float] = None,
                        shot_type: Optional[str] = None, strength_state: Optional[str] = None,
                        empty_net: bool = False, features: Optional[Dict[str, Any]] = None, **kwargs) -> XGPrediction:
        """
        Calculates expected goals (xG) prediction and returns complete provenance (model name, version, method).
        Supports either a pre-extracted complete features dictionary or individual keyword arguments.
        """
        if features is not None:
            shot_features = dict(features)
            if distance is not None:
                shot_features['distance'] = distance
            if angle is not None:
                shot_features['angle'] = angle
            if shot_type is not None:
                shot_features['shot_type'] = shot_type
            if strength_state is not None:
                shot_features['strength_state'] = strength_state
            if empty_net:
                shot_features['empty_net'] = empty_net
            if kwargs:
                shot_features.update(kwargs)
        else:
            shot_features = {
                'distance': distance,
                'angle': angle,
                'shot_type': shot_type,
                'strength_state': strength_state,
                'empty_net': empty_net,
                **kwargs
            }

        # If an explicit override model is set (e.g. HeuristicXGModel in legacy tests), delegate to it
        if cls._override_model is not None:
            if hasattr(cls._override_model, 'predict'):
                prob = cls._override_model.predict(
                    distance=shot_features.get('distance'),
                    angle=shot_features.get('angle'),
                    shot_type=shot_features.get('shot_type'),
                    strength_state=shot_features.get('strength_state'),
                    empty_net=bool(shot_features.get('empty_net', False))
                )
                model_name = getattr(cls._override_model, 'name', 'custom-model')
                model_ver = getattr(cls._override_model, 'version', '1.0.0')
                is_heuristic = isinstance(cls._override_model, HeuristicXGModel) or 'heuristic' in model_name.lower()
                return XGPrediction(
                    xg=round(float(prob), 4),
                    model_name=model_name,
                    model_version=model_ver,
                    method="heuristic" if is_heuristic else "ml",
                    fallback_used=is_heuristic
                )

        # Delegate to ModelRegistry
        return ModelRegistry.predict_shot_xg_with_provenance(shot_features)

    @classmethod
    def calculate_shot_xg(cls, distance: Optional[float] = None, angle: Optional[float] = None,
                          shot_type: Optional[str] = None, strength_state: Optional[str] = None,
                          empty_net: bool = False, features: Optional[Dict[str, Any]] = None, **kwargs) -> float:
        """
        Calculates expected goals (xG) probability for a shot attempt.
        Supports individual keyword arguments or additional contextual features.
        Returns a float strictly bounded in [0.0, 1.0].
        """
        prediction = cls.predict_shot_xg(
            distance=distance, angle=angle, shot_type=shot_type,
            strength_state=strength_state, empty_net=empty_net,
            features=features, **kwargs
        )
        return prediction.xg

