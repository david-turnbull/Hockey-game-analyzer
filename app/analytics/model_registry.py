import os
import json
import logging
from dataclasses import dataclass
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
DEFAULT_MODEL_NAME = "pucklens-xg-logistic"
DEFAULT_MODEL_VERSION = "1.0.0"
DEFAULT_HEURISTIC_NAME = "pucklens-xg-heuristic"
DEFAULT_HEURISTIC_VERSION = "1.0.0"


@dataclass(frozen=True)
class XGPrediction:
    """Represents an expected goal prediction along with complete model provenance."""
    xg: float
    model_name: str
    model_version: str
    method: str  # 'ml' or 'heuristic'
    fallback_used: bool


class ModelRegistry:
    """
    Registry for managing, persisting, loading, and serving Expected Goals models.
    Supports versioning, metadata retrieval, safe fallbacks, and provenance tracking.
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
        meta_dict = model.metadata if hasattr(model, 'metadata') else {}
        with open(metadata_path, 'w', encoding='utf-8') as f:
            json.dump(meta_dict, f, indent=2)

        logger.info(f"Model saved to {model_path}, metadata to {metadata_path}")
        # Only update active cached model if saving to default production directory
        if directory is None or os.path.abspath(directory) == os.path.abspath(cls.get_model_directory()):
            cls._active_model = model
            cls._active_metadata = meta_dict
        return model_path

    @classmethod
    def load_model(cls, directory: Optional[str] = None, filename: str = "xg_v1.pkl") -> Optional[BaseXGModel]:
        """Loads model from disk, caching it in memory if using default model directory."""
        target_dir = directory or cls.get_model_directory()
        model_path = os.path.join(target_dir, filename)
        metadata_path = os.path.join(target_dir, "metadata.json")

        if not os.path.exists(model_path):
            logger.warning(f"Trained model artifact not found at {model_path}. Using baseline fallback.")
            return None

        try:
            model = joblib.load(model_path)
            meta_dict = {}
            if os.path.exists(metadata_path):
                with open(metadata_path, 'r', encoding='utf-8') as f:
                    meta_dict = json.load(f)
            else:
                meta_dict = model.metadata if hasattr(model, 'metadata') else {}
            
            if hasattr(model, '_metadata'):
                model._metadata = meta_dict

            is_default_dir = (directory is None or os.path.abspath(directory) == os.path.abspath(cls.get_model_directory()))
            if is_default_dir:
                cls._active_model = model
                cls._active_metadata = meta_dict

            # Task 7: Check runtime library version compatibility
            if meta_dict:
                saved_sklearn = meta_dict.get('scikit_learn_version')
                if saved_sklearn:
                    import sklearn
                    current_major = sklearn.__version__.split('.')[0]
                    saved_major = str(saved_sklearn).split('.')[0]
                    if current_major != saved_major:
                        logger.warning(
                            f"Model artifact was trained with scikit-learn {saved_sklearn}, "
                            f"current runtime is {sklearn.__version__}. Major version mismatch may cause deserialization issues."
                        )

            logger.info(f"Successfully loaded model {meta_dict.get('name', 'xg_model')} from {model_path}")
            return model
        except Exception as e:
            logger.error(f"Failed to load model from {model_path}: {e}")
            return None

    @classmethod
    def reset_active_model(cls) -> None:
        """Resets cached active model and metadata in memory."""
        cls._active_model = None
        cls._active_metadata = None

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
    def get_active_name(cls) -> str:
        """Returns the active model name string."""
        if cls._active_metadata and 'name' in cls._active_metadata:
            return cls._active_metadata.get('name', DEFAULT_MODEL_NAME)
        if cls._active_metadata and 'model_name' in cls._active_metadata:
            return cls._active_metadata.get('model_name', DEFAULT_MODEL_NAME)
        model = cls.get_active_model()
        return getattr(model, 'name', DEFAULT_MODEL_NAME)

    @classmethod
    def get_active_version(cls) -> str:
        """Returns the active model version string."""
        if cls._active_metadata and 'version' in cls._active_metadata:
            return cls._active_metadata.get('version', DEFAULT_MODEL_VERSION)
        if cls._active_metadata and 'model_version' in cls._active_metadata:
            return cls._active_metadata.get('model_version', DEFAULT_MODEL_VERSION)
        model = cls.get_active_model()
        return getattr(model, 'version', DEFAULT_MODEL_VERSION)

    @classmethod
    def predict_shot_xg_with_provenance(cls, shot_features: Dict[str, Any]) -> XGPrediction:
        """
        Calculates expected goals with complete prediction provenance.
        Falls back to HeuristicXGModel if an ML model is not available or encounters an inference error.
        """
        model = cls.get_active_model()
        if isinstance(model, BaseXGModel):
            try:
                prob = float(model.predict(shot_features))
                return XGPrediction(
                    xg=round(prob, 4),
                    model_name=getattr(model, 'name', cls.get_active_name()),
                    model_version=getattr(model, 'version', cls.get_active_version()),
                    method="ml",
                    fallback_used=False
                )
            except Exception as e:
                logger.warning(f"Error predicting xG with ML model: {e}. Using heuristic fallback.")

        # Fallback to heuristic calculation
        dist = shot_features.get('distance')
        if dist is None or not isinstance(dist, (int, float)):
            dist = 45.0
        ang = shot_features.get('angle')
        if ang is None or not isinstance(ang, (int, float)):
            ang = 0.0

        heuristic_prob = cls._fallback_model.predict(
            distance=float(dist),
            angle=float(ang),
            shot_type=shot_features.get('shot_type'),
            strength_state=shot_features.get('strength_state'),
            empty_net=bool(shot_features.get('empty_net', False))
        )
        return XGPrediction(
            xg=round(float(heuristic_prob), 4),
            model_name=DEFAULT_HEURISTIC_NAME,
            model_version=DEFAULT_HEURISTIC_VERSION,
            method="heuristic",
            fallback_used=True
        )

    @classmethod
    def predict_shot_xg(cls, shot_features: Dict[str, Any]) -> float:
        """
        Maintains backward compatibility returning a float.
        """
        return cls.predict_shot_xg_with_provenance(shot_features).xg
