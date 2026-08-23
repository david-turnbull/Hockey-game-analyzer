GAME_STATUS_LABELS = {
    "OFF": "Final",
    "FINAL": "Final",
    "FUT": "Upcoming",
    "PRE": "Pregame",
    "LIVE": "Live",
    "CRIT": "Live",
    "PPD": "Postponed",
    "SUSP": "Suspended",
}


def get_game_status_label(status: str | None) -> str:
    """Convert an NHL game-state code into a user-friendly label."""

    if not status:
        return "Unknown"

    normalized_status = status.upper()

    return GAME_STATUS_LABELS.get(
        normalized_status,
        normalized_status,
    )