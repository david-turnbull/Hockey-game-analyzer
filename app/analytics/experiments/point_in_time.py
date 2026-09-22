"""
Point-in-Time Temporal Contract and Leakage Prevention Adaptor.

Enforces strict temporal cutoffs for feature calculations:
- prediction_cutoff_time (T): Decision boundary (game start UTC) before which all feature inputs must exist.
- latest_source_game_start_time: Timestamp of the most recent completed source game used to construct features.
  Represents the strongest source-game timestamp available in the repository schema.
- target_observation_time: Timestamp when target label is observed (preserved as None if unavailable, or post-cutoff datetime).

Fails closed with TemporalLeakageError when temporal provenance is missing, unverifiable,
or when latest_source_game_start_time >= prediction_cutoff_time.
"""

import logging
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Tuple
from app.services.pregame_feature_service import PregameFeatureService
from app.models import Game

logger = logging.getLogger(__name__)


class TemporalLeakageError(Exception):
    """
    Raised when feature data contains future observations, post-cutoff events,
    or when temporal provenance is missing or unverifiable.
    """
    pass


class PointInTimeCutoff:
    """
    Explicit temporal boundary specification for a prediction instance.
    """

    def __init__(
        self,
        prediction_cutoff_time: datetime,
        latest_source_game_start_time: Optional[datetime] = None,
        target_observation_time: Optional[datetime] = None,
        source_game_ids: Optional[List[int]] = None
    ):
        if not isinstance(prediction_cutoff_time, datetime):
            raise TemporalLeakageError("prediction_cutoff_time must be a valid datetime instance.")

        # Ensure UTC timezone awareness
        if prediction_cutoff_time.tzinfo is None:
            prediction_cutoff_time = prediction_cutoff_time.replace(tzinfo=timezone.utc)

        self.prediction_cutoff_time = prediction_cutoff_time

        if latest_source_game_start_time is not None and latest_source_game_start_time.tzinfo is None:
            latest_source_game_start_time = latest_source_game_start_time.replace(tzinfo=timezone.utc)
        self.latest_source_game_start_time = latest_source_game_start_time

        if target_observation_time is not None and target_observation_time.tzinfo is None:
            target_observation_time = target_observation_time.replace(tzinfo=timezone.utc)
        self.target_observation_time = target_observation_time

        self.source_game_ids = source_game_ids or []

    @property
    def feature_availability_time(self) -> Optional[datetime]:
        """[DEPRECATED/INTERNAL] Alias for latest_source_game_start_time. Not serialized in public provenance."""
        return self.latest_source_game_start_time

    def audit_source_timestamp(self, source_time: Optional[datetime], source_id: Optional[Any] = None) -> None:
        """
        Audits a single source timestamp. Fails closed if missing, invalid, or >= prediction_cutoff_time.
        """
        if source_time is None:
            raise TemporalLeakageError(
                f"UNVERIFIABLE_PROVENANCE: Source data item '{source_id}' has missing or None timestamp. "
                "Failing closed to prevent potential feature leakage."
            )

        if not isinstance(source_time, datetime):
            raise TemporalLeakageError(
                f"INVALID_TIMESTAMP_TYPE: Source data item '{source_id}' timestamp must be a datetime, got {type(source_time)}."
            )

        if source_time.tzinfo is None:
            source_time = source_time.replace(tzinfo=timezone.utc)

        if source_time >= self.prediction_cutoff_time:
            raise TemporalLeakageError(
                f"TEMPORAL_LEAKAGE: Source timestamp ({source_time.isoformat()}) for item '{source_id}' "
                f"is not strictly prior to prediction cutoff time T ({self.prediction_cutoff_time.isoformat()})."
            )

    def to_dict(self) -> Dict[str, Any]:
        """
        Public Stage 5 provenance contract serialization.
        Serializes latest_source_game_start_time (never feature_availability_time).
        """
        safety_passed = (
            self.latest_source_game_start_time is not None and
            self.latest_source_game_start_time < self.prediction_cutoff_time
        )

        return {
            "prediction_cutoff_time": self.prediction_cutoff_time.isoformat(),
            "latest_source_game_start_time": self.latest_source_game_start_time.isoformat() if self.latest_source_game_start_time else None,
            "target_observation_time": self.target_observation_time.isoformat() if self.target_observation_time else None,
            "source_game_ids_count": len(self.source_game_ids),
            "safety_passed": safety_passed
        }


class PointInTimeAdapter:
    """
    Adapter wrapping PregameFeatureService to provide point-in-time features
    with explicit source timestamp auditing.
    """

    @classmethod
    def extract_game_features_with_cutoff(cls, target_game: Game) -> Tuple[Dict[str, float], PointInTimeCutoff]:
        """
        Extracts pregame features for target_game, auditing all source game timestamps used in feature construction.

        Returns:
            Tuple of (features_dict, PointInTimeCutoff)
        """
        if not target_game:
            raise TemporalLeakageError("UNVERIFIABLE_PROVENANCE: target_game is None.")

        # Determine target game start cutoff time
        target_start = target_game.start_time
        if target_start is None:
            if target_game.game_date:
                target_start = datetime.combine(target_game.game_date, datetime.min.time(), tzinfo=timezone.utc)
            else:
                raise TemporalLeakageError(f"UNVERIFIABLE_PROVENANCE: Game {target_game.game_id} missing start_time and game_date.")
        elif target_start.tzinfo is None:
            target_start = target_start.replace(tzinfo=timezone.utc)

        cutoff = PointInTimeCutoff(prediction_cutoff_time=target_start)

        # Audit source games for home and away teams
        home_prior = PregameFeatureService.get_prior_completed_games_for_team(target_game.home_team_id, target_game)
        away_prior = PregameFeatureService.get_prior_completed_games_for_team(target_game.away_team_id, target_game)

        all_source_games = list({g.game_id: g for g in home_prior + away_prior if g.game_id != target_game.game_id}.values())

        if not all_source_games:
            # Fails closed if no prior completed source games exist (unverifiable feature provenance)
            raise TemporalLeakageError(f"UNVERIFIABLE_PROVENANCE: Target game {target_game.game_id} has zero prior completed source games.")

        max_source_time = None
        source_ids = []

        for sg in all_source_games:
            sg_time = sg.start_time
            if sg_time is None:
                if sg.game_date:
                    sg_time = datetime.combine(sg.game_date, datetime.min.time(), tzinfo=timezone.utc)
                else:
                    raise TemporalLeakageError(
                        f"UNVERIFIABLE_PROVENANCE: Source game {sg.game_id} has missing start_time and game_date."
                    )
            elif sg_time.tzinfo is None:
                sg_time = sg_time.replace(tzinfo=timezone.utc)

            # Audit strict inequality: sg_time < cutoff
            cutoff.audit_source_timestamp(sg_time, source_id=sg.game_id)

            source_ids.append(sg.game_id)
            if max_source_time is None or sg_time > max_source_time:
                max_source_time = sg_time

        cutoff.latest_source_game_start_time = max_source_time
        cutoff.source_game_ids = source_ids

        # Target observation time: preserve explicit None if end_time is not established in schema
        target_end = getattr(target_game, 'end_time', None) or getattr(target_game, 'end_time_utc', None)
        if target_end is not None and target_end.tzinfo is None:
            target_end = target_end.replace(tzinfo=timezone.utc)

        cutoff.target_observation_time = target_end

        # Extract features via PregameFeatureService
        features = PregameFeatureService.get_pregame_features(target_game)

        return features, cutoff


def assert_point_in_time_safety(records: List[Dict[str, Any]]) -> bool:
    """
    Audits a collection of extracted dataset records. Fails closed with TemporalLeakageError if:
    1. Any record is missing cutoff metadata.
    2. Any record's latest_source_game_start_time is missing or None.
    3. Any record's latest_source_game_start_time >= prediction_cutoff_time.
    """
    if not records:
        return True

    for idx, rec in enumerate(records):
        cutoff_info = rec.get("point_in_time_cutoff")
        if not cutoff_info:
            raise TemporalLeakageError(
                f"UNVERIFIABLE_PROVENANCE: Record at index {idx} (id={rec.get('game_id') or rec.get('instance_id')}) "
                "lacks point_in_time_cutoff metadata."
            )

        cutoff_time_str = cutoff_info.get("prediction_cutoff_time")
        source_time_str = cutoff_info.get("latest_source_game_start_time")

        if not cutoff_time_str:
            raise TemporalLeakageError(
                f"UNVERIFIABLE_PROVENANCE: Record at index {idx} lacks prediction_cutoff_time."
            )

        if not source_time_str:
            raise TemporalLeakageError(
                f"UNVERIFIABLE_PROVENANCE: Record at index {idx} lacks latest_source_game_start_time."
            )

        cutoff_time = datetime.fromisoformat(cutoff_time_str)
        source_time = datetime.fromisoformat(source_time_str)

        if source_time >= cutoff_time:
            raise TemporalLeakageError(
                f"TEMPORAL_LEAKAGE: Record at index {idx} has latest_source_game_start_time ({source_time_str}) "
                f">= prediction_cutoff_time ({cutoff_time_str})."
            )

    return True
