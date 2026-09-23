"""
PuckLens Presentation Mode Architecture.

Manages presentation modes:
- Beginner ("What happened?")
- Intermediate ("What happened, and why?")
- Professional ("Give me the data.")

Changes how analytics are explained and displayed across PuckLens pages while preserving
underlying data, calculations, models, and API truth 100%.
"""

import logging
from typing import Dict, Any, Optional, List
from flask import request, session
from app.services.methodology_registry import MethodologyRegistry

logger = logging.getLogger(__name__)

MODE_BEGINNER = "beginner"
MODE_INTERMEDIATE = "intermediate"
MODE_PROFESSIONAL = "professional"

DEFAULT_MODE = MODE_INTERMEDIATE
VALID_MODES = {MODE_BEGINNER, MODE_INTERMEDIATE, MODE_PROFESSIONAL}

MODE_METADATA = {
    MODE_BEGINNER: {
        "key": MODE_BEGINNER,
        "label": "Beginner",
        "tagline": "What happened?",
        "badge_class": "mode-badge-beginner",
        "badge_style": "background: rgba(16, 185, 129, 0.15); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.3);",
        "description": "High-level takeaways and simplified metrics for quick insights without technical jargon."
    },
    MODE_INTERMEDIATE: {
        "key": MODE_INTERMEDIATE,
        "label": "Intermediate",
        "tagline": "What happened, and why?",
        "badge_class": "mode-badge-intermediate",
        "badge_style": "background: rgba(56, 189, 248, 0.15); color: #38bdf8; border: 1px solid rgba(56, 189, 248, 0.3);",
        "description": "Balanced analytical metrics with context, explanations, and progressive methodology access."
    },
    MODE_PROFESSIONAL: {
        "key": MODE_PROFESSIONAL,
        "label": "Professional",
        "tagline": "Give me the data.",
        "badge_class": "mode-badge-professional",
        "badge_style": "background: rgba(168, 85, 247, 0.15); color: #c084fc; border: 1px solid rgba(168, 85, 247, 0.3);",
        "description": "Dense statistical views, raw counting totals, advanced rates, and model provenance."
    }
}


class PresentationModeService:
    """Service managing analytical presentation modes and dynamic metadata formatting."""

    @classmethod
    def normalize_mode(cls, raw_mode: Optional[str]) -> str:
        """Validates and normalizes raw mode string, falling back to default when invalid."""
        if not raw_mode or not isinstance(raw_mode, str):
            return DEFAULT_MODE
        clean = raw_mode.strip().lower()
        if clean in VALID_MODES:
            return clean
        return DEFAULT_MODE

    @classmethod
    def get_current_mode(cls) -> str:
        """
        Resolves active presentation mode for the current Flask request.
        Priority:
        1. Query param (`?mode=` or `?presentation_mode=`)
        2. Session (`session['presentation_mode']`)
        3. Cookie (`request.cookies.get('presentation_mode')`)
        4. Default (`intermediate`)
        """
        try:
            # 1. Query parameter
            query_mode = request.args.get('mode') or request.args.get('presentation_mode')
            if query_mode:
                norm = cls.normalize_mode(query_mode)
                if 'session' in dir() and session is not None:
                    session['presentation_mode'] = norm
                return norm

            # 2. Flask session
            if session and 'presentation_mode' in session:
                return cls.normalize_mode(session['presentation_mode'])

            # 3. Cookie fallback
            cookie_mode = request.cookies.get('presentation_mode')
            if cookie_mode:
                return cls.normalize_mode(cookie_mode)

        except Exception as e:
            logger.debug(f"Error resolving presentation mode: {e}")

        return DEFAULT_MODE

    @classmethod
    def get_mode_info(cls, mode: Optional[str] = None) -> Dict[str, Any]:
        """Returns structured UI metadata for the given or current presentation mode."""
        active_mode = cls.normalize_mode(mode) if mode else cls.get_current_mode()
        return MODE_METADATA.get(active_mode, MODE_METADATA[DEFAULT_MODE]).copy()

    @classmethod
    def list_all_modes(cls) -> List[Dict[str, Any]]:
        """Lists all available presentation modes and their metadata."""
        return [meta.copy() for meta in MODE_METADATA.values()]

    @classmethod
    def format_metric(cls, metric_key: str, mode: Optional[str] = None, raw_value: Any = None) -> Dict[str, Any]:
        """
        Integrates with Stage 3 MethodologyRegistry to return mode-tailored presentation fields
        for a given metric while preserving exact analytical values.
        """
        active_mode = cls.normalize_mode(mode) if mode else cls.get_current_mode()
        metric_def = MethodologyRegistry.get_metric(metric_key)

        if not metric_def:
            return {
                "key": metric_key,
                "mode": active_mode,
                "value": raw_value,
                "display_name": metric_key,
                "description": "",
                "methodology": None
            }

        d = metric_def.to_dict()

        if active_mode == MODE_BEGINNER:
            return {
                "key": metric_key,
                "mode": active_mode,
                "value": raw_value,
                "display_name": cls._get_beginner_name(metric_key, d["name"]),
                "summary": d["interpretation"],
                "strength_context": d["strength_context"],
                "units": d["units"],
                "show_technical_details": False
            }
        elif active_mode == MODE_INTERMEDIATE:
            return {
                "key": metric_key,
                "mode": active_mode,
                "value": raw_value,
                "display_name": d["name"],
                "definition": d["definition"],
                "formula": d["formula"],
                "interpretation": d["interpretation"],
                "caveats": d["caveats"],
                "strength_context": d["strength_context"],
                "units": d["units"],
                "methodology_reference": d["references_or_methodology"],
                "show_technical_details": True,
                "progressive_disclosure": True
            }
        else:  # PROFESSIONAL
            return {
                "key": metric_key,
                "mode": active_mode,
                "value": raw_value,
                "display_name": cls._get_professional_name(metric_key, d["name"]),
                "formula": d["formula"],
                "inputs": d["inputs"],
                "version": d["version"],
                "category": d["category"],
                "references": d["references_or_methodology"],
                "show_technical_details": True,
                "dense_mode": True
            }

    @staticmethod
    def _get_beginner_name(key: str, default_name: str) -> str:
        names = {
            "cf_pct": "Shot Attempt Control",
            "ff_pct": "Unblocked Shot Control",
            "on_ice_xg_pct": "Scoring Chance Quality Share",
            "xg": "Expected Goals Generated",
            "goals_above_expected": "Finishing Impact (G - xG)",
            "shooting_pct": "Shooting Efficiency",
            "expected_conversion_pct": "Shot Quality Rating",
            "goals_per_60": "Goal Scoring Rate (P60)",
            "xg_per_60": "Chance Generation Rate (P60)"
        }
        return names.get(key, default_name)

    @staticmethod
    def _get_professional_name(key: str, default_name: str) -> str:
        names = {
            "cf_pct": "CF%",
            "ff_pct": "FF%",
            "on_ice_xg_pct": "xG%",
            "xg": "xG",
            "goals_above_expected": "G-xG",
            "shooting_pct": "SH%",
            "expected_conversion_pct": "ExpConv%",
            "goals_per_60": "G/60",
            "xg_per_60": "xG/60"
        }
        return names.get(key, default_name)
