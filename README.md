# ChapterStage — Backend

The backend for **ChapterStage**, a multi-agent system that turns a book chapter, PDF chapter, pasted text, or dense document into a verified, interactive visual learning mini-site.

Built with **FastAPI**, **LangGraph**, and **Band.ai** remote agents.

---

## What it does

1. Accepts chapter input from a client (text paste or PDF/TXT upload).
2. Starts a tracked generation job.
3. Spins up a Band chat room for the chapter.
4. Runs a LangGraph workflow with specialist agents.
5. Produces a constrained HTML/CSS/JS site directory.
6. Validates the generated site before it gets a public URL.
7. Streams job status through REST + SSE.
8. Serves the final experience at a public static URL.

---

## The agent team

Every specialist posts structured trace events so the frontend can show a live collaboration timeline.

| Agent | Responsibility |
|-------|----------------|
| **Coordinator** | Creates the task, delegates to specialists, decides retry / fail / continue. |
| **Structure** | Extracts sections, key concepts, dependencies, narrative flow. |
| **Pedagogy** | Learning objectives, likely confusions, quiz points, interactive moments. |
| **Auto-Brainstorm** | Generates and scores presentation variants, picks the best concept. |
| **Visual Builder** | Writes CSP-safe HTML/CSS/JS plus modular screen JSON. |
| **Verifier** | Checks source faithfulness, HTML validity, unsafe JS, mobile responsiveness, accessibility. |

Agent-to-agent handoffs ride Band `@mentions`; LangGraph handles per-agent internal logic only.

---

## Backend architecture

```text
Client
  │ REST upload / start
  ▼
FastAPI API Layer ──► Job Manager
  │                     │
  │                     ▼
SSE ◄────────────── LangGraph Workflow
  │                     │
  │                     ▼
  ▼              Band.ai Chapter Room
Public URL ◄──────── Agent team
```

Key modules:

| Path | What |
|------|------|
| `chapterstage_backend/app/` | FastAPI routes, schemas, services, persistence. |
| `chapterstage_backend/workflows/` | LangGraph graph, state model, node functions. |
| `chapterstage_backend/agents/` | Remote agent implementations and prompts. |
| `chapterstage_backend/scripts/` | Demo / happy-path runner scripts. |
| `static/generated/` | Local static output for generated experiences. |
| `envelopes.py` | Envelope schema + validation + REJECT logic. |
| `consent.py` | Consent gate: action classifier → consent envelopes. |
| `band_agent.py` | Generic agent wrapper: config, role behaviors, SDK seam. |
| `gate_band_loadbearing.py` | Verifies Band is required for workflow progress. |
| `gate_langgraph_loadbearing.py` | Verifies the LangGraph workflow over Band transport. |

---

## API at a glance

Base path: `/api/v1`

| Endpoint | Purpose |
|----------|---------|
| `GET /health` | API health. |
| `POST /chapters/text` | Create chapter from pasted text. |
| `POST /chapters/upload` | Upload PDF/TXT. |
| `POST /generation-jobs` | Start the agent workflow. |
| `GET /generation-jobs/{id}` | Poll job status. |
| `GET /generation-jobs/{id}/events` | SSE progress + agent messages. |
| `GET /generation-jobs/{id}/trace` | Agent collaboration timeline. |
| `GET /experiences/{id}` | Published metadata. |

See `chapterstage_backend_handoff.md` §9 for the full contract.

---

## Safety by default

Generated content is **untrusted until validated**.

- `site_validator.py` checks required files, schemas, remote scripts, inline event handlers, path traversal, CSP meta tag, and size caps.
- The `/public/experiences` route serves with a strict browser-enforced CSP.
- Unsafe actions (file deletion, network push, spend) are blocked behind a `consent_request` envelope.

---

## Why Band is load-bearing

The agent platform is part of the actual collaboration layer, not a notification mirror. We made this falsifiable:

- `gate_band_loadbearing.py` runs the loop with Band alive, then severs Band mid-loop.
- The loop **must stall** — no `done`, no published site.
- Negative controls and decoy sweeps prove the gate itself can go red.

Run the gates:

```bash
python gate_band_loadbearing.py
python gate_langgraph_loadbearing.py
```

---

## Setup

```bash
python3 -m venv venv
./venv/bin/pip install -r chapterstage_backend/requirements.txt
```

1. `cp .env.example .env` — fill platform URLs and LLM keys.
2. `cp chapterstage_agent_config.example.yaml chapterstage_agent_config.yaml` — add per-agent Band credentials.
3. Start the server:

```bash
./venv/bin/uvicorn app.main:app --app-dir chapterstage_backend --reload
```

Run a one-command happy-path flow:

```bash
./venv/bin/python chapterstage_backend/scripts/run_flow.py
```

---

## Tests

All gates run offline (no SDK, no network) and exit nonzero on failure:

```bash
python envelopes.py
python consent.py
python band_agent.py --selftest
python gate_band_loadbearing.py
python gate_langgraph_loadbearing.py
python chapterstage_backend/tests/test_api_jobs.py
python chapterstage_backend/tests/test_site_validator.py
python chapterstage_backend/tests/test_chapter_graph.py
python chapterstage_backend/tests/test_public_csp.py
python chapterstage_backend/tests/test_global_progress.py
```

---

## Secrets policy

| File | Tracked? | Holds |
|------|----------|-------|
| `.env.example`, `chapterstage_agent_config.example.yaml` | yes | placeholders only |
| `.env` | no | platform URLs + LLM keys |
| `chapterstage_agent_config.yaml` | no | per-agent UUIDs + Band API keys |

Never put a real key in a tracked file.

---

## License

MIT — see [LICENSE](LICENSE).

---

## References

- Band remote agents: https://docs.band.ai/getting-started/connect-remote-agent
- Band SDK: https://docs.band.ai/integrations/sdks/overview
- LangGraph: https://docs.langchain.com/oss/python/langgraph/overview
- FastAPI: https://fastapi.tiangolo.com/
