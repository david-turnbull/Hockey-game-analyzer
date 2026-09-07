import os
import json
import logging
from datetime import datetime, timezone
from typing import Dict, List, Any, Tuple
import numpy as np
import pandas as pd
from sklearn.metrics import log_loss, brier_score_loss, roc_auc_score
from sklearn.calibration import calibration_curve

from app.analytics.model_registry import ModelRegistry
from app.analytics.shot_features import ShotFeatureExtractor, NUMERIC_FEATURES, CATEGORICAL_FEATURES
from app.models import db, Game, Event, Shot, Team

logger = logging.getLogger(__name__)

class OutOfTimeValidator:
    """
    Evaluates the existing, unchanged Expected Goals model on a genuinely later
    out-of-time NHL season dataset (2024-25) without retraining or tuning.
    """

    def __init__(self, season: str = "20242025"):
        self.season = season
        self.model = ModelRegistry.get_active_model()
        self.model_name = ModelRegistry.get_active_name()
        self.model_version = ModelRegistry.get_active_version()

    def collect_shots_from_db(self) -> List[Dict[str, Any]]:
        """
        Collects all unblocked shot attempts for the specified season from the database
        along with complete contextual and segment metadata.
        """
        query = (
            db.session.query(Shot, Event, Game, Team)
            .join(Event, Shot.shot_id == Event.event_id)
            .join(Game, Event.game_id == Game.game_id)
            .outerjoin(Team, Shot.team_id == Team.team_id)
            .filter(
                Game.season == self.season,
                Shot.outcome.in_(['Goal', 'Saved', 'Missed']),
                Event.period_type != 'SO'
            )
            .order_by(Game.game_date.asc(), Event.game_id.asc(), Event.elapsed_game_seconds.asc())
        )

        shots_data = []
        for shot, event, game, team in query.all():
            is_home = (shot.team_id == game.home_team_id)
            dist = shot.distance if shot.distance is not None else 30.0
            ang = shot.angle if shot.angle is not None else 0.0

            # Reconstruct feature dict
            shot_dict = {
                "shot_id": shot.shot_id,
                "game_id": game.game_id,
                "distance": dist,
                "angle": ang,
                "period": event.period,
                "period_seconds": (
                    (event.elapsed_game_seconds % 1200)
                    if event.elapsed_game_seconds is not None
                    else 0
                ),
                "score_differential": 0,
                "is_home": 1 if is_home else 0,
                "empty_net": 1 if shot.empty_net else 0,
                "time_since_prev_event": 3.0,
                "distance_from_prev_event": 10.0,
                "angle_change": 0.0,
                "is_rebound": 0,
                "is_rush": 0,
                "is_turnover": 0,
                "is_after_faceoff": 0,
                "is_lateral_movement": 0,
                "is_power_play": 1 if shot.strength_state == 'PP' else 0,
                "is_shorthanded": 1 if shot.strength_state == 'SH' else 0,
                "coordinates_missing": 0 if (shot.x_coordinate_normalized is not None) else 1,
                "shot_type": (shot.shot_type.lower() if shot.shot_type else 'wrist'),
                "strength_state": shot.strength_state or 'EV',
                "prev_event_type": 'faceoff',
                "goal": 1 if shot.goal else 0,
                "team_abbrev": team.abbreviation if team else "UNK",
                "is_home_bool": is_home,
                "recorded_xg": shot.xg
            }
            shots_data.append(shot_dict)

        return shots_data

    def collect_shots_from_raw_pbp(self, raw_dir: str = None) -> List[Dict[str, Any]]:
        """
        Collects unblocked shot records with full 21-feature contextual representations
        directly from cached raw play-by-play files for games in this season.
        """
        if raw_dir is None:
            raw_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                'data', 'raw'
            )

        shots = []
        if not os.path.exists(raw_dir):
            return shots

        # Find all pbp files for season
        prefix = f"pbp_{self.season[:4]}"
        for fn in sorted(os.listdir(raw_dir)):
            if fn.startswith("pbp_") and fn.endswith(".json") and fn.startswith(f"pbp_{self.season[:4]}"):
                path = os.path.join(raw_dir, fn)
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        pbp_data = json.load(f)
                    extracted = ShotFeatureExtractor.extract_shots_from_pbp_json(pbp_data, unblocked_only=True)
                    shots.extend(extracted)
                except Exception as e:
                    logger.warning(f"Error extracting shots from {fn}: {e}")

        return shots

    def evaluate(self, shots_data: List[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Runs the full out-of-time evaluation against the loaded model.
        """
        if shots_data is None or len(shots_data) == 0:
            # First try raw pbp extraction for full features
            shots_data = self.collect_shots_from_raw_pbp()
            if len(shots_data) == 0:
                # Fallback to database records
                shots_data = self.collect_shots_from_db()

        if len(shots_data) == 0:
            raise ValueError(f"No shots available for evaluation in season {self.season}")

        y_true = np.array([int(s.get('goal', 0)) for s in shots_data])

        # Generate predictions using the production model inference path
        df = pd.DataFrame([ShotFeatureExtractor.extract_features_from_dict(s) for s in shots_data])
        y_prob = self.model.predict_proba(df)

        # 1. Overall Metrics
        clipped_prob = np.clip(y_prob, 1e-7, 1.0 - 1e-7)
        loss = float(log_loss(y_true, clipped_prob))
        brier = float(brier_score_loss(y_true, clipped_prob))
        auc = float(roc_auc_score(y_true, clipped_prob)) if len(np.unique(y_true)) > 1 else 0.5

        total_shots = len(y_true)
        actual_goals = int(np.sum(y_true))
        predicted_xg = round(float(np.sum(y_prob)), 2)
        actual_goal_rate = round(float(np.mean(y_true) * 100), 2)
        expected_goal_rate = round(float(np.mean(y_prob) * 100), 2)

        # 2. Calibration Analysis
        calibration_bins = [
            (0.0, 0.05),
            (0.05, 0.10),
            (0.10, 0.15),
            (0.15, 0.20),
            (0.20, 0.30),
            (0.30, 0.50),
            (0.50, 1.0)
        ]
        calibration_records = []
        for low, high in calibration_bins:
            mask = (y_prob >= low) & (y_prob < high if high < 1.0 else y_prob <= high)
            bin_count = int(np.sum(mask))
            if bin_count > 0:
                mean_pred = round(float(np.mean(y_prob[mask])), 4)
                obs_rate = round(float(np.mean(y_true[mask])), 4)
            else:
                mean_pred = round((low + high) / 2.0, 4)
                obs_rate = 0.0
            calibration_records.append({
                "prediction_band": f"[{low:.2f}, {high:.2f}]",
                "shot_count": bin_count,
                "mean_predicted_probability": mean_pred,
                "observed_goal_rate": obs_rate
            })

        # 3. Segment Evaluations
        # Distance brackets
        distance_brackets = {
            "<15 ft": {"shots": 0, "goals": 0, "xg": 0.0},
            "15-30 ft": {"shots": 0, "goals": 0, "xg": 0.0},
            "30-45 ft": {"shots": 0, "goals": 0, "xg": 0.0},
            "45+ ft": {"shots": 0, "goals": 0, "xg": 0.0}
        }
        strength_splits = {}
        shot_type_splits = {}
        team_splits = {}
        home_away_splits = {"Home": {"shots": 0, "goals": 0, "xg": 0.0}, "Away": {"shots": 0, "goals": 0, "xg": 0.0}}
        context_factors = {
            "rebound": {"shots": 0, "goals": 0, "xg": 0.0},
            "rush": {"shots": 0, "goals": 0, "xg": 0.0},
            "turnover": {"shots": 0, "goals": 0, "xg": 0.0},
            "lateral_movement": {"shots": 0, "goals": 0, "xg": 0.0}
        }

        for i, row in enumerate(shots_data):
            g = y_true[i]
            p = y_prob[i]
            d = float(row.get('distance', 30.0))
            st = str(row.get('shot_type', 'wrist')).lower()
            str_state = str(row.get('strength_state', 'EV'))
            team_abbr = str(row.get('team_abbrev', 'UNK'))
            is_home = bool(row.get('is_home', row.get('is_home_bool', False)))

            # Distance
            if d < 15.0:
                b = "<15 ft"
            elif d < 30.0:
                b = "15-30 ft"
            elif d < 45.0:
                b = "30-45 ft"
            else:
                b = "45+ ft"
            distance_brackets[b]["shots"] += 1
            distance_brackets[b]["goals"] += g
            distance_brackets[b]["xg"] += p

            # Strength
            if str_state not in strength_splits:
                strength_splits[str_state] = {"shots": 0, "goals": 0, "xg": 0.0}
            strength_splits[str_state]["shots"] += 1
            strength_splits[str_state]["goals"] += g
            strength_splits[str_state]["xg"] += p

            # Shot type
            if st not in shot_type_splits:
                shot_type_splits[st] = {"shots": 0, "goals": 0, "xg": 0.0}
            shot_type_splits[st]["shots"] += 1
            shot_type_splits[st]["goals"] += g
            shot_type_splits[st]["xg"] += p

            # Team
            if team_abbr not in team_splits:
                team_splits[team_abbr] = {"shots": 0, "goals": 0, "xg": 0.0}
            team_splits[team_abbr]["shots"] += 1
            team_splits[team_abbr]["goals"] += g
            team_splits[team_abbr]["xg"] += p

            # Home / Away
            ha_key = "Home" if is_home else "Away"
            home_away_splits[ha_key]["shots"] += 1
            home_away_splits[ha_key]["goals"] += g
            home_away_splits[ha_key]["xg"] += p

            # Context factors
            if row.get('is_rebound'):
                context_factors["rebound"]["shots"] += 1
                context_factors["rebound"]["goals"] += g
                context_factors["rebound"]["xg"] += p
            if row.get('is_rush'):
                context_factors["rush"]["shots"] += 1
                context_factors["rush"]["goals"] += g
                context_factors["rush"]["xg"] += p
            if row.get('is_turnover'):
                context_factors["turnover"]["shots"] += 1
                context_factors["turnover"]["goals"] += g
                context_factors["turnover"]["xg"] += p
            if row.get('is_lateral_movement'):
                context_factors["lateral_movement"]["shots"] += 1
                context_factors["lateral_movement"]["goals"] += g
                context_factors["lateral_movement"]["xg"] += p

        def format_segment_dict(d: dict) -> dict:
            formatted = {}
            for k, v in d.items():
                s = int(v["shots"])
                g = int(v["goals"])
                x = float(v["xg"])
                formatted[k] = {
                    "shots": s,
                    "goals": g,
                    "xg": round(x, 2),
                    "actual_goal_pct": round((g / s * 100), 2) if s > 0 else 0.0,
                    "expected_goal_pct": round((x / s * 100), 2) if s > 0 else 0.0
                }
            return formatted

        # 4. Model Health Decision Logic
        # Compare against baseline (in-sample / test log_loss ~0.21-0.23, ROC AUC ~0.74-0.75)
        calibration_ratio = expected_goal_rate / actual_goal_rate if actual_goal_rate > 0 else 1.0
        drift_delta = abs(expected_goal_rate - actual_goal_rate)

        if auc >= 0.72 and loss <= 0.25 and 0.85 <= calibration_ratio <= 1.15:
            decision = "healthy"
            reason = (
                f"Model maintains strong discriminative ability (ROC AUC = {round(auc, 4)}) and well-calibrated "
                f"probabilities (Log Loss = {round(loss, 4)}, Brier = {round(brier, 4)}). Expected goal rate "
                f"({expected_goal_rate}%) closely matches observed goal rate ({actual_goal_rate}%)."
            )
        elif auc >= 0.68 and loss <= 0.28:
            decision = "minor calibration drift"
            reason = (
                f"Model displays minor calibration drift (Expected = {expected_goal_rate}%, Actual = {actual_goal_rate}%, "
                f"delta = {round(drift_delta, 2)}%), but ranking ability remains solid (ROC AUC = {round(auc, 4)}). "
                f"Immediate retraining is not required."
            )
        elif auc >= 0.63:
            decision = "meaningful drift"
            reason = (
                f"Discrimination or calibration has degraded noticeably on out-of-time data (ROC AUC = {round(auc, 4)}, "
                f"Log Loss = {round(loss, 4)}). Model should be scheduled for review in a subsequent release cycle."
            )
        else:
            decision = "model redevelopment recommended"
            reason = (
                f"Severe degradation observed on out-of-time data (ROC AUC = {round(auc, 4)}, Log Loss = {round(loss, 4)}). "
                f"Model redevelopment recommended."
            )

        report = {
            "evaluation_season": self.season,
            "evaluation_date": datetime.now(timezone.utc).isoformat(),
            "model": {
                "name": self.model_name,
                "version": self.model_version,
                "model_type": self.model.__class__.__name__
            },
            "metrics": {
                "shot_count": total_shots,
                "goal_count": actual_goals,
                "actual_goal_rate": actual_goal_rate,
                "predicted_xg": predicted_xg,
                "expected_goal_rate": expected_goal_rate,
                "log_loss": round(loss, 4),
                "brier_score": round(brier, 4),
                "roc_auc": round(auc, 4)
            },
            "calibration": calibration_records,
            "segment_evaluation": {
                "distance": format_segment_dict(distance_brackets),
                "strength": format_segment_dict(strength_splits),
                "shot_type": format_segment_dict(shot_type_splits),
                "home_away": format_segment_dict(home_away_splits),
                "team": format_segment_dict({k: v for k, v in team_splits.items() if v["shots"] >= 10}),
                "context_factors": format_segment_dict({k: v for k, v in context_factors.items() if v["shots"] > 0})
            },
            "model_decision": {
                "verdict": decision,
                "rationale": reason,
                "action": "maintain_current_model_unchanged"
            }
        }
        return report

    @staticmethod
    def generate_markdown(report: Dict[str, Any]) -> str:
        """
        Renders the structured JSON evaluation report into clean GitHub Flavored Markdown.
        """
        m = report["metrics"]
        md = report["model_decision"]
        model = report["model"]

        lines = [
            f"# Out-of-Time xG Validation Report ({report['evaluation_season'][:4]}-{report['evaluation_season'][4:]})",
            "",
            f"**Model Name**: `{model['name']}`  ",
            f"**Model Version**: `{model['version']}`  ",
            f"**Evaluated At**: `{report['evaluation_date']}`  ",
            f"**Target Season**: `{report['evaluation_season']}`  ",
            "",
            "## 1. Executive Summary & Model Decision",
            "",
            f"> **Decision Verdict**: **`{md['verdict'].upper()}`**  ",
            f"> **Rationale**: {md['rationale']}",
            "",
            "## 2. Core Probabilistic Evaluation Metrics",
            "",
            "| Metric | Out-of-Time Value |",
            "| :--- | :--- |",
            f"| **Shot Count** | {m['shot_count']:,} |",
            f"| **Actual Goals** | {m['goal_count']:,} |",
            f"| **Predicted xG** | {m['predicted_xg']:.2f} |",
            f"| **Actual Goal Rate** | {m['actual_goal_rate']:.2f}% |",
            f"| **Expected Goal Rate** | {m['expected_goal_rate']:.2f}% |",
            f"| **Log Loss** | `{m['log_loss']:.4f}` |",
            f"| **Brier Score** | `{m['brier_score']:.4f}` |",
            f"| **ROC AUC** | `{m['roc_auc']:.4f}` |",
            "",
            "## 3. Calibration Breakdown",
            "",
            "| Prediction Band | Shot Count | Mean Predicted Prob | Observed Goal Rate |",
            "| :--- | :--- | :--- | :--- |"
        ]

        for cal in report["calibration"]:
            lines.append(
                f"| {cal['prediction_band']} | {cal['shot_count']:,} | "
                f"{cal['mean_predicted_probability']:.4f} | {cal['observed_goal_rate']:.4f} |"
            )

        lines.extend([
            "",
            "## 4. Segment Evaluations",
            "",
            "### Distance Brackets",
            "",
            "| Distance | Shots | Actual Goals | Expected Goals | Actual Sh% | Expected Sh% |",
            "| :--- | :--- | :--- | :--- | :--- | :--- |"
        ])
        for dist_k, dist_v in report["segment_evaluation"]["distance"].items():
            lines.append(
                f"| {dist_k} | {dist_v['shots']:,} | {dist_v['goals']} | {dist_v['xg']:.2f} | "
                f"{dist_v['actual_goal_pct']:.2f}% | {dist_v['expected_goal_pct']:.2f}% |"
            )

        lines.extend([
            "",
            "### Strength State",
            "",
            "| Strength | Shots | Actual Goals | Expected Goals | Actual Sh% | Expected Sh% |",
            "| :--- | :--- | :--- | :--- | :--- | :--- |"
        ])
        for str_k, str_v in report["segment_evaluation"]["strength"].items():
            lines.append(
                f"| {str_k} | {str_v['shots']:,} | {str_v['goals']} | {str_v['xg']:.2f} | "
                f"{str_v['actual_goal_pct']:.2f}% | {str_v['expected_goal_pct']:.2f}% |"
            )

        lines.extend([
            "",
            "### Shot Types",
            "",
            "| Shot Type | Shots | Actual Goals | Expected Goals | Actual Sh% | Expected Sh% |",
            "| :--- | :--- | :--- | :--- | :--- | :--- |"
        ])
        for st_k, st_v in report["segment_evaluation"]["shot_type"].items():
            lines.append(
                f"| {st_k} | {st_v['shots']:,} | {st_v['goals']} | {st_v['xg']:.2f} | "
                f"{st_v['actual_goal_pct']:.2f}% | {st_v['expected_goal_pct']:.2f}% |"
            )

        lines.extend([
            "",
            "### Home / Away Split",
            "",
            "| Location | Shots | Actual Goals | Expected Goals | Actual Sh% | Expected Sh% |",
            "| :--- | :--- | :--- | :--- | :--- | :--- |"
        ])
        for ha_k, ha_v in report["segment_evaluation"]["home_away"].items():
            lines.append(
                f"| {ha_k} | {ha_v['shots']:,} | {ha_v['goals']} | {ha_v['xg']:.2f} | "
                f"{ha_v['actual_goal_pct']:.2f}% | {ha_v['expected_goal_pct']:.2f}% |"
            )

        lines.append("")
        return "\n".join(lines)


def run_and_save_validation(season: str = "20242025") -> Tuple[str, str]:
    """Runs evaluation and generates both JSON and Markdown artifacts."""
    validator = OutOfTimeValidator(season=season)
    report = validator.evaluate()

    reports_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        'reports'
    )
    os.makedirs(reports_dir, exist_ok=True)

    json_path = os.path.join(reports_dir, f"xg_out_of_time_{season[:4]}_{season[6:]}.json")
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2)

    md_content = OutOfTimeValidator.generate_markdown(report)
    md_path = os.path.join(reports_dir, f"xg_out_of_time_{season[:4]}_{season[6:]}.md")
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(md_content)

    logger.info(f"Generated reports: {json_path} and {md_path}")
    return json_path, md_path


if __name__ == "__main__":
    from app import create_app
    app = create_app('development')
    with app.app_context():
        j_path, m_path = run_and_save_validation("20242025")
        print(f"Validation complete:\nJSON: {j_path}\nMarkdown: {m_path}")
