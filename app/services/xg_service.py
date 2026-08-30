from app.services.xg_models import HeuristicXGModel

class XGService:
    """Service class that acts as the entrypoint for expected goals (xG) calculations, delegating to a registered model."""
    _model = HeuristicXGModel()

    @classmethod
    def calculate_shot_xg(cls, distance, angle, shot_type=None, strength_state=None, empty_net=False) -> float:
        """
        Calculates the expected goals (xG) probability for a shot attempt.
        Delegates calculation to the registered ExpectedGoalsModel.
        """
        return cls._model.predict(distance, angle, shot_type, strength_state, empty_net)

