import os
import json
import hashlib
import logging
from typing import Dict, Any, Tuple, Optional
from app.analytics.forecasting.win_probability import WinProbabilityModel, FEATURE_NAMES

logger = logging.getLogger(__name__)

class ModelUnavailableError(Exception):
    """Raised when a production forecast model artifact or manifest is missing, corrupted, or invalid."""
    pass


class ForecastModelRegistry:
    """
    Authoritative Model Registry & Fail-Closed Loader for PuckLens v1.4.
    
    Verifies:
    1. Artifact existence (.pkl file)
    2. Metadata manifest existence (.json file)
    3. SHA-256 checksum integrity matching manifest
    4. Feature schema and ordering matching runtime FEATURE_NAMES
    5. Model version compatibility
    """
    _cached_models: Dict[str, Tuple[WinProbabilityModel, Dict[str, Any]]] = {}

    @classmethod
    def get_models_dir(cls) -> str:
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        return os.path.join(project_root, "models", "forecasting")

    @classmethod
    def compute_sha256(cls, filepath: str) -> str:
        """Computes SHA-256 hash of a file on disk."""
        sha256 = hashlib.sha256()
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                sha256.update(chunk)
        return sha256.hexdigest()

    @classmethod
    def load_active_model(
        cls,
        model_version: Optional[str] = None,
        force_reload: bool = False
    ) -> Tuple[WinProbabilityModel, Dict[str, Any]]:
        """
        Loads, validates, and returns active production WinProbabilityModel and its metadata manifest.
        Fails closed with ModelUnavailableError if artifact or manifest is invalid.
        """
        if not model_version:
            # Check app configuration or default to v1.4.0
            from flask import current_app, has_app_context
            if has_app_context() and current_app.config.get("ACTIVE_FORECAST_MODEL_VERSION"):
                model_version = current_app.config.get("ACTIVE_FORECAST_MODEL_VERSION")
            else:
                model_version = "v1.4.0"

        if not force_reload and model_version in cls._cached_models:
            return cls._cached_models[model_version]

        models_dir = cls.get_models_dir()
        
        # Primary naming contract
        pkl_path = os.path.join(models_dir, f"pucklens-win-{model_version}.pkl")
        json_path = os.path.join(models_dir, f"pucklens-win-{model_version}.json")

        # Fallback check for legacy naming if primary path missing
        if not os.path.exists(pkl_path):
            alt_pkl = os.path.join(os.path.dirname(models_dir), "analytics", "forecasting", f"win_model_{model_version}.pkl")
            if os.path.exists(alt_pkl):
                pkl_path = alt_pkl

        if not os.path.exists(pkl_path):
            logger.error(f"MODEL_UNAVAILABLE: Artifact file missing at {pkl_path}")
            raise ModelUnavailableError(f"Production model artifact '{model_version}' not found at {pkl_path}.")

        if not os.path.exists(json_path):
            logger.error(f"MODEL_UNAVAILABLE: Metadata manifest missing at {json_path}")
            raise ModelUnavailableError(f"Production model metadata manifest '{model_version}' not found at {json_path}.")

        # Read manifest
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
        except Exception as e:
            logger.error(f"MODEL_UNAVAILABLE: Failed to parse manifest JSON at {json_path}: {e}")
            raise ModelUnavailableError(f"Corrupted metadata manifest at {json_path}: {e}")

        # 1. SHA-256 Verification
        actual_hash = cls.compute_sha256(pkl_path)
        expected_hash = manifest.get("artifact_sha256")
        if not expected_hash or actual_hash != expected_hash:
            logger.error(f"MODEL_UNAVAILABLE: Hash mismatch for {pkl_path}. Computed: {actual_hash}, Expected: {expected_hash}")
            raise ModelUnavailableError(f"SHA-256 hash mismatch for model artifact '{model_version}'. Computed: {actual_hash}, Manifest: {expected_hash}")

        # 2. Feature Schema & Ordering Validation
        manifest_features = manifest.get("feature_names", [])
        if manifest_features != FEATURE_NAMES:
            logger.error(f"MODEL_UNAVAILABLE: Feature schema mismatch. Manifest features: {manifest_features}, Runtime features: {FEATURE_NAMES}")
            raise ModelUnavailableError(f"Feature schema mismatch for model '{model_version}'. Manifest feature set does not match runtime FEATURE_NAMES.")

        # 3. Model Version Compatibility
        manifest_version = manifest.get("model_version")
        if manifest_version != model_version:
            logger.error(f"MODEL_UNAVAILABLE: Version mismatch. Manifest: {manifest_version}, Requested: {model_version}")
            raise ModelUnavailableError(f"Model version mismatch. Manifest version '{manifest_version}' does not match requested version '{model_version}'.")

        # 4. Scikit-Learn Runtime Version Compatibility
        import sklearn
        manifest_sklearn_ver = manifest.get("sklearn_version") or manifest.get("key_library_versions", {}).get("scikit_learn")
        if manifest_sklearn_ver:
            installed_major_minor = ".".join(sklearn.__version__.split(".")[:2])
            manifest_major_minor = ".".join(str(manifest_sklearn_ver).split(".")[:2])
            if installed_major_minor != manifest_major_minor:
                logger.error(f"MODEL_UNAVAILABLE: Incompatible scikit-learn version. Installed: {sklearn.__version__}, Manifest: {manifest_sklearn_ver}")
                raise ModelUnavailableError(f"Runtime scikit-learn version ({sklearn.__version__}) is incompatible with model manifest scikit-learn version ({manifest_sklearn_ver}).")

        # Load Model Pickle
        try:
            model_instance = WinProbabilityModel.load_model(pkl_path)
            if model_instance.model is None:
                raise ModelUnavailableError("Loaded model pickle contains unfitted classifier model.")
        except Exception as e:
            logger.error(f"MODEL_UNAVAILABLE: Failed to unpickle model from {pkl_path}: {e}")
            raise ModelUnavailableError(f"Failed to load fitted model artifact from {pkl_path}: {e}")

        cls._cached_models[model_version] = (model_instance, manifest)
        logger.info(f"Successfully loaded and verified production model artifact '{model_version}' (SHA-256: {actual_hash[:8]}...)")
        return model_instance, manifest
