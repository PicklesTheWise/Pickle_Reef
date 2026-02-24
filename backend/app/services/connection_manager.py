from __future__ import annotations

from typing import Any

from fastapi.websockets import WebSocket, WebSocketState


class ConnectionManager:
    """Track active module WebSocket connections for future commands."""

    def __init__(self) -> None:
        self._connections: dict[str, WebSocket] = {}

    def register(self, module_id: str, websocket: WebSocket) -> None:
        self._connections[module_id] = websocket

    def unregister(self, module_id: str) -> None:
        self._connections.pop(module_id, None)

    def is_connected(self, module_id: str) -> bool:
        websocket = self._connections.get(module_id)
        return bool(websocket and websocket.application_state == WebSocketState.CONNECTED)

    async def send(self, module_id: str, payload: dict[str, Any]) -> bool:
        websocket = self._connections.get(module_id)
        if websocket and websocket.application_state == WebSocketState.CONNECTED:
            await websocket.send_json(payload)
            return True
        return False


manager = ConnectionManager()
