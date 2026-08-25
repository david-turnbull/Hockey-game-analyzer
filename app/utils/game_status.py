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


GAME_STATUS_CLASSES = {
    "OFF": "status-final",
    "FINAL": "status-final",
    "FUT": "status-upcoming",
    "PRE": "status-upcoming",
    "LIVE": "status-live",
    "CRIT": "status-live",
    "PPD": "status-postponed",
    "SUSP": "status-suspended",
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


def get_game_status_class(status: str | None) -> str:
    """Return the CSS class used to display an NHL game state."""

    if not status:
        return "status-unknown"

    normalized_status = status.upper()

    return GAME_STATUS_CLASSES.get(
        normalized_status,
        "status-unknown",
    )