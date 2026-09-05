from typing import Optional, Dict, Any, Union
from app.analytics.model_registry import ModelRegistry
from app.services.xg_models import HeuristicXGModel, ExpectedGoalsModel


class XGService:
    """
    Service class that acts as the entrypoint for expected goals (xG) calculations,
    delegating to the active registered predictive machine learning model.
    Maintains compatibility with legacy heuristic callers.
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
    def get_active_model_version(cls) -> str:
        """Returns the identifier/version of the current active xG model."""
        if cls._override_model is not None:
            return getattr(cls._override_model, 'name', 'custom-model')
        return ModelRegistry.get_active_version()

    @classmethod
    def calculate_shot_xg(cls, distance: Optional[float] = None, angle: Optional[float] = None,
                          shot_type: Optional[str] = None, strength_state: Optional[str] = None,
                          empty_net: bool = False, **kwargs) -> float:
        """
        Calculates expected goals (xG) probability for a shot attempt.
        Supports individual keyword arguments or additional contextual features.
        Returns a float strictly bounded in [0.0, 1.0].
        """
        # If an explicit override model is set (e.g. HeuristicXGModel in legacy tests), delegate to it
        if cls._override_model is not None:
            if hasattr(cls._override_model, 'predict'):
                return cls._override_model.predict(
                    distance=distance, angle=angle, shot_type=shot_type,
                    strength_state=strength_state, empty_net=empty_net
                )

        # Construct feature dictionary for ML model
        shot_features = {
            'distance': distance if distance is not None else 30.0,
            'angle': angle if angle is not None else 0.0,
            'shot_type': shot_type or 'wrist',
            'strength_state': strength_state or 'EV',
            'empty_net': empty_net,
            **kwargs
        }

        # Delegate to ModelRegistry
        xg_val = ModelRegistry.predict_shot_xg(shot_features)
        return round(float(xg_val), 4)
