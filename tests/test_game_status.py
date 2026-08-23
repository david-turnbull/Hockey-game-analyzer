from app.utils.game_status import get_game_status_label


def test_completed_status_labels():
    assert get_game_status_label("OFF") == "Final"
    assert get_game_status_label("FINAL") == "Final"


def test_upcoming_status_labels():
    assert get_game_status_label("FUT") == "Upcoming"
    assert get_game_status_label("PRE") == "Pregame"


def test_live_status_labels():
    assert get_game_status_label("LIVE") == "Live"
    assert get_game_status_label("CRIT") == "Live"


def test_interrupted_status_labels():
    assert get_game_status_label("PPD") == "Postponed"
    assert get_game_status_label("SUSP") == "Suspended"


def test_unknown_status_is_preserved():
    assert get_game_status_label("UNKNOWN_CODE") == "UNKNOWN_CODE"