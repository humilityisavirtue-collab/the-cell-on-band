"""Transport interface shared by offline tests and live Band SDK mode."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol


class BandTransportConfigError(RuntimeError):
    """Raised when a selectable Band transport cannot be configured."""


class BandTransportProtocol(Protocol):
    alive: bool

    def open_room(self, room_id: str) -> str | None:
        ...

    def recruit(self, role: str) -> None:
        ...

    def post(self, to_role: str, text: str) -> bool:
        ...

    def sever(self) -> None:
        ...


ROLE_UUID_ENV = {
    "coordinator": "BAND_AGENT_UUID_COORDINATOR",
    "structure": "BAND_AGENT_UUID_STRUCTURE",
    "pedagogy": "BAND_AGENT_UUID_PEDAGOGY",
    "brainstorm": "BAND_AGENT_UUID_BRAINSTORM",
    "visual": "BAND_AGENT_UUID_VISUAL_BUILDER",
    "verifier": "BAND_AGENT_UUID_VERIFIER",
}


@dataclass(frozen=True)
class BandTransportConfig:
    mode: str
    api_key: str
    rest_url: str
    ws_url: str
    agent_uuids: dict[str, str]

    @classmethod
    def from_env(cls, mode: str | None = None) -> "BandTransportConfig":
        selected = (mode or os.environ.get("BAND_TRANSPORT_MODE") or "test").lower()
        rest_url = os.environ.get(
            "BAND_API_URL", os.environ.get("BAND_REST_URL", "https://app.band.ai"))
        return cls(
            mode=selected,
            api_key=os.environ.get("BAND_API_KEY", ""),
            rest_url=_normalize_rest_url(rest_url),
            ws_url=os.environ.get(
                "BAND_WS_URL", "wss://app.band.ai/api/v1/socket/websocket"),
            agent_uuids={
                role: os.environ.get(env_name, "")
                for role, env_name in ROLE_UUID_ENV.items()
            },
        )

    @property
    def coordinator_agent_id(self) -> str:
        return self.agent_uuids.get("coordinator", "")

    def agent_identifier(self, role: str) -> str:
        return self.agent_uuids.get(role, "") or role

    def require_live_credentials(self) -> None:
        missing = []
        if not self.api_key:
            missing.append("BAND_API_KEY")
        if not self.coordinator_agent_id:
            missing.append("BAND_AGENT_UUID_COORDINATOR")
        if missing:
            raise BandTransportConfigError(
                "BAND_TRANSPORT_MODE=live requires %s." % ", ".join(missing))


def _normalize_rest_url(rest_url: str) -> str:
    """Accept older handoff URLs but pass the SDK its REST origin/base URL."""
    suffix = "/api/v1/agent"
    clean = (rest_url or "https://app.band.ai").rstrip("/")
    if clean.endswith(suffix):
        return clean[: -len(suffix)] or "https://app.band.ai"
    return clean
