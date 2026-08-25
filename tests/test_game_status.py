from app.utils.game_status import (
    get_game_status_label,
    get_game_status_class,
)

def test_off_status_displays_as_final():
    assert get_game_status_label("OFF") == "Final"


def test_final_status_displays_as_final():
    assert get_game_status_label("FINAL") == "Final"


def test_live_statuses_display_as_live():
    assert get_game_status_label("LIVE") == "Live"
    assert get_game_status_label("CRIT") == "Live"


def test_future_statuses_are_user_friendly():
    assert get_game_status_label("FUT") == "Upcoming"
    assert get_game_status_label("PRE") == "Pregame"


def test_exception_statuses_are_user_friendly():
    assert get_game_status_label("PPD") == "Postponed"
    assert get_game_status_label("SUSP") == "Suspended"


def test_missing_status_returns_unknown():
    assert get_game_status_label(None) == "Unknown"


def test_unknown_status_is_preserved():
    assert get_game_status_label("XYZ") == "XYZ"

def test_completed_game_status_style():
    assert get_game_status_class("OFF") == "status-final"
    assert get_game_status_class("FINAL") == "status-final"


def test_live_game_status_style():
    assert get_game_status_class("LIVE") == "status-live"
    assert get_game_status_class("CRIT") == "status-live"


def test_upcoming_game_status_style():
    assert get_game_status_class("FUT") == "status-upcoming"
    assert get_game_status_class("PRE") == "status-upcoming"


def test_postponed_game_status_style():
    assert get_game_status_class("PPD") == "status-postponed"


def test_suspended_game_status_style():
    assert get_game_status_class("SUSP") == "status-suspended"


def test_unknown_game_status_style():
    assert get_game_status_class("XYZ") == "status-unknown"
    assert get_game_status_class(None) == "status-unknown"