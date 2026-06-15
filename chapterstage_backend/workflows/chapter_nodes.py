"""nodes.py — per-stage agent nodes (M3: stubbed outputs, real envelope contract).

Each node IS a per-agent LangGraph (the invariant: LangGraph per-agent internal
only). A node runs its own tiny graph, then emits a chapterstage_envelopes
envelope as its output. Nodes NEVER call each other — chapter_graph routes their
outputs through band_service. M5 swaps the stub bodies for real agent work; the
output contract (chapterstage_envelopes.validate) does not change.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated, TypedDict
import operator

# chapterstage_envelopes lives in apps/band (two levels up) — the node-output contract
_BAND = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_BAND))
import chapterstage_envelopes as cse  # noqa: E402

from langgraph.graph import StateGraph, START, END  # noqa: E402
from app.services import chapter_agents  # noqa: E402


class _AgentS(TypedDict):
    log: Annotated[list, operator.add]


def _per_agent_graph(role: str):
    """One trivial Pregel graph per agent — stands in for the agent's internal
    reasoning. The point is structural: each agent advances its OWN graph; the
    inter-agent edge is NOT here, it's band_service."""
    g = StateGraph(_AgentS)
    g.add_node("think", lambda s: {"log": [role]})
    g.add_edge(START, "think")
    g.add_edge("think", END)
    return g.compile()


def structure_node(state: dict) -> dict:
    _per_agent_graph("structure").invoke({"log": []})
    return cse.make_envelope(
        "knowledge_pack", state["job_id"], "structure", "pedagogy",
        pack=chapter_agents.build_structure_pack(state))


def brainstorm_node(state: dict) -> dict:
    _per_agent_graph("brainstorm").invoke({"log": []})
    return cse.make_envelope(
        "brainstorm_score", state["job_id"], "brainstorm", "coordinator",
        score=chapter_agents.build_brainstorm_score(state))


def visual_node(state: dict) -> dict:
    _per_agent_graph("visual").invoke({"log": []})
    return cse.make_envelope(
        "storyboard", state["job_id"], "visual", "verifier",
        storyboard=chapter_agents.build_storyboard(state))


def verifier_node(state: dict) -> dict:
    _per_agent_graph("verifier").invoke({"log": []})
    return cse.make_envelope(
        "module", state["job_id"], "verifier", "room",
        verdict=chapter_agents.build_verifier_verdict(state))


# (from_role, slot, node_fn, to_role) — the artifact chain. to_role is who the
# output is @mentioned to; chapter_graph routes it THROUGH band_service.
STAGES = [
    ("structure", "pack", structure_node, "brainstorm"),
    ("brainstorm", "score", brainstorm_node, "visual"),
    ("visual", "storyboard", visual_node, "verifier"),
    ("verifier", "module", verifier_node, "room"),
]
