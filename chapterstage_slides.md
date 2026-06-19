# ChapterStage — Hackathon Submission Slides

> **One-liner:** ChapterStage turns any dense chapter or topic — from operating systems to black holes — into a verified, interactive visual learning experience, built live by a team of Band agents and served as a public mini-site.

---

## Slide 1: What We Built

- **Product name:** ChapterStage
- **Event:** Band of Agents Hackathon (lablab.ai, June 12–19, 2026)
- **Track:** Track 2 — Multi-Agent Software Development
- **The pitch:** Paste a chapter, upload a PDF, or enter a topic. Choose your audience and style. Watch a team of specialist agents plan, visualize, build, verify, and publish a beautiful interactive chapter site in seconds.
- **Output:** A hosted HTML/CSS/JS mini-site with screens like narrative scenes, concept maps, flow diagrams, timelines, quizzes, and recaps.
- **Frontend:** Kotlin Multiplatform + Compose Multiplatform app that controls the workflow and renders the final URL.
- **Backend:** FastAPI service orchestrating Band remote agents through LangGraph.

---

## Slide 2: The Problem

- Dense chapters and technical topics are hard to absorb from plain text or slides.
- Creating rich, audience-adapted visual learning content is slow and expensive.
- AI-generated interactive content is often unsafe to publish: remote scripts, eval-based attacks, and network egress are common risks.
- Existing "multi-agent" demos rarely prove the agent platform is actually required for the workflow.

**Our solution:** A product that generates safe, visual, audience-tailored learning experiences — with verifiable proof that the agent collaboration layer is real.

---

## Slide 3: Product Concept — From Source to Site

**Input examples:**

- A PDF chapter on "Process Scheduling"
- Pasted text about "Black Holes"
- A dense explainer on "The French Revolution"
- Notes on "Neural Networks"

**User choices:**

- Audience: Beginner / Intermediate / Expert
- Style: Visual Story / Lecture Mode / Concept Map First / Quiz First / Case Study
- Target screen count: 6–10 scenes
- Auto-brainstorm: on / off

**Output:** A public URL like  
`https://api.chapterstage.dev/public/experiences/exp_abc123/index.html`

---

## Slide 4: Example — "Black Holes" for Beginners

1. User pastes an article on black holes.
2. Structure Agent extracts key concepts: event horizon, singularity, spaghettification, Hawking radiation.
3. Pedagogy Agent identifies likely confusions and quiz points.
4. Brainstorm Agent scores presentation variants and picks "visual story".
5. Visual Builder generates:
   - Scene 1: Narrative intro with a callout on gravity
   - Scene 2: Diagram of a black hole with labeled nodes
   - Scene 3: Timeline from star collapse to evaporation
   - Scene 4: Quiz checkpoint
   - Scene 5: Recap checklist
6. Verifier checks source faithfulness and safety.
7. Site is published; user opens it in the app WebView.

---

## Slide 5: The Frontend — KMP Control Panel

Built with **Kotlin Multiplatform + Compose Multiplatform**.

**Screens:**

| Screen | Purpose |
|--------|---------|
| Home | Product explanation + start CTA |
| Create Chapter | Paste text or upload PDF/TXT |
| Generation Settings | Audience, style, screen count, brainstorm toggle |
| Generation Progress | Live progress bar + agent event feed |
| Agent Trace | Visible Band collaboration timeline |
| Experience Viewer | In-app WebView of the generated public URL |

**Frontend does NOT:** parse generated HTML, implement per-platform renderers, store credentials, or call LLMs directly.

---

## Slide 6: Frontend Architecture

```text
chapterstage-kmp/
  composeApp/
    commonMain/
      data/
        remote/        # Ktor client, SSE streaming
        dto/           # @Serializable request/response models
        repository/    # ChapterRepository, JobRepository
      domain/
        model/         # Chapter, GenerationJob, AgentTraceEvent
        usecase/       # CreateTextChapter, UploadChapter, StartJob, ObserveEvents
      presentation/
        onboarding/
        home/
        create/
        generation/    # Progress screen + event feed
        trace/         # Agent collaboration timeline
        viewer/        # WebView wrapper
      platform/
        FilePicker.*
        WebExperienceView.*
```

- Shared DTOs map exactly to backend §9/§10 contract (`snake_case` via `@SerialName`).
- Platform-specific code is limited to file picking and WebView rendering.

---

## Slide 7: User Navigation Flow

```
Home
  │
  ▼
Create Chapter (paste text or upload file)
  │
  ▼
Generation Settings (audience, style, screens)
  │
  ▼
Generation Progress (live SSE + agent feed)
  │     \
  │      ▼
  │   Agent Trace (who did what)
  │
  ▼
Experience Viewer (open public mini-site)
```

- Progress screen is the hub: user can jump to trace or open the final site as soon as it is ready.
- SSE reconnects automatically; polling fallback every 2 seconds if SSE fails.

---

## Slide 8: Backend Architecture

```
KMP Frontend
    │ REST upload/start
    ▼
FastAPI API Layer
    ├── Job Manager
    ├── Document Parser (text / PDF)
    ├── SSE Event Bus
    └── Static File Serving
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
    │
    ▼
Site Assembly → Validator → Static Storage → Public URL
```

- **Key invariant:** agent-to-agent handoffs ride Band `@mentions`; LangGraph is per-agent internal logic only.

---

## Slide 9: The Agent Team

| Agent | What it contributes |
|-------|---------------------|
| **Coordinator** | Creates the task, delegates to specialists, decides retry/fail/continue |
| **Structure** | Extracts sections, key concepts, dependencies, narrative flow |
| **Pedagogy** | Learning objectives, likely confusions, quiz points, interactive moments |
| **Auto-Brainstorm** | Generates and scores presentation variants (courtroom debate, timeline, concept map, etc.) |
| **Visual Builder** | Writes CSP-safe HTML/CSS/JS + modular screen JSON |
| **Verifier** | Checks source faithfulness, HTML validity, no unsafe JS, mobile responsiveness, accessibility |

Every agent posts structured trace events so the frontend can show a live collaboration timeline.

---

## Slide 10: The Generated Experience

Each published site is a static-hostable directory:

```text
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

**Supported screen types:**

- Narrative scene
- Diagram / concept map
- Flow diagram
- Timeline
- State machine
- Process flow
- Quiz / checkpoint
- Recap checklist

The shell renders one screen at a time, lazy-loads the next, and anonymously resumes the reader's last checkpoint.

---

## Slide 11: Security — Safe by Default

Generated content is **untrusted until validated**.

**Static gate** (`site_validator.py`) checks:

- Required files and schemas
- No remote `<script src>` or external iframes
- No `fetch`, `XMLHttpRequest`, `WebSocket`, `eval`, `Function(...)`
- No inline event handlers
- No path traversal
- Strict CSP meta tag
- Size caps

**Runtime boundary** on `/public/experiences`:

```
Content-Security-Policy:
  default-src 'none';
  script-src 'self';
  connect-src 'self';
  frame-src 'none';
  object-src 'none';
  base-uri 'none'
```

Regex deny-lists lose to obfuscation (`window['fet'+'ch']`). A browser-enforced allowlist does not.

---

## Slide 12: Why Band? (The Load-Bearing Claim)

The hackathon rule: Band must be part of the actual collaboration layer, not a notification mirror.

We made this **falsifiable in code:**

- `gate_band_loadbearing.py` drives the loop with Band alive (positive control), then severs Band mid-loop.
- Result: the loop **must stall** — no `done`, no published site.
- Negative controls and decoy sweeps prove the gate itself can go red.

**Result:** 16/16 checks pass. Band is load-bearing in this build.

`gate_langgraph_loadbearing.py` proves the same on the real workflow over the Band transport — 13/13 checks pass.

---

## Slide 13: API Contract (What the Frontend Consumes)

Base path: `/api/v1`

| Endpoint | Purpose |
|----------|---------|
| `GET /health` | API health |
| `POST /chapters/text` | Create chapter from pasted text |
| `POST /chapters/upload` | Upload PDF/TXT |
| `POST /generation-jobs` | Start agent workflow |
| `GET /generation-jobs/{id}` | Poll status |
| `GET /generation-jobs/{id}/events` | SSE progress + agent messages |
| `GET /generation-jobs/{id}/trace` | Agent collaboration timeline |
| `GET /experiences/{id}` | Published metadata |
| `GET/PUT /experiences/{id}/progress` | Anonymous global progress |

All errors use a stable shape:

```json
{
  "error": {
    "code": "CHAPTER_TOO_SHORT",
    "message": "...",
    "details": {}
  }
}
```

---

## Slide 14: SSE Events the Frontend Receives

Event types:

- `job_progress` — status, progress, current step
- `agent_message` — who acted and what happened
- `brainstorm_variant` — concept being considered
- `validation_report` — verifier results
- `experience_ready` — final public URL
- `job_failed` — terminal failure with code
- `heartbeat` — keep-alive

The frontend maps these into a progress bar, agent chips, and a scrollable event feed.

---

## Slide 15: LLM Provider Abstraction

- **Local-first default:** Ollama (great for hackathon demos, no API spend).
- **One-line swap:** OpenAI, Anthropic/Claude, or Featherless via env vars.
- **Per-agent routing:** use a small cheap model for structure/brainstorm, a stronger model for the visual builder.

This keeps ChapterStage portable across budgets, hardware, and providers without changing agent logic.

---

## Slide 16: Verification & Test Evidence

All gates run offline (no SDK, no network) and exit nonzero on failure:

| Test | Result |
|------|--------|
| `envelopes.py` | 12/12 |
| `band_agent.py --selftest` | 10/10 |
| `gate_band_loadbearing.py` | 16/16 |
| `gate_langgraph_loadbearing.py` | 13/13 |
| `tests/test_api_jobs.py` | 11/11 |
| `tests/test_site_validator.py` | 24/24 |
| `tests/test_public_csp.py` | 7/7 |
| `tests/test_chapter_graph.py` | 11/11 |
| `tests/test_m4_band_loadbearing.py` | 9/9 |
| `tests/test_global_progress.py` | 5/5 |
| `tests/test_run_flow_script.py` | 6/6 |

**Total passing gate checks:** 124+

---

## Slide 17: Implementation Status

**Done:**

- ✅ FastAPI backend with SQLModel persistence
- ✅ Text + PDF/TXT chapter ingestion
- ✅ Selectable Band transport (test + live SDK)
- ✅ Job lifecycle, SSE events, agent trace
- ✅ Background execution and publishing
- ✅ Modular generated-site shell
- ✅ Site validator + runtime CSP security boundary
- ✅ Anonymous global reader progress
- ✅ LLM provider abstraction (Ollama, OpenAI, Anthropic, Featherless)
- ✅ Provider-backed agent hooks
- ✅ Load-bearing kill-test gates

**Next:**

- Production migrations for Postgres
- Live Band SDK smoke test with credentials
- Richer visual components and animations
- Provider retry/failure hardening
- Frontend KMP integration and end-to-end mobile demo

---

## Slide 18: How to Run the Backend Demo

```bash
python3 -m venv venv
./venv/bin/pip install -r chapterstage_backend/requirements.txt
./venv/bin/uvicorn app.main:app --app-dir chapterstage_backend --reload
```

One-command happy-path flow:

```bash
./venv/bin/python chapterstage_backend/scripts/run_flow.py
```

Output ends with:

```text
PASS completed
experience_id=...
public_url=http://127.0.0.1:8000/public/experiences/.../index.html
```

Run all gates:

```bash
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

## Slide 19: Closing Argument

- ChapterStage is a real product: turn any chapter or topic into a visual, interactive learning experience.
- It is safe by default: generated sites pass a strict validator and browser-enforced CSP before they ever get a public URL.
- It is observable: users watch specialist agents collaborate in real time through the frontend trace.
- It is honest: we prove Band is load-bearing — sever the room, and work stops.
- This is not a slide about agents. This is a working system where agents build something useful, verifiable, and safe.

---

## Appendix: Glossary

- **Envelope** — a fenced JSON block inside a Band message carrying structured handoff data.
- **Load-bearing** — the platform is required for workflow progress; removing it causes a verifiable stall.
- **CSP** — Content-Security-Policy, a browser-enforced allowlist for scripts and network connections.
- **LangGraph** — per-agent state-machine framework; used inside agents, not between them.
- **Test transport** — deterministic offline Band stand-in for gates.
- **Live transport** — real Band SDK mode activated by `BAND_TRANSPORT_MODE=live`.
