"""Pod launcher: bring up the 4-agent loop on Band.

Spec: cell/specs/BAND_OF_AGENTS_SPEC.md. Nucleus opens the room, recruits
gamer/diamond/club via @mention (the verified add-agent-chat-participant
endpoint), then the loop runs conversationally — every handoff an @mention
carrying one envelope (adapter path (a): mention-triggered wake).

Honest status: this launcher is BUILT, not VERIFIED-RUNNABLE — it cannot
be until band-sdk installs at kickoff. It refuses loudly (exit nonzero)
rather than pretending; preflight() is the part that runs today and is
what Club can gate now.

Preflight (offline): py -3.12 apps/band/run_pod.py --preflight
Live (post-kickoff):  py -3.12 apps/band/run_pod.py --task "the demo ask"
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

import asyncio  # noqa: E402

from band_agent import (  # noqa: E402
    LOOP_ROLES, BandCellAgent, load_agent_config, load_env,
)


def preflight(verbose=True):
    """Everything checkable before the SDK exists. Returns problem list —
    empty means GO. Asserts nothing it didn't observe."""
    problems = []

    env = load_env()
    for key in ("THENVOI_REST_URL", "THENVOI_WS_URL"):
        if not env.get(key):
            problems.append(".env missing %s" % key)

    for role in LOOP_ROLES:
        try:
            load_agent_config(role)
        except Exception as e:
            problems.append("config[%s]: %s" % (role, e))

    try:
        import band_sdk  # noqa: F401
    except ImportError:
        problems.append('band-sdk not installed '
                        '(py -3.12 -m pip install "band-sdk[claude_sdk]")')

    if verbose:
        print("run_pod preflight:")
        if problems:
            for p in problems:
                print("  [BLOCKED] %s" % p)
        else:
            print("  [GO] env + 4 role configs + SDK all present")
    return problems


async def _run_pod(agents):
    """Run all 4 cell agents concurrently on Band."""
    await asyncio.gather(*(a.run() for a in agents))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", help="the demo ask gamer will decompose")
    parser.add_argument("--room", default="the-cell-on-band")
    parser.add_argument("--preflight", action="store_true",
                        help="check readiness and exit (offline-safe)")
    args = parser.parse_args()

    problems = preflight()
    if args.preflight:
        sys.exit(1 if problems else 0)
    if problems:
        print("refusing to launch with %d preflight problems" % len(problems))
        sys.exit(1)

    agents = [BandCellAgent(role) for role in LOOP_ROLES]
    print("launching pod: %s" % ", ".join(LOOP_ROLES))
    print("add all 4 agents to room '%s' on app.band.ai, then @gamer to kick off"
          % args.room)
    asyncio.run(_run_pod(agents))


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    main()
