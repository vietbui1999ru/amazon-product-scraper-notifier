import asyncio
import json
from collections import deque
from typing import Any

# Last N events kept for new SSE clients joining mid-session
_HISTORY_SIZE = 100
_history: deque[str] = deque(maxlen=_HISTORY_SIZE)
_subscribers: list[asyncio.Queue[str]] = []


def publish(event: dict[str, Any]) -> None:
    """Called by the structlog processor on every log event (sync context)."""
    line = json.dumps(event)
    _history.append(line)
    for q in _subscribers:
        try:
            q.put_nowait(line)
        except asyncio.QueueFull:
            pass


def subscribe() -> asyncio.Queue[str]:
    q: asyncio.Queue[str] = asyncio.Queue(maxsize=200)
    for line in _history:
        q.put_nowait(line)
    _subscribers.append(q)
    return q


def unsubscribe(q: asyncio.Queue[str]) -> None:
    try:
        _subscribers.remove(q)
    except ValueError:
        pass
