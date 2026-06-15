"""Live Band SDK transport.

This module is imported only for BAND_TRANSPORT_MODE=live. Test/default mode
must never import the Band SDK, which keeps local gates deterministic and avoids
accidental network calls.
"""
from __future__ import annotations

import asyncio
import threading
from typing import Any, Awaitable

from .base import BandTransportConfig, BandTransportConfigError


class BandSdkTransport:
    """Sync adapter around the Band SDK's async REST/WebSocket primitives."""

    def __init__(self, config: BandTransportConfig | None = None):
        self.config = config or BandTransportConfig.from_env("live")
        self.config.require_live_credentials()
        try:
            from band import AgentTools, BandLink  # type: ignore
        except ImportError as exc:
            raise BandTransportConfigError(
                'Band SDK is not installed. Install "band-sdk[langgraph]" '
                "before using BAND_TRANSPORT_MODE=live.") from exc

        self._agent_tools_cls = AgentTools
        self.link = BandLink(
            agent_id=self.config.coordinator_agent_id,
            api_key=self.config.api_key,
            ws_url=self.config.ws_url,
            rest_url=self.config.rest_url,
        )
        self.alive = True
        self.room_id: str | None = None
        self.rooms: list[str] = []
        self.recruited: list[str] = []
        self.posts: list[tuple[str, str]] = []
        self.participants: list[dict[str, Any]] = []
        self.last_error: str | None = None

    def open_room(self, room_id: str) -> str:
        async def _open() -> str:
            tools = self._agent_tools_cls("__chapterstage_bootstrap__", self.link.rest)
            return await tools.create_chatroom(task_id=room_id)

        self.room_id = self._run(_open())
        self.rooms.append(self.room_id)
        return self.room_id

    def recruit(self, role: str) -> None:
        if not self.room_id:
            raise BandTransportConfigError("Cannot recruit before open_room().")
        identifier = self.config.agent_identifier(role)

        async def _recruit() -> None:
            tools = self._room_tools()
            result = await tools.add_participant(identifier)
            self.participants = tools.participants
            if isinstance(result, dict) and result.get("id"):
                _merge_participant(self.participants, result)

        self._run(_recruit())
        self.recruited.append(role)

    def post(self, to_role: str, text: str) -> bool:
        if not self.alive or not self.room_id:
            return False
        mention = self.config.agent_identifier(to_role)

        async def _post() -> None:
            tools = self._room_tools()
            try:
                await tools.get_participants()
            except Exception:
                # A fresh participant snapshot is helpful, not required. Sending
                # still gets a chance using the participant cache built by recruit().
                pass
            self.participants = tools.participants
            await tools.send_message(text, mentions=[mention])

        try:
            self._run(_post())
        except Exception as exc:
            self.last_error = str(exc)
            return False
        self.posts.append((to_role, text))
        return True

    def connect(self) -> None:
        self._run(self.link.connect())
        self.alive = True

    def disconnect(self) -> None:
        self._run(self.link.disconnect())
        self.alive = False

    def sever(self) -> None:
        self.alive = False
        try:
            if getattr(self.link, "is_connected", False):
                self.disconnect()
        except Exception as exc:
            self.last_error = str(exc)

    def _room_tools(self):
        if not self.room_id:
            raise BandTransportConfigError("No Band room has been opened.")
        return self._agent_tools_cls(
            self.room_id, self.link.rest, participants=self.participants)

    @staticmethod
    def _run(awaitable: Awaitable[Any]) -> Any:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(awaitable)

        result: dict[str, Any] = {}

        def runner() -> None:
            try:
                result["value"] = asyncio.run(awaitable)
            except BaseException as exc:
                result["error"] = exc

        thread = threading.Thread(target=runner, daemon=True)
        thread.start()
        thread.join()
        if "error" in result:
            raise result["error"]
        return result.get("value")


def _merge_participant(participants: list[dict[str, Any]], result: dict[str, Any]) -> None:
    pid = result.get("id")
    if not pid or any(p.get("id") == pid for p in participants):
        return
    participants.append({
        "id": pid,
        "name": result.get("name") or pid,
        "handle": result.get("handle") or pid,
        "type": "Agent",
    })
