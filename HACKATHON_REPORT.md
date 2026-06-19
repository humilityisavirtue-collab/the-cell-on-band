# Hackathon Submission Report — The Cell, on Band

> **One-liner:** A provably load-bearing multi-agent software delivery loop that runs on Band as the coordination transport — and a working ChapterStage backend that turns book chapters into verified, interactive learning mini-sites built by that agent team.

---

## Slide 1: What We Built

- **Project name:** The Cell, on Band  
- **Event:** Band of Agents Hackathon (lablab.ai, June 12–19, 2026)  
- **Track:** Track 2 — Multi-Agent Software Development  
- **Submission angle:** Band is not a chat log or notification mirror; it is the live, load-bearing collaboration layer. We made that claim falsifiable in code.
- **Two layered deliverables:**
  1. **Cell-on-Band chassis** — a 4-agent loop (Planner / Engineer / Reviewer / Coordinator) with handoff envelopes, consent gates, and kill-test harnesses.
  2. **ChapterStage backend** — a FastAPI service on that chassis that converts a pasted chapter or PDF into a CSP-safe, public interactive learning site.

---

## Slide 2: The Problem We Are Solving

- Hackathon entries often claim "multi-agent collaboration" but cannot prove the platform is actually required for the loop to work.
- Generated content from AI agents is usually trusted implicitly, leaving demo deployments open to remote-script injection, eval-based XSS, and network egress.
- Most agent workflows are black boxes: humans cannot see who did what, when, or why a job failed.
- Learning-content creation is slow, manual, and hard to adapt for different audiences.

Our solution addresses all three: **provable platform dependency**, **verified untrusted output**, and **observable agent teamwork**.

---

## Slide 3: The 4-Agent Loop (Cell-on-Band)

| Band role | Cell role | Job on Band |
|-----------|-----------|-------------|
| Planner   | Gamer     | Decomposes the ask and posts a `spec` envelope |
| Engineer  | Diamond   | Claims the spec, builds, and posts an `artifact` envelope |
| Reviewer  | Club      | Runs a can-fail gate and posts a `verdict` envelope |
| Coordinator | Nucleus | Recruits, routes, grants consent, and calls `done` only on PASS |

- Every handoff is an `@mention` carrying one fenced-JSON **envelope**: prose for humans, structure for the loop.
- Three rules are enforced in **code, not in prompts**:
  1. Reviewer **REJECTS** any artifact missing a checkout-able `ref`.
  2. Coordinator **REFUSES** to emit `done` without an embedded `PASS` verdict.
  3. Engineer **BLOCKS** unsafe actions (deletion, network push, spend) and posts a `consent_request`.

---

## Slide 4: Why This Is "Load-Bearing" (The Core Claim)

- Hackathon rule: Band must be part of the actual collaboration layer.
- We made the claim **falsifiable** with `gate_band_loadbearing.py`:
  - Drive the loop to completion with Band alive (positive control).
  - Sever Band mid-loop and prove the loop **MUST stall** — no `done` envelope by any path.
  - Negative controls, consume-path scan (no agent reads workflow state except from Band), and a decoy sweep prove the gate itself can go red.
- **Result:** 16/16 gate checks pass. Exit 0 = Band is load-bearing in this build.

---

## Slide 5: ChapterStage — The Demo Product

- **Product:** A Band-powered multi-agent system that converts a book chapter, PDF chapter, pasted text, or dense document into a verified, interactive visual learning mini-site.
- **Frontend client:** Kotlin Multiplatform app (handoff documented).
- **Backend stack:** FastAPI + Python workers + Band.ai remote agents + LangGraph.
- **Output:** A hosted HTML/CSS/JS chapter experience URL.
- **User flow:** paste or upload a chapter → choose audience/style → agents plan, structure, brainstorm, build, verify, and publish → open public URL.

---

## Slide 6: Backend Architecture

```
KMP Frontend
    │ REST upload/start
    ▼
FastAPI API Layer
    ├── Auth (lightweight, none for MVP public pages)
    ├── Job Manager
    ├── Document Parser
    └── SSE bus
            │
            ▼
    LangGraph Workflow
            │
            ▼
    Band.ai Chapter Room
            │
    ┌───────┼───────┬───────────┬────────────┐
    ▼       ▼       ▼           ▼            ▼
Coordinator  Structure  Pedagogy  Auto-Brainstorm  Visual Builder  Verifier
    │               │
    ▼               ▼
Site Assembly → Validator → Static Storage → Public URL
```

- **Invariant:** agent-to-agent handoffs ride Band `@mentions`; LangGraph is per-agent internal logic only.
- **Acceptance test:** sever Band mid-job → job MUST stall (no `completed`, no published URL).

---

## Slide 7: The Agent Team in ChapterStage

| Agent | Responsibility |
|-------|----------------|
| **Coordinator** | Creates the chapter task, mentions specialists, decides continue/retry/fail, summarizes stages |
| **Structure** | Extracts sections, key concepts, dependencies, narrative flow |
| **Pedagogy** | Produces learning objectives, likely confusions, quiz points, interactive moments |
| **Auto-Brainstorm** | Generates and scores presentation variants, selects the best candidate |
| **Visual Builder** | Generates CSP-safe HTML/CSS/JS files and modular screen JSON |
| **Verifier** | Checks source faithfulness, HTML validity, no unsafe JS, mobile responsiveness, accessibility, broken assets |

---

## Slide 8: Security — The Generated Site Is Untrusted Until Proven Safe

- Generated experiences are treated as **untrusted output** until validation passes.
- Two layers of defense:
  1. **Static validator** (`site_validator.py`) checks required files, metadata/manifest/screen schemas, size caps, no remote scripts, no `eval`, no `fetch`, no external iframes, no path traversal, and a strict CSP meta tag.
  2. **Runtime CSP header** on `/public/experiences` enforces `default-src 'none'; script-src 'self'; connect-src 'self'` at the browser.
- Why both? Regex deny-lists lose to obfuscation (`window['fet'+'ch']`). A browser-enforced allowlist does not.
- Tests include evasive JS + CSP-desync negative controls. 24/24 validator checks pass; 7/7 runtime CSP checks pass.

---

## Slide 9: Verification & Test Evidence

All gates run offline (no SDK, no network) and exit nonzero on failure:

| Test | What it proves | Result |
|------|----------------|--------|
| `envelopes.py` | Envelope schema + REJECT logic works | 12/12 |
| `band_agent.py --selftest` | Role behaviors, consent block, done refusal | 10/10 |
| `gate_band_loadbearing.py` | Band is load-bearing; loop stalls if severed | 16/16 |
| `gate_langgraph_loadbearing.py` | Adapter-per-agent topology is load-bearing; master graph is removable | 13/13 |
| `tests/test_api_jobs.py` | API + DB round-trip + §10 error codes | 11/11 |
| `tests/test_site_validator.py` | Generated-site security gate | 24/24 |
| `tests/test_public_csp.py` | Runtime CSP neutralizes evasive JS | 7/7 |
| `tests/test_chapter_graph.py` | Workflow invariant over stubs | 11/11 |
| `tests/test_m4_band_loadbearing.py` | Real workflow load-bearing over transport | 9/9 |
| `tests/test_global_progress.py` | Anonymous global progress persists | 5/5 |
| `tests/test_run_flow_script.py` | One-command demo runner | 6/6 |

**Total passing gate checks:** 124+

---

## Slide 10: API & Demo Flow

Key endpoints (under `/api/v1`):

- `POST /chapters/text` — create chapter from pasted text
- `POST /chapters/upload` — upload PDF or TXT
- `POST /generation-jobs` — start the agent workflow
- `GET /generation-jobs/{job_id}` — poll status
- `GET /generation-jobs/{job_id}/events` — SSE progress stream
- `GET /generation-jobs/{job_id}/trace` — agent trace events
- `GET /experiences/{experience_id}` — metadata
- `GET/PUT /experiences/{experience_id}/progress` — anonymous global progress

One-command demo:

```bash
./venv/bin/python chapterstage_backend/scripts/run_flow.py
```

Success ends with `PASS completed` plus a public experience URL.

---

## Slide 11: LLM Provider Abstraction

- **Local-first:** Ollama (default for development).
- **Pluggable:** OpenAI, Anthropic/Claude, Featherless selectable via environment variables.
- **Per-agent model routing** supported (e.g., small model for structure, larger model for visual builder).
- Agents call a provider interface, not vendor SDKs directly, so the backend is portable across providers and budgets.

---

## Slide 12: Modular Generated Site Contract

Each published experience is a static-hostable directory:

```
{experience_id}/
  index.html
  styles.css
  script.js
  metadata.json
  manifest.json
  screens/
    intro.json
    concept_map.json
    checkpoint.json
    recap.json
  assets/ (optional)
```

- Shell renders one screen at a time, lazy-loads the next, and syncs progress with the same-origin backend.
- Progress is **anonymous and global per experience** — no auth, cookies, or accounts required for MVP.
- Screens support narrative scenes, diagrams, flow diagrams, timelines, state machines, concept maps, quizzes, and recaps.

---

## Slide 13: What Is Implemented Now

- ✅ FastAPI service with SQLModel persistence
- ✅ Selectable Band transport: offline `test` mode and `live` SDK mode
- ✅ Document parser for text and PDF
- ✅ Job lifecycle, SSE events, agent trace persistence
- ✅ Background job execution and publishing
- ✅ Modular generated-site shell
- ✅ Strict site validator + runtime CSP
- ✅ Anonymous global reader progress
- ✅ Provider abstraction (Ollama, OpenAI, Anthropic, Featherless)
- ✅ Provider-backed agent hooks preserving the Cell-on-Band handoff invariant
- ✅ Load-bearing kill-test gates for both root chassis and ChapterStage backend

---

## Slide 14: What Remains / Next Steps

- Production-grade schema migrations for non-SQLite databases.
- Live Band SDK smoke testing with real credentials.
- Richer generated visual components beyond the current modular shell.
- Provider failure/retry hardening across all agent outputs.
- Frontend KMP integration and end-to-end mobile demo.

---

## Slide 15: Repos, Files, and How to Run

- **Repo root:** `/Users/zeeshanali/Documents/Hackathons/Band Of Agents/backend/the-cell-on-band`
- **Key files:**
  - `README.md` — project overview
  - `envelopes.py`, `band_agent.py`, `consent.py` — Cell-on-Band chassis
  - `gate_band_loadbearing.py`, `gate_langgraph_loadbearing.py` — load-bearing kill tests
  - `chapterstage_backend/` — FastAPI backend and ChapterStage workflow
  - `chapterstage_backend_handoff.md` — full backend specification
  - `chapterstage_backend/TESTING_FLOW.md` — step-by-step demo/test guide

Quick start:

```bash
python3 -m venv venv
./venv/bin/pip install -r chapterstage_backend/requirements.txt
./venv/bin/uvicorn app.main:app --app-dir chapterstage_backend --reload
```

Run all gates:

```bash
./venv/bin/python envelopes.py
./venv/bin/python band_agent.py --selftest
./venv/bin/python gate_band_loadbearing.py
./venv/bin/python gate_langgraph_loadbearing.py
./venv/bin/python chapterstage_backend/tests/test_api_jobs.py
./venv/bin/python chapterstage_backend/tests/test_site_validator.py
./venv/bin/python chapterstage_backend/tests/test_chapter_graph.py
./venv/bin/python chapterstage_backend/tests/test_m4_band_loadbearing.py
./venv/bin/python chapterstage_backend/tests/test_public_csp.py
./venv/bin/python chapterstage_backend/tests/test_global_progress.py
```

---

## Slide 16: Closing Argument

- We did not just bolt Band onto a pre-existing workflow.
- We built a loop where **Band is the bus**: sever it, and work stops.
- We did not just claim our generated sites are safe.
- We wrote a validator and browser-enforced CSP that survive obfuscation and desync attacks.
- We did not hide the agent team in a black box.
- Every handoff, trace event, and failure is observable through REST + SSE.
- This is a working, tested, verifiable multi-agent software delivery system — built for Band.

---

## Appendix: Glossary for Slide Generation

- **Envelope** — a fenced JSON block inside a Band message that carries structured handoff data.
- **Load-bearing** — the platform is required for the workflow to make progress; removing it causes a verifiable stall.
- **CSP** — Content-Security-Policy, a browser-enforced allowlist for scripts and network connections.
- **LangGraph** — framework for per-agent state machines; used here *inside* agents, not *between* them.
- **Test transport** — deterministic offline Band stand-in used for gates.
- **Live transport** — real Band SDK mode activated by `BAND_TRANSPORT_MODE=live`.
