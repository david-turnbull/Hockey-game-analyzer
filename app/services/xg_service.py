import math

class XGService:
    @staticmethod
    def calculate_shot_xg(distance, angle, shot_type=None, strength_state=None, empty_net=False) -> float:
        """
        Calculates the expected goals (xG) probability for a shot attempt.
        Returns a float between 0.0 and 1.0 (rounded to 4 decimal places).

        This is a prototype heuristic xG model using hand-selected coefficients,
        rather than a statistically trained ML model.

        Formula:
            log_odds = beta_0 + (beta_dist * distance) + (beta_angle * abs(angle))
                       + shot_type_adjustment + strength_state_adjustment

            probability = 1 / (1 + exp(-log_odds))

        Coefficients:
            beta_0 (Baseline log-odds): -1.9 (representing ~13% average conversion)
            beta_dist (Distance decay): -0.035 per foot
            beta_angle (Angle decay): -0.015 per degree (from net center)

        Adjustments:
            Shot Types:
                - Tip-In, Deflection, Tip: +0.4 log-odds (higher danger)
                - Backhand: +0.1 log-odds
                - Slap Shot: -0.2 log-odds (lower danger from distance)
            Strength States:
                - Power Play (e.g. PP, 5v4, 5v3): +0.15 log-odds
                - Shorthanded (e.g. SH, 4v5, 3v5): -0.15 log-odds

        Empty Net Override:
            If empty_net is True:
                probability = max(0.1, 1.0 - (distance * 0.005))
                (Linear decay from 99% near net to 10% from own side)
        """
        # Baseline constant (approximate log-odds of a typical shot scoring)
        # Average NHL shooting percentage is about 9-10% (log-odds = -2.2)
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
