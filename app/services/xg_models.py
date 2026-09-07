from abc import ABC, abstractmethod
import math

class ExpectedGoalsModel(ABC):
    """Abstract base class representing an Expected Goals (xG) estimation model."""

    @abstractmethod
    def predict(self, distance: float, angle: float, shot_type: str = None, strength_state: str = None, empty_net: bool = False) -> float:
        """
        Estimate the expected goals probability for a shot attempt.
        Returns a float between 0.0 and 1.0.
        """
        pass


class HeuristicXGModel(ExpectedGoalsModel):
    """
    Heuristic prototype expected goals model using hand-selected coefficients.
    This acts as the baseline xG provider before training statistical or ML models.
    """

    def predict(self, distance: float, angle: float, shot_type: str = None, strength_state: str = None, empty_net: bool = False) -> float:
        # Baseline constant (approximate log-odds of a typical shot scoring)
        beta_0 = -1.9
        
        # Distance coefficient: farther shots have lower probability
        d = distance if distance is not None else 30.0
        beta_dist = -0.035
        
        # Angle coefficient: wider angles have lower probability (angle in degrees relative to net center)
        a = abs(angle) if angle is not None else 0.0
        beta_angle = -0.015
        
        # Empty Net override
        if empty_net:
            # Linear decay: max 99% near net, min 10% from other side
            prob = max(0.1, 1.0 - (d * 0.005))
            return round(prob, 4)
            
        # Shot type adjustment
        shot_adj = 0.0
        if shot_type:
            s_type = shot_type.lower()
            if 'tip-in' in s_type or 'deflect' in s_type or 'tip' in s_type:
                shot_adj = 0.4
            elif 'slap' in s_type:
                shot_adj = -0.2
            elif 'backhand' in s_type:
                shot_adj = 0.1
                
        # Strength state adjustment
        strength_adj = 0.0
        if strength_state:
            st = strength_state.upper()
            if 'PP' in st or '5V4' in st or '5V3' in st:
                strength_adj = 0.15
            elif 'SH' in st or '4V5' in st or '3V5' in st:
                strength_adj = -0.15
                
        log_odds = beta_0 + (beta_dist * d) + (beta_angle * a) + shot_adj + strength_adj
        
        try:
            prob = 1.0 / (1.0 + math.exp(-log_odds))
        except OverflowError:
            prob = 0.0 if log_odds < 0 else 1.0
            
        return round(prob, 4)
