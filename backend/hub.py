"""WebSocket connection manager: broadcasts AppState JSON to every HUD/control client."""
import asyncio
import logging

from fastapi import WebSocket

log = logging.getLogger("lowsight.hub")
SEND_TIMEOUT_S = 1.0


class Hub:
    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._clients.add(ws)

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients.discard(ws)

    async def broadcast(self, text: str) -> None:
        async with self._lock:
            clients = list(self._clients)
        dead = []
        for ws in clients:
            try:
                # A client that stops reading must not stall every demo's updates.
                await asyncio.wait_for(ws.send_text(text), SEND_TIMEOUT_S)
            except Exception:  # client went away mid-send, or stalled
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self._clients.discard(ws)
            # Close them too, so the page's onclose fires and it reconnects instead of freezing.
            for ws in dead:
                asyncio.create_task(self._close_quietly(ws))

    @staticmethod
    async def _close_quietly(ws: WebSocket) -> None:
        try:
            await asyncio.wait_for(ws.close(code=1011), SEND_TIMEOUT_S)
        except Exception:  # already gone
            pass

    @property
    def count(self) -> int:
        return len(self._clients)
