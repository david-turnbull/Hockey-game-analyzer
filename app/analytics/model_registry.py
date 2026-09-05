import os
import json
import logging
from typing import Optional, Dict, Any, Union
import joblib
import pandas as pd

from app.analytics.xg_model import BaseXGModel
from app.services.xg_models import HeuristicXGModel

logger = logging.getLogger(__name__)

DEFAULT_MODEL_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'models', 'xg'
)
DEFAULT_MODEL_VERSION = "pucklens-xg-v1"


class ModelRegistry:
    """
    Registry for managing, persisting, loading, and serving Expected Goals models.
    Supports versioning, metadata retrieval, and safe fallbacks.
    """

    _active_model: Optional[BaseXGModel] = None
    _active_metadata: Optional[Dict[str, Any]] = None
    _fallback_model: HeuristicXGModel = HeuristicXGModel()

    @classmethod
    def get_model_directory(cls) -> str:
        return DEFAULT_MODEL_DIR

    @classmethod
    def save_model(cls, model: BaseXGModel, directory: Optional[str] = None, filename: str = "xg_v1.pkl") -> str:
        """Saves trained model pipeline and metadata to disk."""
        target_dir = directory or cls.get_model_directory()
        os.makedirs(target_dir, exist_ok=True)

        model_path = os.path.join(target_dir, filename)
        joblib.dump(model, model_path)

        metadata_path = os.path.join(target_dir, "metadata.json")
        with open(metadata_path, 'w', encoding='utf-8') as f:
            json.dump(model.metadata, f, indent=2)

        logger.info(f"Model saved to {model_path}, metadata to {metadata_path}")
        # Update cached active model
        cls._active_model = model
        cls._active_metadata = model.metadata
        return model_path

    @classmethod
    def load_model(cls, directory: Optional[str] = None, filename: str = "xg_v1.pkl") -> Optional[BaseXGModel]:
        """Loads model from disk, caching it in memory."""
        target_dir = directory or cls.get_model_directory()
        model_path = os.path.join(target_dir, filename)
        metadata_path = os.path.join(target_dir, "metadata.json")

        if not os.path.exists(model_path):
            logger.warning(f"Trained model artifact not found at {model_path}. Using baseline fallback.")
            return None

        try:
            model = joblib.load(model_path)
            cls._active_model = model
            if os.path.exists(metadata_path):
                with open(metadata_path, 'r', encoding='utf-8') as f:
                    cls._active_metadata = json.load(f)
            else:
                cls._active_metadata = model.metadata if hasattr(model, 'metadata') else {}
            logger.info(f"Successfully loaded model {cls._active_metadata.get('name', 'xg_model')} from {model_path}")
            return model
        except Exception as e:
            logger.error(f"Failed to load model from {model_path}: {e}")
            return None

    @classmethod
    def get_active_model(cls) -> Union[BaseXGModel, HeuristicXGModel]:
        """Returns the active model, loading from disk if needed, or falling back safely."""
        if cls._active_model is not None:
            return cls._active_model

        loaded = cls.load_model()
        if loaded is not None:
            return loaded

        return cls._fallback_model

    @classmethod
    def get_active_version(cls) -> str:
        """Returns the active model version string."""
        if cls._active_metadata and 'version' in cls._active_metadata:
            return cls._active_metadata.get('name', DEFAULT_MODEL_VERSION)
        return DEFAULT_MODEL_VERSION

    @classmethod
    def predict_shot_xg(cls, shot_features: Dict[str, Any]) -> float:
        """
        Calculates expected goals for a shot dictionary using active model.
        Falls back to HeuristicXGModel if an ML model is not available.
        """
        model = cls.get_active_model()
        if isinstance(model, BaseXGModel):
            try:
                return float(model.predict(shot_features))
            except Exception as e:
                logger.warning(f"Error predicting xG with ML model: {e}. Using heuristic fallback.")

        # Fallback to heuristic calculation
        return cls._fallback_model.predict(
            distance=shot_features.get('distance', 30.0),
            angle=shot_features.get('angle', 0.0),
            shot_type=shot_features.get('shot_type'),
            strength_state=shot_features.get('strength_state'),
            empty_net=bool(shot_features.get('empty_net', False))
        )
