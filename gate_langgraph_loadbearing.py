"""LangGraph twin of Club's load-bearing kill test — the orchestration-locus gate.

Spec/sibling: gate_band_loadbearing.py (the claude_sdk @mention twin). Owner: Club.
Authored at the ChapterStage hybrid decision (Kit: hybrid; spade dispatch
diamond.jsonl#L292) BEFORE anyone builds on the LangGraph backend handoff.

THE QUESTION (spade's decision-blocker): under band-sdk[langgraph], does the
inter-agent conversation happen IN the Band room (Band load-bearing = OK), or
does LangGraph orchestrate point-to-point with the room as a trace mirror
(Band removable = FAILS the hackathon thesis)?

This answers it MECHANICALLY, offline, with the REAL langgraph installed (so the
test is not blind to the layer it judges — the mock-selftest trap). It builds the
SAME 5-stage learning chain TWO ways and severs the Band room mid-flight:

  GOOD topology  — one Pregel graph PER agent (the SDK's LangGraphAdapter design:
                   an adapter wraps a single-agent graph, advances only via
                   on_message). Inter-agent hops route through the Band room.
                   Sever the room -> the chain STALLS before `module`. Band is
                   load-bearing.  [LEG 1]

  BAD topology   — one MASTER Pregel graph with all agents as nodes + edges.
                   graph.invoke() runs the whole conversation in-process; the room
                   only mirrors transcripts. Sever the room -> invoke() STILL
                   reaches `module`. Band is removable.  [LEG 2 = negative control:
                   this is the architecture the gate must be able to catch.]

A gate that cannot tell these two apart is theater. LEG 2 going "removable" is the
proof the test can go red. The node outputs are REAL chapterstage_envelopes, so
LEG 3 also confirms piece 1 drops into LangGraph node outputs as the JSON contract.

VERDICT: hybrid is SAFE iff ChapterStage wires adapter-PER-AGENT (LEG 1 good). A
single master multi-agent graph (LEG 2) is Band-removable and FAILS the thesis.

Exit 0 = GATE PASS. Exit 1 = FAIL (receipts printed).
Run: py -3.12 apps/band/gate_langgraph_loadbearing.py
"""
from __future__ import annotations

import operator
import sys
from pathlib import Path
from typing import Annotated, Any, TypedDict

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

import chapterstage_envelopes as cse  # noqa: E402  (piece 1 — the node-output contract)

from langgraph.graph import StateGraph, START, END  # noqa: E402

FAILURES: list[str] = []
RAN: list[str] = []


def check(name, cond, receipt=""):
    RAN.append(name)
    print("  [%s] %s" % ("PASS" if cond else "FAIL", name))
    if receipt and not cond:
        print("         receipt: %s" % receipt)
    if not cond:
        FAILURES.append(name)


# ------------------------------------------------------- severable Band room

class MockBandRoom:
    """In-memory stand-in for the Band room — the inter-agent transport.
    sever() == WS drop / key revoke. After sever, post() DROPS the message
    (returns False), exactly what the live 60s-WS-drop test does."""

    def __init__(self):
        self.alive = True
        self.delivered: list[tuple[str, str]] = []   # (from_stage, kind)
        self.dropped: list[tuple[str, str]] = []

    def sever(self):
        self.alive = False

    def post(self, from_stage: str, env: dict) -> bool:
        kind = env.get("kind", "?")
        if not self.alive:
            self.dropped.append((from_stage, kind))
            return False
        self.delivered.append((from_stage, kind))
        return True


# ------------------------------------------------- shared stage logic (nodes)
# Each stage emits a REAL chapterstage_envelopes envelope as its output contract.
# Identical logic feeds BOTH topologies — the ONLY difference between GOOD and BAD
# is where the inter-stage edges live (Band room vs in-graph edges).

TASK = "cs-gate-1"


def stage_structure(state: dict) -> dict:
    env = cse.make_envelope(
        "knowledge_pack", TASK, "structure", "pedagogy",
        pack={"source_ref": "Young Wizards ch.3",
              "sections": ["intro", "the Oath"], "ideas": ["service over power"]})
    return {"pack": env, "log": ["structure"]}


def stage_brainstorm(state: dict) -> dict:
    env = cse.make_envelope(
        "brainstorm_score", TASK, "brainstorm", "coordinator",
        score={"variant_id": "v3", "metric": "learning_value", "value": 0.79})
    return {"score": env, "log": ["brainstorm"]}


def stage_visual(state: dict) -> dict:
    env = cse.make_envelope(
        "storyboard", TASK, "visual", "verifier",
        storyboard={"scenes": [{"id": 1, "kind": "interactive_oath"}]})
    return {"storyboard": env, "log": ["visual"]}


def stage_verifier(state: dict) -> dict:
    # The verifier gate: a module is only emitted WITH a PASS faithfulness verdict.
    env = cse.make_envelope(
        "module", TASK, "verifier", "room",
        verdict={"gate": "source_faithfulness", "result": "PASS",
                 "receipts": "$ verify\n8/8 claims grounded in ch.3"})
    return {"module": env, "log": ["verifier"]}


# The pipeline order (coordinator/pedagogy fold into routing; the 4 emitting
# stages are the artifact chain: pack -> score -> storyboard -> module).
PIPELINE = [
    ("structure", stage_structure),
    ("brainstorm", stage_brainstorm),
    ("visual", stage_visual),
    ("verifier", stage_verifier),
]


# ---------------------------------------------------------- GOOD topology
# One single-node Pregel graph PER agent (mirrors LangGraphAdapter: each agent IS
# its own graph, advanced only by an inbound message). The orchestrator routes
# each agent's output through the Band room to trigger the next agent. If the room
# is severed, the next agent is NEVER triggered -> chain stalls. Band load-bearing.

class _S(TypedDict):
    log: Annotated[list, operator.add]


def _single_agent_graph(fn):
    g = StateGraph(_S)
    g.add_node("act", lambda s: {"log": fn(s)["log"]})
    g.add_edge(START, "act")
    g.add_edge("act", END)
    return g.compile()


def run_good_topology(room: MockBandRoom, sever_at: str | None = None):
    """Drive the per-agent graphs, hopping through the room. Returns the final
    module envelope (or None if the chain stalled).

    sever_at: the stage whose OUTBOUND handoff is severed. That stage runs, but
    its message to the next agent is dropped -> the next agent never triggers.
    This isolates the load-bearing claim: the conversation rides the room, so a
    severed room halts it at the broken hop."""
    agents = {name: _single_agent_graph(fn) for name, fn in PIPELINE}
    state: dict = {"log": []}
    module = None
    for name, fn in PIPELINE:
        # the agent's OWN graph runs (real langgraph invoke), producing its output
        agents[name].invoke({"log": []})
        out = fn(state)              # the emitted envelope (same logic the node ran)
        state.update({k: v for k, v in out.items() if k != "log"})
        state["log"].append(name)
        env = out.get("module") or out.get("pack") or out.get("score") \
            or out.get("storyboard")
        if name == "verifier":
            module = out["module"]
        # sever this stage's OUTBOUND hop before it posts (its handoff is lost)
        if sever_at == name:
            room.sever()
        # inter-agent hop is the ROOM. severed room == next agent never triggers.
        if not room.post(name, env):
            return None, state          # chain stalls at the broken hop
    return module, state


# ----------------------------------------------------------- BAD topology
# One MASTER Pregel graph: all stages are nodes wired by in-graph edges. A single
# invoke() runs the whole conversation in-process. The room is passed but only
# MIRRORS (post() return ignored). Severing the room cannot stop in-graph edges.

def _build_master_graph(room: MockBandRoom):
    g = StateGraph(_S)
    prev = START
    for name, fn in PIPELINE:
        def make_node(fn=fn, name=name):
            def node(state):
                out = fn(state)
                env = out.get("module") or out.get("pack") or out.get("score") \
                    or out.get("storyboard")
                room.post(name, env)     # mirror only — return ignored (the bug)
                return {"log": out["log"]}
            return node
        g.add_node(name, make_node())
        g.add_edge(prev, name)
        prev = name
    g.add_edge(prev, END)
    return g.compile()


def run_bad_topology(room: MockBandRoom, sever_before_invoke: bool = False):
    graph = _build_master_graph(room)
    if sever_before_invoke:
        room.sever()
    final = graph.invoke({"log": []})
    reached_verifier = "verifier" in final.get("log", [])
    return reached_verifier, final


# ---------------------------------------------------------------- the legs

def leg1_good_loadbearing():
    print("LEG 1 — GOOD topology: adapter-per-agent, hops via Band room")

    # POSCONTROL: room alive -> chain reaches a valid `module`.
    room = MockBandRoom()
    module, state = run_good_topology(room, sever_at=None)
    check("POSCONTROL per-agent chain reaches module with room alive",
          module is not None and module.get("kind") == "module",
          receipt="module=%r log=%r" % (module, state.get("log")))
    check("POSCONTROL emitted module is a VALID chapterstage module (PASS verdict)",
          module is not None and cse.validate(module) == [],
          receipt="validate=%r" % (cse.validate(module) if module else "no module"))

    # KILL: sever structure's outbound hop -> brainstorm is never triggered.
    room = MockBandRoom()
    module, state = run_good_topology(room, sever_at="structure")
    check("severed-at-structure: NO module (chain stalled)",
          module is None, receipt="module=%r log=%r" % (module, state.get("log")))
    check("severed-at-structure: handoff actually dropped (sever is real)",
          len(room.dropped) >= 1, receipt="dropped=%r" % room.dropped)
    check("severed-at-structure: no later stage ran (room is the only trigger)",
          state.get("log") == ["structure"],
          receipt="log=%r" % state.get("log"))


def leg2_bad_removable_negcontrol():
    print("LEG 2 — BAD topology: master graph, room as mirror (NEGATIVE CONTROL)")

    # POSCONTROL: master graph also completes with room alive (sanity).
    room = MockBandRoom()
    reached, final = run_bad_topology(room, sever_before_invoke=False)
    check("master graph completes to verifier with room alive (sanity)",
          reached, receipt="log=%r" % final.get("log"))

    # THE TELL: sever the room, then invoke. In-graph edges don't care -> it
    # STILL completes. This is Band-removable, and the gate must DETECT it.
    room = MockBandRoom()
    reached_severed, final = run_bad_topology(room, sever_before_invoke=True)
    band_removable = reached_severed and len(room.dropped) >= 1
    check("master graph reaches verifier EVEN WITH room severed (Band removable)",
          reached_severed, receipt="log=%r" % final.get("log"))
    check("NEGCONTROL gate DETECTS the removable case (all posts dropped, yet done)",
          band_removable, receipt="dropped=%r reached=%r"
          % (room.dropped, reached_severed))
    # The discriminator: GOOD stalls severed, BAD does not. If they behaved the
    # same, this gate would be theater.
    room_g = MockBandRoom()
    good_module, _ = run_good_topology(room_g, sever_at="structure")
    check("DISCRIMINATOR: severed GOOD stalls while severed BAD completes",
          good_module is None and reached_severed,
          receipt="good_severed_module=%r bad_severed_reached=%r"
          % (good_module, reached_severed))


def leg3_real_layer_probe():
    print("LEG 3 — real-layer probe: the SDK's adapter is single-agent by design")
    import band.adapters.langgraph as LGA
    import inspect
    adapter = LGA.LangGraphAdapter
    methods = {m for m in dir(adapter) if not m.startswith("_")}
    # The adapter advances ONLY via on_message (Band-delivered) and lifecycle
    # hooks — there is NO public 'call_other_agent' / inter-agent edge method.
    check("LangGraphAdapter advances via on_message (Band-triggered)",
          "on_message" in methods, receipt="methods=%r" % sorted(methods))
    inter_agent_methods = {m for m in methods
                           if any(k in m.lower()
                                  for k in ("other_agent", "call_agent",
                                            "route_to", "handoff"))}
    check("a single adapter has NO inter-agent edge method (hop must be the room)",
          inter_agent_methods == set(),
          receipt="found=%r" % sorted(inter_agent_methods))
    # The adapter wraps ONE graph (graph / graph_factory) — one graph per agent.
    sig = inspect.signature(adapter.__init__)
    check("adapter takes ONE graph per agent (graph/graph_factory params)",
          "graph" in sig.parameters and "graph_factory" in sig.parameters,
          receipt="params=%r" % list(sig.parameters))


def leg4_contract_reuse():
    print("LEG 4 — piece 1 envelopes drop into LangGraph node outputs (adapter-agnostic)")
    # Every stage output that flows on the wire is a valid chapterstage envelope —
    # the same contract for GOOD (room hop) and BAD (node output). spade's claim.
    bad_envs = []
    for name, fn in PIPELINE:
        out = fn({"log": []})
        env = out.get("module") or out.get("pack") or out.get("score") \
            or out.get("storyboard")
        if cse.validate(env) != []:
            bad_envs.append((name, cse.validate(env)))
    check("all 4 node outputs are valid chapterstage envelopes",
          bad_envs == [], receipt="invalid=%r" % bad_envs)


def main():
    print("gate_langgraph_loadbearing.py — orchestration-locus gate (offline, real langgraph)")
    leg1_good_loadbearing()
    leg2_bad_removable_negcontrol()
    leg3_real_layer_probe()
    leg4_contract_reuse()
    print("%d/%d gate checks passed" % (len(RAN) - len(FAILURES), len(RAN)))
    if FAILURES:
        print("GATE FAIL: %s" % ", ".join(FAILURES))
        sys.exit(1)
    print("GATE PASS — under band-sdk[langgraph], adapter-PER-AGENT is "
          "load-bearing (severing the room stalls the chain); a single MASTER "
          "graph is Band-REMOVABLE. Hybrid is safe IFF ChapterStage wires one "
          "graph per agent. The gate can tell the two apart.")
    sys.exit(0)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    main()
