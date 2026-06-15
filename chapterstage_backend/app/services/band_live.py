"""band_live.py — the REAL Band transport for ChapterStage handoffs.

Plugs into band_service.BandService(transport=...). When the runner sets
CHAPTERSTAGE_BAND_LIVE=1, each stage handoff (structure->brainstorm->visual->
verifier->room) is posted as an @mention message into a live Band room over the
agent REST API — so the handoffs genuinely RIDE Band, not an in-memory twin.
This is the spec's load-bearing claim made real: sever the room (or revoke the
key) and post() returns False, so band_service stalls the job (no module, no URL).

Verified call sequence (live, 2026-06-15): create_agent_chat() (no task_id ->
standalone room) -> add_agent_chat_participant() per agent -> create_agent_chat_
message(content, mentions=[{id}]) returns success=True with the recipient.

Credentials load from apps/band/.env (the 4 agents Kit created: gamer/diamond/
spade/nucleus). The 4 ChapterStage stage roles map onto those 4 agents as the
visible room participants. Posts go out as one orchestrator agent (gamer) that
@mentions the next role each hop — band_service.post(to_role, text) only carries
the target, so the poster is fixed; real multi-author posting is a follow-up that
needs from_role threaded through band_service.

Sync (RestClient): band_service runs in the runner's worker thread, no event loop.
"""
from __future__ import annotations

import re
from pathlib import Path

_BAND_ENV = Path("C:/kit.triv/apps/band/.env")
BASE_URL = "https://app.band.ai"

# ChapterStage stage role -> the Band agent that represents it in the room.
ROLE_MAP = {
    "structure": "gamer",
    "brainstorm": "diamond",
    "visual": "spade",
    "verifier": "nucleus",
    "coordinator": "nucleus",
}
POSTER_ROLE = "gamer"   # the agent whose key posts each handoff message


def load_band_agents(path: Path = _BAND_ENV) -> dict:
    """Parse apps/band/.env's custom block into {role: {id, api, handle}}.
    Lines look like:  Gamer = <uuid> / gamer_api = <key> / gamer_handle = @..."""
    agents: dict[str, dict] = {}
    if not path.exists():
        return agents
    id_re = re.compile(r"^([A-Za-z]+)\s*=\s*([0-9a-fA-F-]{36})\s*$")
    api_re = re.compile(r"^([A-Za-z]+)_api\s*=\s*(\S+)\s*$")
    handle_re = re.compile(r"^([A-Za-z]+)_handle\s*=\s*(\S+)\s*$")
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = api_re.match(line)
        if m:
            agents.setdefault(m.group(1).lower(), {})["api"] = m.group(2)
            continue
        m = handle_re.match(line)
        if m:
            agents.setdefault(m.group(1).lower(), {})["handle"] = m.group(2)
            continue
        m = id_re.match(line)
        if m:
            agents.setdefault(m.group(1).lower(), {})["id"] = m.group(2)
    return agents


class BandRoomTransport:
    """band_service transport over the live Band agent REST API."""

    def __init__(self, agents: dict | None = None):
        self.agents = agents or load_band_agents()
        self.alive = True
        self.chat_id: str | None = None
        self._client = None
        self._msg_types = None

    # ---- lazy SDK wiring (kept out of import so offline gates never load it) --
    def _connect(self):
        if self._client is not None:
            return
        from band.client.rest import (RestClient, ChatRoomRequest,
                                       ChatMessageRequest,
                                       ChatMessageRequestMentionsItem,
                                       ParticipantRequest)
        poster = self.agents.get(POSTER_ROLE)
        if not poster or "api" not in poster:
            raise RuntimeError("no %s api key in apps/band/.env" % POSTER_ROLE)
        self._client = RestClient(base_url=BASE_URL, api_key=poster["api"], timeout=30)
        self._msg_types = (ChatRoomRequest, ChatMessageRequest,
                           ChatMessageRequestMentionsItem, ParticipantRequest)

    def _agent_id(self, role: str) -> str | None:
        band_role = ROLE_MAP.get(role, role)
        return (self.agents.get(band_role) or {}).get("id")

    # ---- band_service transport interface ----
    def open_room(self, _label: str) -> None:
        """Create a real standalone Band room and add the 4 agents. The synthetic
        label band_service passes is ignored — Band assigns the room id."""
        self._connect()
        ChatRoomRequest = self._msg_types[0]
        ParticipantRequest = self._msg_types[3]
        room = self._client.agent_api_chats.create_agent_chat(chat=ChatRoomRequest())
        self.chat_id = room.data.id
        for role in ("diamond", "spade", "nucleus"):   # gamer is the poster/owner
            agent = self.agents.get(role)
            if agent and "id" in agent:
                try:
                    self._client.agent_api_participants.add_agent_chat_participant(
                        self.chat_id,
                        participant=ParticipantRequest(participant_id=agent["id"],
                                                       role="member"))
                except Exception:
                    pass   # already a member / transient — not fatal to the room

    def recruit(self, _role: str) -> None:
        pass   # participants are added in open_room

    def post(self, to_role: str, text: str) -> bool:
        """Post the handoff as an @mention. Returns False on any failure so
        band_service records a drop and the loop stalls (the load-bearing test)."""
        if not self.alive or self.chat_id is None:
            return False
        try:
            ChatMessageRequest = self._msg_types[1]
            MentionItem = self._msg_types[2]
            mentions = []
            if to_role in ("room", "broadcast"):
                # the final module is a room broadcast — the Band API requires at
                # least one mention AND rejects mentioning the poster itself (both
                # learned live 2026-06-15: empty list AND self-mention each 422),
                # so address every participant EXCEPT the poster.
                for role in ("gamer", "diamond", "spade", "nucleus"):
                    if role == POSTER_ROLE:
                        continue
                    a = self.agents.get(role)
                    if a and "id" in a:
                        mentions.append(MentionItem(id=a["id"], name=role))
            else:
                agent_id = self._agent_id(to_role)
                if agent_id:
                    mentions.append(MentionItem(id=agent_id, name=to_role))
            resp = self._client.agent_api_messages.create_agent_chat_message(
                self.chat_id,
                message=ChatMessageRequest(content=text, mentions=mentions))
            return bool(getattr(resp.data, "success", True))
        except Exception:
            return False

    def sever(self) -> None:
        self.alive = False
