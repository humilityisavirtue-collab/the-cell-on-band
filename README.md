# The Cell, on Band

A 4-agent software-delivery loop running on [Band](https://www.band.ai/) as
the load-bearing coordination transport. Built for the Band of Agents
Hackathon (lablab.ai, June 12–19 2026), Track 2: multi-agent software
development.

**Disclosure:** the K-Cell framework pre-exists this hackathon (months of
prior work, in a private monorepo). Everything Band-specific — adapters,
room workflows, the demo — is built during the event window.

## The loop

| Band role | Cell role | Job on Band |
|-----------|-----------|-------------|
| Planner | Gamer | decomposes the ask → posts spec envelope |
| Engineer | Diamond | claims spec via @mention, builds, posts artifact |
| Reviewer/Tester | Club | runs can-fail gate, posts verdict envelope |
| Coordinator | Nucleus | recruits, routes, grants consent, calls done (only on PASS) |

Every handoff is an @mention carrying one fenced-JSON **envelope**: prose
for humans, structure for the loop. Three rules are enforced in code, not
in prompts:

- The reviewer **REJECTS** any artifact envelope missing a `ref` it can
  check out — rejection is a FAIL verdict carrying the validation errors
  as receipts.
- The coordinator **REFUSES** to emit `done` without a PASS verdict, and
  `done` envelopes must *embed* the verdict so any receiver can re-check.
- The engineer **BLOCKS** on unsafe actions (file deletion, network push,
  spend) and posts a `consent_request`; grants ride the room as envelopes.

## Band is load-bearing — provably

The hackathon's hard rule: Band must be part of the actual collaboration
layer, not a notification mirror. We made that falsifiable instead of
aspirational: `gate_band_loadbearing.py` is a four-leg kill-test harness —
sever Band mid-loop and the loop MUST stall (no `done` by any path), with
negative controls, a consume-path scan (no agent reads workflow state from
anywhere but Band), and a decoy sweep that kills each validation organ
in-process to prove the gate itself can go red.

```bash
python gate_band_loadbearing.py   # exit 0 = gate PASS, receipts printed
```

## Components

| File | What |
|------|------|
| `envelopes.py` | Envelope schema + validation + REJECT logic |
| `consent.py` | Consent gate: action classifier → consent envelopes |
| `_gate_fallback.py` | Standalone mirror of the cell's autonomy-gate patterns |
| `band_agent.py` | Generic agent wrapper: config, role behaviors, SDK seam |
| `run_pod.py` | Launcher: preflight + bring up the 4-agent pod |
| `gate_band_loadbearing.py` | The "Band removable = FAIL" kill-test harness |

All selftests run offline (no SDK, no network) and exit nonzero on failure:

```bash
python envelopes.py
python consent.py
python band_agent.py --selftest
python run_pod.py --preflight
```

## Setup

```bash
pip install "band-sdk[claude_sdk]"
```

1. Create a free account at [app.band.ai](https://app.band.ai/dashboard).
2. Dashboard → create a **Remote Agent** per loop role (gamer, diamond,
   club, nucleus). The creation popup shows the **API Key**; the
   **Agent UUID** is bottom-right of the agent page.
3. `cp .env.example .env` — production URLs are pre-filled; add LLM keys.
4. `cp agent_config.example.yaml agent_config.yaml` — fill per-role credentials.
5. `python run_pod.py --preflight` until it says GO, then drop `--preflight`.

**Adapter note:** the claude_sdk adapter is @mention-triggered — agents wake
only when mentioned, so every handoff @mentions the next role. All SDK
wiring is isolated in `band_agent.BandTransport`.

## Secrets policy

| File | Tracked? | Holds |
|------|----------|-------|
| `.env.example`, `agent_config.example.yaml` | yes | placeholders only |
| `.env` | no | platform URLs + LLM keys |
| `agent_config.yaml` | no | per-agent UUIDs + Band API keys |

Never put a real key in a tracked file.

## License

MIT — see [LICENSE](LICENSE).

## References

- SDK setup: https://docs.band.ai/integrations/sdks/tutorials/setup
- Core concepts: https://docs.thenvoi.com/core-concepts
- Hackathon: https://lablab.ai/ai-hackathons/band-of-agents-hackathon
