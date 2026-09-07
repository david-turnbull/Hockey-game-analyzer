def format_toi(total_seconds: int) -> str:
    """Formats an integer number of seconds into MM:SS string."""
    if not total_seconds or total_seconds < 0:
        return "00:00"
    minutes = int(total_seconds) // 60
    seconds = int(total_seconds) % 60
    return f"{minutes:02d}:{seconds:02d}"
