"""
WebSocket endpoint for real-time chat streaming.

Protocol:
  1. Client connects to ``ws://host/ws/chat/{session_id}``.
  2. Client sends JSON: ``{"type": "message", "content": "..."}``
  3. Server streams back events:
       {"type": "token",       "data": "partial text"}
       {"type": "tool_start",  "data": {"tool_name": "..."}}
       {"type": "tool_result", "data": {"tool_name": "...", "success": true}}
       {"type": "done",        "data": {"elapsed_ms": 1234}}
       {"type": "error",       "data": "error message"}
  4. Client can send ``{"type": "ping"}`` → server replies ``{"type": "pong"}``.
  5. Connection closes on client disconnect or server error.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from app.services.intelligence.agent import ConversationMessage, MolChatAgent

logger = structlog.get_logger(__name__)

router = APIRouter()

# Track active connections for monitoring
_active_connections: dict[str, WebSocket] = {}


@router.websocket("/ws/chat/{session_id}")
async def websocket_chat(websocket: WebSocket, session_id: str) -> None:
    """WebSocket endpoint for real-time chat."""
    await websocket.accept()

    connection_id = str(uuid.uuid4())[:8]
    _active_connections[connection_id] = websocket

    log = logger.bind(
        session_id=session_id,
        connection_id=connection_id,
    )
    log.info("ws_connected")

    agent = MolChatAgent()
    history: list[ConversationMessage] = []

    try:
        session_uuid: uuid.UUID | None = None
        try:
            session_uuid = uuid.UUID(session_id)
        except ValueError:
            session_uuid = uuid.uuid4()

        while True:
            # ── Receive message ──
            raw = await websocket.receive_text()

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await _send_json(websocket, {
                    "type": "error",
                    "data": "Invalid JSON",
                })
                continue

            msg_type = msg.get("type", "message")

            # ── Ping/pong ──
            if msg_type == "ping":
                await _send_json(websocket, {"type": "pong"})
                continue

            # ── Chat message ──
            if msg_type == "message":
                content = msg.get("content", "").strip()
                if not content:
                    await _send_json(websocket, {
                        "type": "error",
                        "data": "Empty message",
                    })
                    continue

                context = msg.get("context")

                log.info("ws_message_received", content_preview=content[:80])

                # Add user message to history
                history.append(
                    ConversationMessage(role="user", content=content)
                )

                # Stream response
                full_response = ""
                async for event in agent.chat_stream(
                    user_message=content,
                    history=history,
                    session_id=session_uuid,
                    context=context,
                ):
                    if websocket.client_state != WebSocketState.CONNECTED:
                        break

                    event_type = event.get("type", "token")

                    if event_type == "token":
                        full_response += event.get("data", "")

                    await _send_json(websocket, event)

                # Add assistant response to history
                if full_response:
                    history.append(
                        ConversationMessage(role="assistant", content=full_response)
                    )

                # Trim history to prevent memory growth
                if len(history) > 40:
                    history = history[-40:]

                continue

            # ── Unknown type ──
            await _send_json(websocket, {
                "type": "error",
                "data": f"Unknown message type: {msg_type}",
            })

    except WebSocketDisconnect:
        log.info("ws_disconnected")

    except Exception as exc:
        log.error("ws_error", error=str(exc))
        try:
            if websocket.client_state == WebSocketState.CONNECTED:
                await _send_json(websocket, {
                    "type": "error",
                    "data": "Internal server error",
                })
        except Exception:
            pass

    finally:
        _active_connections.pop(connection_id, None)
        log.info("ws_cleanup", active_connections=len(_active_connections))


async def _send_json(websocket: WebSocket, data: dict[str, Any]) -> None:
    """Safe JSON send that handles connection state."""
    try:
        if websocket.client_state == WebSocketState.CONNECTED:
            await websocket.send_text(
                json.dumps(data, ensure_ascii=False, default=str)
            )
    except Exception:
        pass


# ═══════════════════════════════════════════════
# Connection monitoring (used by health endpoint)
# ═══════════════════════════════════════════════


def get_active_connections_count() -> int:
    """Return the number of active WebSocket connections."""
    return len(_active_connections)