"""
Deterministic Experiment Configuration and Provenance Result Abstractions.

Enforces deterministic config hashing (excluding runtime values, UUIDs, or timestamps)
and structured experiment result serialization.
"""

import json
import hashlib
import sys
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Any, Optional, Literal


TASK_CLASSIFICATION = "classification"
TASK_REGRESSION = "regression"
VALID_TASK_TYPES = [TASK_CLASSIFICATION, TASK_REGRESSION]


@dataclass
class ExperimentConfig:
    """
    Deterministic configuration object for a PuckLens experiment.
    """
    experiment_id: str
    name: str
    task_type: Literal["classification", "regression"]
    target: str
    feature_set: List[str]
    train_window: Dict[str, Any]
    validation_window: Dict[str, Any]
    model_type: str
    test_window: Optional[Dict[str, Any]] = None
    hyperparameters: Dict[str, Any] = field(default_factory=dict)
    feature_version: str = "v1.5.0"
    seed: int = 42

    def __post_init__(self):
        if self.task_type not in VALID_TASK_TYPES:
            raise ValueError(f"Invalid task_type '{self.task_type}'. Must be one of {VALID_TASK_TYPES}.")

        if not self.experiment_id:
            raise ValueError("experiment_id cannot be empty.")

        if not self.target:
            raise ValueError("target variable cannot be empty.")

        if not self.feature_set:
            raise ValueError("feature_set cannot be empty.")

    def compute_config_hash(self) -> str:
        """
        Computes deterministic SHA-256 hash of canonical configuration representation ONLY.
        Excludes runtime values (timestamps, UUIDs, git commit SHAs, metrics).
        """
        canonical_dict = {
            "experiment_id": str(self.experiment_id),
            "name": str(self.name),
            "task_type": str(self.task_type),
            "target": str(self.target),
            "feature_set": sorted([str(f) for f in self.feature_set]),
            "feature_version": str(self.feature_version),
            "train_window": self.train_window,
            "validation_window": self.validation_window,
            "test_window": self.test_window,
            "model_type": str(self.model_type),
            "hyperparameters": self.hyperparameters,
            "seed": int(self.seed)
        }

        canonical_json = json.dumps(canonical_dict, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["config_hash"] = self.compute_config_hash()
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExperimentConfig":
        clean_data = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**clean_data)

    @classmethod
    def from_json(cls, json_str: str) -> "ExperimentConfig":
        return cls.from_dict(json.loads(json_str))


@dataclass
class ExperimentResult:
    """
    Structured container for experiment metrics, audit summaries, and provenance metadata.
    """
    experiment_id: str
    config_hash: str
    task_type: str
    config: ExperimentConfig
    metrics: Dict[str, float]
    sample_counts: Dict[str, int]
    temporal_audit_summary: Dict[str, Any]
    provenance: Dict[str, Any]
    predictions: Optional[List[Dict[str, Any]]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "config_hash": self.config_hash,
            "task_type": self.task_type,
            "config": self.config.to_dict(),
            "metrics": self.metrics,
            "sample_counts": self.sample_counts,
            "temporal_audit_summary": self.temporal_audit_summary,
            "provenance": self.provenance,
            "predictions_count": len(self.predictions) if self.predictions else 0
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)
