"""Deterministic no-network Band transport used by tests and local logic."""
from __future__ import annotations


class TestBandTransport:
    """In-memory stand-in for the Band room transport.

    It records the same observable facts the load-bearing gates care about:
    opened rooms, recruited roles, and posted @mentions. `sever()` makes future
    posts fail, matching the live failure mode without touching the network.
    """

    def __init__(self):
        self.alive = True
        self.room_id: str | None = None
        self.rooms: list[str] = []
        self.recruited: list[str] = []
        self.posts: list[tuple[str, str]] = []

    def open_room(self, room_id: str) -> str:
        self.room_id = room_id
        self.rooms.append(room_id)
        return room_id

    def recruit(self, role: str) -> None:
        self.recruited.append(role)

    def post(self, to_role: str, text: str) -> bool:
        if not self.alive:
            return False
        self.posts.append((to_role, text))
        return True

    def sever(self) -> None:
        self.alive = False
