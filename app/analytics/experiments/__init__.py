"""
PuckLens Stage 5 Modelling & Experiment Foundation.

Provides point-in-time temporal abstractions, deterministic experiment configuration,
chronological group-aware dataset splitting, task-aware baseline models, and experiment runner.
"""

from app.analytics.experiments.point_in_time import (
    PointInTimeCutoff,
    PointInTimeAdapter,
    TemporalLeakageError,
    assert_point_in_time_safety
)
from app.analytics.experiments.experiment_config import (
    ExperimentConfig,
    ExperimentResult
)
from app.analytics.experiments.chronological_splitter import (
    ChronologicalSplitter
)
from app.analytics.experiments.baselines import (
    HistoricalMeanBaseline,
    TrailingNMeanBaseline,
    SimpleLogisticBaseline,
    SimpleLinearBaseline,
    SimpleRidgeBaseline,
    evaluate_predictions
)
from app.analytics.experiments.runner import (
    ExperimentRunner
)

__all__ = [
    "PointInTimeCutoff",
    "PointInTimeAdapter",
    "TemporalLeakageError",
    "assert_point_in_time_safety",
    "ExperimentConfig",
    "ExperimentResult",
    "ChronologicalSplitter",
    "HistoricalMeanBaseline",
    "TrailingNMeanBaseline",
    "SimpleLogisticBaseline",
    "SimpleLinearBaseline",
    "SimpleRidgeBaseline",
    "evaluate_predictions",
    "ExperimentRunner",
]
