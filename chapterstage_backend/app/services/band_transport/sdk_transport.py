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
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread: threading.Thread | None = None

    def open_room(self, room_id: str) -> str:
        async def _open() -> str:
            tools = self._agent_tools_cls("__chapterstage_bootstrap__", self.link.rest)
            return await tools.create_chatroom()

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
        try:
            self._run(self.link.disconnect())
        finally:
            self.alive = False
            self.close()

    def sever(self) -> None:
        self.alive = False
        try:
            if getattr(self.link, "is_connected", False):
                self.disconnect()
            else:
                self.close()
        except Exception as exc:
            self.last_error = str(exc)
            self.close()

    def close(self) -> None:
        loop = self._loop
        thread = self._loop_thread
        if loop is None:
            return
        if loop.is_running():
            loop.call_soon_threadsafe(loop.stop)
        if thread is not None and thread.is_alive():
            thread.join(timeout=5)
        self._loop = None
        self._loop_thread = None

    def _room_tools(self):
        if not self.room_id:
            raise BandTransportConfigError("No Band room has been opened.")
        return self._agent_tools_cls(
            self.room_id, self.link.rest, participants=self.participants)

    def _run(self, awaitable: Awaitable[Any]) -> Any:
        loop = self._ensure_loop()
        future = asyncio.run_coroutine_threadsafe(awaitable, loop)
        return future.result()

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        loop = getattr(self, "_loop", None)
        if loop is not None and loop.is_running():
            return loop

        ready = threading.Event()
        loop = asyncio.new_event_loop()

        def runner() -> None:
            asyncio.set_event_loop(loop)
            ready.set()
            loop.run_forever()
            loop.close()

        thread = threading.Thread(
            target=runner, name="BandSdkTransportLoop", daemon=True)
        self._loop = loop
        self._loop_thread = thread
        thread.start()
        ready.wait(timeout=5)
        return loop


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
