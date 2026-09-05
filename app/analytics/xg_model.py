import abc
from datetime import datetime, timezone
from typing import Dict, List, Any, Union, Optional
import numpy as np
import pandas as pd
from sklearn.pipeline import Pipeline
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import StandardScaler, OneHotEncoder
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import HistGradientBoostingClassifier

from app.analytics.shot_features import NUMERIC_FEATURES, CATEGORICAL_FEATURES, ShotFeatureExtractor


class BaseXGModel(abc.ABC):
    """
    Abstract Base Class for Expected Goals models.
    Defines common interface: predict(), predict_proba(), metadata, and exportable properties.
    Prepared for future Model Lab extensibility (Milestone 20).
    """

    def __init__(self, name: str, version: str):
        self.name = name
        self.version = version
        self.pipeline: Optional[Pipeline] = None
        self.features: List[str] = NUMERIC_FEATURES + CATEGORICAL_FEATURES
        self.metrics: Dict[str, Any] = {}
        self.training_date: Optional[str] = None
        self.is_fitted = False

    @abc.abstractmethod
    def fit(self, X: pd.DataFrame, y: np.ndarray) -> 'BaseXGModel':
        """Fit the model pipeline on training data."""
        pass

    def predict_proba(self, X: Union[pd.DataFrame, Dict[str, Any], List[Dict[str, Any]]]) -> np.ndarray:
        """
        Predict continuous expected goals probability [0.0, 1.0].
        Accepts DataFrame, single dictionary, or list of dictionaries.
        """
        if not self.is_fitted or self.pipeline is None:
            raise ValueError(f"Model {self.name} ({self.version}) is not fitted.")

        df = self._ensure_dataframe(X)
        probs = self.pipeline.predict_proba(df)[:, 1]
        # Guarantee mathematical bounds [0.0, 1.0]
        return np.clip(probs, 0.0, 1.0)

    def predict(self, X: Union[pd.DataFrame, Dict[str, Any], List[Dict[str, Any]]]) -> Union[float, np.ndarray]:
        """
        Calculates expected goals for input features.
        If a single shot dictionary is passed, returns a single float.
        """
        probs = self.predict_proba(X)
        if isinstance(X, dict):
            return round(float(probs[0]), 4)
        return probs

    def _ensure_dataframe(self, X: Union[pd.DataFrame, Dict[str, Any], List[Dict[str, Any]]]) -> pd.DataFrame:
        """Converts raw inputs to formatted DataFrame containing all required feature columns."""
        if isinstance(X, pd.DataFrame):
            df = X
        elif isinstance(X, dict):
            standardized = ShotFeatureExtractor.extract_features_from_dict(X)
            df = pd.DataFrame([standardized])
        elif isinstance(X, list):
            standardized = [ShotFeatureExtractor.extract_features_from_dict(r) for r in X]
            df = pd.DataFrame(standardized)
        else:
            raise TypeError(f"Unsupported feature input type: {type(X)}")

        # Ensure all columns exist
        for col in self.features:
            if col not in df.columns:
                df[col] = 0 if col in NUMERIC_FEATURES else 'other'

        return df[self.features]

    @property
    def metadata(self) -> Dict[str, Any]:
        """Returns standard metadata for model registry and tracking."""
        return {
            'name': self.name,
            'version': self.version,
            'training_date': self.training_date,
            'features': self.features,
            'metrics': self.metrics,
            'model_type': self.__class__.__name__
        }


class LogisticRegressionXGModel(BaseXGModel):
    """
    Baseline interpretable Expected Goals model using Logistic Regression.
    Features are scaled with StandardScaler and categorical features one-hot encoded.
    """

    def __init__(self, name: str = "pucklens-xg-logistic", version: str = "1.0.0", C: float = 1.0):
        super().__init__(name, version)
        self.C = C
        self._build_pipeline()

    def _build_pipeline(self):
        preprocessor = ColumnTransformer(
            transformers=[
                ('num', StandardScaler(), NUMERIC_FEATURES),
                ('cat', OneHotEncoder(handle_unknown='ignore', sparse_output=False), CATEGORICAL_FEATURES)
            ]
        )
        self.pipeline = Pipeline(steps=[
            ('preprocessor', preprocessor),
            ('classifier', LogisticRegression(C=self.C, max_iter=1000, solver='lbfgs', random_state=42))
        ])

    def fit(self, X: pd.DataFrame, y: np.ndarray) -> 'LogisticRegressionXGModel':
        df = self._ensure_dataframe(X)
        self.pipeline.fit(df, y)
        self.is_fitted = True
        self.training_date = datetime.now(timezone.utc).isoformat()
        return self


class GradientBoostingXGModel(BaseXGModel):
    """
    Production Expected Goals model using HistGradientBoostingClassifier.
    Captures non-linear geometric and temporal interactions.
    """

    def __init__(self, name: str = "pucklens-xg-boosted", version: str = "1.2.0",
                 learning_rate: float = 0.05, max_iter: int = 150, max_leaf_nodes: int = 31):
        super().__init__(name, version)
        self.learning_rate = learning_rate
        self.max_iter = max_iter
        self.max_leaf_nodes = max_leaf_nodes
        self._build_pipeline()

    def _build_pipeline(self):
        preprocessor = ColumnTransformer(
            transformers=[
                ('num', StandardScaler(), NUMERIC_FEATURES),
                ('cat', OneHotEncoder(handle_unknown='ignore', sparse_output=False), CATEGORICAL_FEATURES)
            ]
        )
        self.pipeline = Pipeline(steps=[
            ('preprocessor', preprocessor),
            ('classifier', HistGradientBoostingClassifier(
                learning_rate=self.learning_rate,
                max_iter=self.max_iter,
                max_leaf_nodes=self.max_leaf_nodes,
                min_samples_leaf=20,
                random_state=42
            ))
        ])

    def fit(self, X: pd.DataFrame, y: np.ndarray) -> 'GradientBoostingXGModel':
        df = self._ensure_dataframe(X)
        self.pipeline.fit(df, y)
        self.is_fitted = True
        self.training_date = datetime.now(timezone.utc).isoformat()
        return self
