"""
Holds the most recent /analyze input in memory so /chat can use the real analysis.

* Stored per session_id (so /analyze(session_id="test1") -> /chat(session_id="test1") works)
* AND as the global "latest" snapshot, which /chat falls back to when its own session has nothing
  (single-farm demo behaviour, same as before).

Note: resets when the server restarts; fine for a college-project demo.
"""

_DEFAULT = "default"
_by_session: dict[str, tuple] = {}
_global_latest: tuple | None = None   # (sensor_history, weather_forecast, daily_forecast)


def update_latest(sensor_history: list[dict], weather_forecast: dict, daily_forecast=None,
                  session_id: str = _DEFAULT) -> None:
    global _global_latest
    snapshot = (sensor_history, weather_forecast, daily_forecast)
    _by_session[session_id] = snapshot
    _global_latest = snapshot


def get_latest(session_id: str | None = None):
    """
    Returns (sensor_history, weather_forecast, daily_forecast) for the session, else the global latest,
    else (None, None, None).
    """
    snapshot = _by_session.get(session_id) if session_id else None
    if snapshot is None:
        snapshot = _global_latest
    return snapshot if snapshot is not None else (None, None, None)


def has_session(session_id: str) -> bool:
    return session_id in _by_session