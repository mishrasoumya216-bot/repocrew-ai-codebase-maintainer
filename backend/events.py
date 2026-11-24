"""RepoCrew event recording + live broadcast.

Every pipeline event is (1) persisted to the ``events`` table and
(2) broadcast to all WebSocket subscribers of that run.

Event schema: {id, run_id, ts, agent, type, text, data?}
  agent: orchestrator | triage | coder | tester | reviewer | gate
  type:  step | message | tool_call | tool_result | status | log
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

from .database import SessionLocal
from .models import Event

# run_id -> set of subscriber queues (all within the single uvicorn loop)
_subscribers: dict[int, set[asyncio.Queue]] = {}


def subscribe(run_id: int) -> asyncio.Queue:
    queue: asyncio.Queue = asyncio.Queue(maxsize=2000)
    _subscribers.setdefault(run_id, set()).add(queue)
    return queue


def unsubscribe(run_id: int, queue: asyncio.Queue) -> None:
    queues = _subscribers.get(run_id)
    if queues is not None:
        queues.discard(queue)
        if not queues:
            _subscribers.pop(run_id, None)


def emit(run_id: int, agent: str, type: str, text: str, data: Any = None) -> dict:
    """Persist an event and broadcast it to subscribers. Returns the payload."""
    ts = time.time()
    session = SessionLocal()
    try:
        row = Event(run_id=run_id, ts=ts, agent=agent, type=type, text=text, data=data)
        session.add(row)
        session.commit()
        session.refresh(row)
        payload = {
            "id": row.id,
            "run_id": run_id,
            "ts": ts,
            "agent": agent,
            "type": type,
            "text": text,
            "data": data,
        }
    finally:
        session.close()
    for queue in list(_subscribers.get(run_id, ())):
        try:
            queue.put_nowait(payload)
        except asyncio.QueueFull:
            pass
    return payload
