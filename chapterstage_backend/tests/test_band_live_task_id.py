"""Regression gate for Band live chatroom creation."""
from __future__ import annotations

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

from app.services.band_transport.sdk_transport import BandSdkTransport  # noqa: E402


def check(name, cond, receipt=""):
    print("  [%s] %s" % ("PASS" if cond else "FAIL", name))
    if not cond:
        if receipt:
            print("         receipt: %s" % receipt)
        raise SystemExit(1)


class FakeAgentTools:
    calls = []

    def __init__(self, room_id, rest, participants=None):
        self.room_id = room_id
        self.rest = rest
        self.participants = participants or []

    async def create_chatroom(self, task_id=None):
        self.calls.append(task_id)
        return "band-room-1"

    async def add_participant(self, identifier):
        self.calls.append(("add", identifier))
        return {"id": identifier, "name": identifier, "handle": identifier}

    async def get_participants(self):
        self.calls.append("participants")
        return []

    async def send_message(self, content, mentions=None):
        self.calls.append(("send", content, mentions))
        return {"id": "message-1"}


def main():
    print("test_band_live_task_id.py - Band live chatroom creation")
    tx = BandSdkTransport.__new__(BandSdkTransport)
    tx._agent_tools_cls = FakeAgentTools
    tx.config = type("Config", (), {
        "agent_identifier": lambda _self, role: "agent-%s" % role,
    })()
    tx.link = type("Link", (), {"rest": object()})()
    tx.rooms = []
    tx.recruited = []
    tx.participants = []
    tx.posts = []
    tx.room_id = None
    tx.alive = True
    tx.last_error = None
    tx._loop = None
    tx._loop_thread = None

    room_id = tx.open_room("room-19208c32-91bf-4dd9-b690-2288ab692e0f")
    first_loop = tx._loop
    tx.recruit("structure")
    posted = tx.post("brainstorm", "@brainstorm\nknowledge envelope")
    check("live transport creates an unbound Band chatroom",
          room_id == "band-room-1" and FakeAgentTools.calls[0] is None,
          receipt={"room_id": room_id, "calls": FakeAgentTools.calls})
    check("live transport reuses one event loop across Band calls",
          first_loop is tx._loop
          and FakeAgentTools.calls[:2] == [None, ("add", "agent-structure")],
          receipt=FakeAgentTools.calls)
    check("live transport mentions actual target agents",
          posted
          and FakeAgentTools.calls[-1]
          == ("send", "@brainstorm\nknowledge envelope", ["agent-brainstorm"]),
          receipt=FakeAgentTools.calls)
    tx.close()
    check("live transport closes its background event loop",
          tx._loop is None and tx._loop_thread is None)
    print("GATE PASS - live Band transport avoids closed-loop reuse.")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    main()
