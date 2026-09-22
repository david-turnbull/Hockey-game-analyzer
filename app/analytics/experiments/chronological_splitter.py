"""
Chronological and Group-Aware Dataset Splitter.

Enforces strict chronological train -> validation -> test splits (max(train) < min(val))
and group-aware grouping (e.g. game_id), ensuring related rows never cross split boundaries.
"""

import logging
from datetime import datetime, timezone
from typing import Dict, List, Any, Tuple, Optional
from app.analytics.experiments.point_in_time import TemporalLeakageError

logger = logging.getLogger(__name__)


class ChronologicalSplitter:
    """
    Splits datasets into train, validation, and optional test sets
    strictly respecting time ordering and group integrity.
    """

    @classmethod
    def split(
        cls,
        records: List[Dict[str, Any]],
        train_window: Dict[str, Any],
        validation_window: Dict[str, Any],
        test_window: Optional[Dict[str, Any]] = None,
        time_key: str = "timestamp",
        group_key: Optional[str] = "game_id"
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Optional[List[Dict[str, Any]]]]:
        """
        Splits a list of record dicts based on window definitions (seasons or date ranges).

        Returns:
            Tuple of (train_records, val_records, test_records)
        """
        if not records:
            return [], [], [] if test_window else None

        train_records = []
        val_records = []
        test_records = [] if test_window else None

        train_seasons = set(train_window.get("seasons", []))
        val_seasons = set(validation_window.get("seasons", []))
        test_seasons = set(test_window.get("seasons", [])) if test_window else set()

        for rec in records:
            rec_season = rec.get("season")
            rec_time = cls._extract_datetime(rec, time_key)

            # Route record to appropriate split
            if rec_season in train_seasons:
                train_records.append(rec)
            elif rec_season in val_seasons:
                val_records.append(rec)
            elif test_window and rec_season in test_seasons:
                test_records.append(rec)
            else:
                # Fallback to date range checks if specified
                if cls._matches_date_range(rec_time, train_window):
                    train_records.append(rec)
                elif cls._matches_date_range(rec_time, validation_window):
                    val_records.append(rec)
                elif test_window and cls._matches_date_range(rec_time, test_window):
                    test_records.append(rec)

        # Audit chronological ordering and group integrity
        cls.audit_split_leakage(train_records, val_records, test_records, time_key=time_key, group_key=group_key)

        return train_records, val_records, test_records

    @classmethod
    def audit_split_leakage(
        cls,
        train_records: List[Dict[str, Any]],
        val_records: List[Dict[str, Any]],
        test_records: Optional[List[Dict[str, Any]]] = None,
        time_key: str = "timestamp",
        group_key: Optional[str] = "game_id"
    ) -> None:
        """
        Audits chronological split integrity and group separation.
        Fails closed with TemporalLeakageError if:
        1. max(train_time) >= min(val_time)
        2. max(val_time) >= min(test_time)
        3. Any group_id (e.g. game_id) is present in multiple splits.
        """
        if not train_records or not val_records:
            return

        train_times = [cls._extract_datetime(r, time_key) for r in train_records if cls._extract_datetime(r, time_key)]
        val_times = [cls._extract_datetime(r, time_key) for r in val_records if cls._extract_datetime(r, time_key)]

        if train_times and val_times:
            max_train_time = max(train_times)
            min_val_time = min(val_times)

            if max_train_time >= min_val_time:
                raise TemporalLeakageError(
                    f"CHRONOLOGICAL_LEAKAGE: Max train timestamp ({max_train_time.isoformat()}) "
                    f"is not strictly prior to min validation timestamp ({min_val_time.isoformat()})."
                )

        if test_records and val_times:
            test_times = [cls._extract_datetime(r, time_key) for r in test_records if cls._extract_datetime(r, time_key)]
            if test_times:
                max_val_time = max(val_times)
                min_test_time = min(test_times)
                if max_val_time >= min_test_time:
                    raise TemporalLeakageError(
                        f"CHRONOLOGICAL_LEAKAGE: Max validation timestamp ({max_val_time.isoformat()}) "
                        f"is not strictly prior to min test timestamp ({min_test_time.isoformat()})."
                    )

        # Group-aware audit
        if group_key:
            train_groups = set(r.get(group_key) for r in train_records if r.get(group_key) is not None)
            val_groups = set(r.get(group_key) for r in val_records if r.get(group_key) is not None)
            test_groups = set(r.get(group_key) for r in test_records if r.get(group_key) is not None) if test_records else set()

            train_val_overlap = train_groups.intersection(val_groups)
            if train_val_overlap:
                raise TemporalLeakageError(
                    f"GROUP_LEAKAGE: Group key '{group_key}' overlap detected between Train and Validation: {train_val_overlap}."
                )

            if test_records:
                train_test_overlap = train_groups.intersection(test_groups)
                if train_test_overlap:
                    raise TemporalLeakageError(
                        f"GROUP_LEAKAGE: Group key '{group_key}' overlap detected between Train and Test: {train_test_overlap}."
                    )
                val_test_overlap = val_groups.intersection(test_groups)
                if val_test_overlap:
                    raise TemporalLeakageError(
                        f"GROUP_LEAKAGE: Group key '{group_key}' overlap detected between Validation and Test: {val_test_overlap}."
                    )

    @classmethod
    def _extract_datetime(cls, rec: Dict[str, Any], time_key: str) -> Optional[datetime]:
        val = rec.get(time_key)
        if isinstance(val, datetime):
            return val if val.tzinfo else val.replace(tzinfo=timezone.utc)
        elif isinstance(val, str):
            try:
                dt = datetime.fromisoformat(val)
                return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            except ValueError:
                pass

        # Check point_in_time_cutoff metadata
        cutoff_meta = rec.get("point_in_time_cutoff", {})
        cutoff_str = cutoff_meta.get("prediction_cutoff_time")
        if cutoff_str:
            dt = datetime.fromisoformat(cutoff_str)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

        return None

    @classmethod
    def _matches_date_range(cls, rec_time: Optional[datetime], window: Dict[str, Any]) -> bool:
        if not rec_time:
            return False
        start_date_str = window.get("start_date")
        end_date_str = window.get("end_date")

        if start_date_str:
            start_dt = datetime.fromisoformat(start_date_str).replace(tzinfo=timezone.utc)
            if rec_time < start_dt:
                return False

        if end_date_str:
            end_dt = datetime.fromisoformat(end_date_str).replace(tzinfo=timezone.utc)
            if rec_time > end_dt:
                return False

        return True if (start_date_str or end_date_str) else False
