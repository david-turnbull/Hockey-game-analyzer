import math
from typing import Dict, List, Any, Tuple
import numpy as np
from sklearn.metrics import log_loss, brier_score_loss, roc_auc_score
from sklearn.calibration import calibration_curve


class ModelEvaluator:
    """
    Evaluates Expected Goals probabilistic classification models.
    Strictly focuses on probabilistic scoring rules (Log Loss, Brier Score, ROC AUC, Calibration)
    rather than plain accuracy, due to the severe class imbalance of hockey goals (~6-8%).
    """

    @staticmethod
    def compute_metrics(y_true: np.ndarray, y_prob: np.ndarray) -> Dict[str, float]:
        """Calculates core evaluation metrics for expected goals."""
        # Clip probabilities to prevent infinite log loss
        clipped_prob = np.clip(y_prob, 1e-7, 1.0 - 1e-7)

        loss = float(log_loss(y_true, clipped_prob))
        brier = float(brier_score_loss(y_true, clipped_prob))
        
        # ROC AUC requires at least one positive and one negative sample
        if len(np.unique(y_true)) > 1:
            auc = float(roc_auc_score(y_true, clipped_prob))
        else:
            auc = 0.5

        return {
            'log_loss': round(loss, 4),
            'brier_score': round(brier, 4),
            'roc_auc': round(auc, 4),
            'actual_goals': int(np.sum(y_true)),
            'total_shots': int(len(y_true)),
            'expected_goals': round(float(np.sum(y_prob)), 2),
            'actual_goal_pct': round(float(np.mean(y_true) * 100), 2),
            'expected_goal_pct': round(float(np.mean(y_prob) * 100), 2)
        }

    @staticmethod
    def compute_calibration(y_true: np.ndarray, y_prob: np.ndarray, n_bins: int = 10) -> Dict[str, Any]:
        """
        Computes calibration curves comparing predicted goal probabilities against observed goal frequencies,
        including shot counts in each probability bin.
        """
        clipped_prob = np.clip(y_prob, 1e-7, 1.0 - 1e-7)
        prob_true, prob_pred = calibration_curve(y_true, clipped_prob, n_bins=n_bins, strategy='uniform')
        
        bins = np.linspace(0.0, 1.0 + 1e-8, n_bins + 1)
        binids = np.digitize(clipped_prob, bins) - 1
        bin_total = np.bincount(binids, minlength=len(bins))
        nonzero = bin_total != 0
        bin_counts = [int(c) for c in bin_total[nonzero]]
        
        return {
            'predicted_probabilities': [round(float(p), 4) for p in prob_pred],
            'observed_frequencies': [round(float(f), 4) for f in prob_true],
            'bin_counts': bin_counts
        }

    @staticmethod
    def breakdown_by_segment(records: List[Dict[str, Any]], y_true: np.ndarray, y_prob: np.ndarray) -> Dict[str, Any]:
        """
        Breaks down expected goals vs actual goals across key hockey dimensions:
        1. Distance brackets (<15 ft, 15-30 ft, 30-45 ft, 45+ ft)
        2. Shot types (wrist, slap, snap, backhand, tip-in, wrap-around, etc.)
        3. Strength state (EV, PP, SH)
        """
        by_distance = {
            '<15 ft': {'actual': 0, 'expected': 0.0, 'shots': 0},
            '15-30 ft': {'actual': 0, 'expected': 0.0, 'shots': 0},
            '30-45 ft': {'actual': 0, 'expected': 0.0, 'shots': 0},
            '45+ ft': {'actual': 0, 'expected': 0.0, 'shots': 0}
        }
        by_shot_type: Dict[str, Dict[str, Any]] = {}
        by_strength: Dict[str, Dict[str, Any]] = {}

        for i, row in enumerate(records):
            actual = int(y_true[i])
            expected = float(y_prob[i])
            dist = float(row.get('distance', 30.0))
            stype = str(row.get('shot_type', 'wrist'))
            strength = str(row.get('strength_state', 'EV'))

            # Distance bracket
            if dist < 15.0:
                d_bracket = '<15 ft'
            elif dist < 30.0:
                d_bracket = '15-30 ft'
            elif dist < 45.0:
                d_bracket = '30-45 ft'
            else:
                d_bracket = '45+ ft'

            by_distance[d_bracket]['actual'] += actual
            by_distance[d_bracket]['expected'] += expected
            by_distance[d_bracket]['shots'] += 1

            # Shot type
            if stype not in by_shot_type:
                by_shot_type[stype] = {'actual': 0, 'expected': 0.0, 'shots': 0}
            by_shot_type[stype]['actual'] += actual
            by_shot_type[stype]['expected'] += expected
            by_shot_type[stype]['shots'] += 1

            # Strength state
            if strength not in by_strength:
                by_strength[strength] = {'actual': 0, 'expected': 0.0, 'shots': 0}
            by_strength[strength]['actual'] += actual
            by_strength[strength]['expected'] += expected
            by_strength[strength]['shots'] += 1

        # Format and round
        def format_group(group_dict):
            out = {}
            for k, v in group_dict.items():
                s = v['shots']
                out[k] = {
                    'shots': s,
                    'actual_goals': v['actual'],
                    'expected_goals': round(v['expected'], 2),
                    'actual_sh_pct': round((v['actual'] / s * 100), 2) if s > 0 else 0.0,
                    'expected_sh_pct': round((v['expected'] / s * 100), 2) if s > 0 else 0.0
                }
            return out

        return {
            'by_distance': format_group(by_distance),
            'by_shot_type': format_group(by_shot_type),
            'by_strength_state': format_group(by_strength)
        }
