"""
Simple in-memory conversation history, keyed by session_id.
No database - this resets if the server restarts, which is
acceptable for a college project demo.
"""

# Structure: { session_id: [ {"role": "user"/"assistant", "content": "..."} , ... ] }
_sessions: dict[str, list[dict]] = {}

MAX_TURNS_REMEMBERED = 6  # keep last 6 messages (3 exchanges) to keep prompts small


def get_history(session_id: str) -> list[dict]:
    """Return the conversation history for a session (empty list if new)."""
    return _sessions.get(session_id, [])


def add_message(session_id: str, role: str, content: str) -> None:
    """Append a message to a session's history, trimming old messages if too long."""
    if session_id not in _sessions:
        _sessions[session_id] = []

    _sessions[session_id].append({"role": role, "content": content})

    # Keep only the most recent messages
    if len(_sessions[session_id]) > MAX_TURNS_REMEMBERED:
        _sessions[session_id] = _sessions[session_id][-MAX_TURNS_REMEMBERED:]


def format_history_for_prompt(session_id: str) -> str:
    """Turn history into a short readable block to prepend to the prompt."""
    history = get_history(session_id)
    if not history:
        return ""

    lines = []
    for msg in history:
        speaker = "Farmer" if msg["role"] == "user" else "AgriTwin AI"
        lines.append(f"{speaker}: {msg['content']}")

    return "PREVIOUS CONVERSATION:\n" + "\n".join(lines) + "\n\n"