# ChapterStage — Backend Coding Agent Handoff

**Date:** 2026-06-14  
**Owner:** Backend / AI Orchestration coding agent  
**Product:** ChapterStage  
**Frontend client:** Kotlin Multiplatform app  
**Backend stack:** FastAPI + Python workers + Band.ai remote agents + LangGraph  
**Output:** Hosted HTML/CSS/JS chapter experience URL

---

## 0. Objective

Build the backend for **ChapterStage**, a Band-powered multi-agent system that converts a book chapter, PDF chapter, pasted text, or dense document into a verified, interactive visual learning mini-site.

The backend must:

1. Accept chapter input from the KMP frontend.
2. Start a generation job.
3. Create or associate a Band chat room for the chapter.
4. Run a LangGraph workflow with specialist agents.
5. Produce a constrained HTML/CSS/JS site directory.
6. Validate the generated site before public exposure.
7. Serve job status through REST + SSE.
8. Return a final public URL that mobile/web clients can render in browser/WebView.

---

## 1. Current Documentation Grounding

Use the official docs below as source of truth when implementing integrations.

### Band.ai

- Band remote agents run in our own environment and connect to Band through **REST for outgoing commands** and **WebSocket for incoming messages/events**.
- Band chat rooms use **@mention routing**: mentioned agents process messages; unmentioned agents do not; humans can see the full room conversation.
- Band SDK supports framework adapters, including LangGraph.

References:

- https://docs.band.ai/getting-started/connect-remote-agent
- https://docs.band.ai/api/agent-api
- https://docs.band.ai/core-concepts/chat-rooms
- https://docs.band.ai/integrations/sdks/tutorials/langgraph
- https://docs.band.ai/integrations/sdks/overview

### LangGraph

Use LangGraph for workflow state, node execution, conditional transitions, retries, and resumability.

Core pattern:

```text
Define state → add nodes → add edges / conditional edges → compile graph → run graph
```

References:

- https://docs.langchain.com/oss/python/langgraph/overview
- https://docs.langchain.com/oss/python/langgraph/graph-api

### FastAPI

Use FastAPI for REST APIs, file uploads, background processing, static file serving, and SSE streaming.

References:

- https://fastapi.tiangolo.com/
- https://fastapi.tiangolo.com/tutorial/request-files/
- https://fastapi.tiangolo.com/tutorial/background-tasks/
- https://fastapi.tiangolo.com/tutorial/static-files/
- https://fastapi.tiangolo.com/tutorial/server-sent-events/

---

## 2. Backend Architecture

```mermaid
flowchart TD
    Client[KMP Frontend] -->|REST upload/start| API[FastAPI API Layer]
    Client -->|SSE progress| API
    Client -->|Open final URL| Site[Hosted Chapter Site]

    API --> Auth[Lightweight Auth / Session]
    API --> JobMgr[Job Manager]
    API --> Parser[Document Parser]
    JobMgr --> LG[LangGraph Workflow]

    LG --> Band[Band.ai Chapter Room]
    Band --> Coordinator[Coordinator Agent]
    Band --> Structure[Structure Agent]
    Band --> Pedagogy[Pedagogy Agent]
    Band --> Brainstorm[Auto-Brainstorm Agent]
    Band --> Builder[Visual HTML Builder Agent]
    Band --> Verifier[Verifier Agent]

    LG --> SiteGen[Site Assembly]
    SiteGen --> Validator[HTML/CSS/JS Validator]
    Validator --> Storage[Static Storage Local/S3/R2]
    Storage --> Site

    API --> DB[(PostgreSQL)]
    JobMgr --> Redis[(Redis optional)]
```

### Backend process boundaries

For MVP, this can be one FastAPI service plus one worker process:

```text
backend/
  app/              FastAPI app, routes, schemas, services
  agents/           remote agent implementations / prompts / tools
  workflows/        LangGraph graphs and node functions
  generated_sites/  local static output during MVP
  tests/            unit + integration tests
```

Production later can split into:

```text
api-service
agent-worker
site-publisher
validation-worker
```

---

## 3. Recommended Repository Structure

```text
chapterstage-backend/
  pyproject.toml
  README.md
  .env.example
  app/
    main.py
    config.py
    database.py
    models/
      book.py
      chapter.py
      generation_job.py
      experience.py
      agent_trace.py
    schemas/
      common.py
      chapters.py
      jobs.py
      experiences.py
      traces.py
    api/
      v1/
        router.py
        chapters.py
        jobs.py
        experiences.py
        traces.py
        health.py
    services/
      document_parser.py
      job_service.py
      band_service.py
      site_storage.py
      site_validator.py
      sse_bus.py
    workflows/
      chapter_state.py
      chapter_graph.py
      nodes/
        extract_structure.py
        pedagogy.py
        brainstorm.py
        select_variant.py
        build_site.py
        verify_site.py
        publish_site.py
    agents/
      coordinator_agent.py
      structure_agent.py
      pedagogy_agent.py
      brainstorm_agent.py
      visual_builder_agent.py
      verifier_agent.py
      prompts/
        coordinator.md
        structure.md
        pedagogy.md
        brainstorm.md
        visual_builder.md
        verifier.md
    static/
      generated/
    tests/
      test_api_jobs.py
      test_site_validator.py
      test_workflow_state.py
      test_generated_site_contract.py
```

---

## 4. Core Backend Concepts

### 4.1 Chapter

A chapter is the source unit to transform.

Supported MVP input types:

```text
text/plain
application/pdf
```

Later:

```text
.epub
.docx
Google Drive document
URL extraction
```

### 4.2 Generation Job

A generation job represents one full transformation request.

Lifecycle:

```text
queued
→ extracting
→ creating_band_room
→ structuring
→ pedagogy_review
→ brainstorming
→ selecting_concept
→ building_site
→ verifying
→ publishing
→ completed
```

Failure states:

```text
failed_extraction
failed_agent_workflow
failed_validation
failed_publish
cancelled
```

### 4.3 Band Chapter Room

For each generation job, create or map one Band room:

```text
ChapterStage / {book_title} / {chapter_title or job_id}
```

Minimum room behavior:

1. Coordinator posts the initial task.
2. Coordinator mentions specialist agents.
3. Agent messages are stored in our DB for frontend trace display.
4. Important workflow decisions are summarized into `agent_trace_events`.

### 4.4 Generated Site

Final output directory:

```text
generated_sites/{experience_id}/
  index.html
  styles.css
  script.js
  metadata.json
  assets/
```

MVP hosting options:

1. FastAPI `StaticFiles` mounted at `/public/experiences`.
2. Later: S3/R2 bucket + CDN.

Public URL format:

```text
https://api.chapterstage.dev/public/experiences/{experience_id}/index.html
```

---

## 5. Band.ai Integration Plan

### 5.1 Required environment variables

```bash
BAND_API_KEY=
BAND_AGENT_UUID_COORDINATOR=
BAND_AGENT_UUID_STRUCTURE=
BAND_AGENT_UUID_PEDAGOGY=
BAND_AGENT_UUID_BRAINSTORM=
BAND_AGENT_UUID_VISUAL_BUILDER=
BAND_AGENT_UUID_VERIFIER=
BAND_API_URL=https://app.band.ai/api/v1/agent
BAND_WS_URL=wss://app.band.ai/api/v1/socket/websocket
```

### 5.2 SDK installation

```bash
uv add "band-sdk[langgraph]"
```

### 5.3 Agent roles

#### Coordinator Agent

Owns orchestration, delegation, and conflict resolution.

Responsibilities:

- Create/initialize chapter task.
- Mention relevant agents.
- Decide when to continue, retry, or fail.
- Summarize each stage for frontend trace.

#### Structure Agent

Extracts the chapter map.

Output:

```json
{
  "sections": [],
  "key_concepts": [],
  "concept_dependencies": [],
  "narrative_flow": [],
  "source_quotes": []
}
```

#### Pedagogy Agent

Converts content into learning objectives and learner support.

Output:

```json
{
  "learning_objectives": [],
  "likely_confusions": [],
  "quiz_points": [],
  "interactive_moments": [],
  "audience_adjustments": []
}
```

#### Auto-Brainstorm Agent

AutoResearch-inspired creative loop.

Workflow:

```text
Generate variants → score variants → mutate weak-but-promising variant → select top candidate
```

Output:

```json
{
  "variants": [
    {
      "id": "variant_1",
      "title": "Courtroom Debate",
      "format": "interactive_story",
      "strengths": [],
      "risks": [],
      "scores": {
        "faithfulness": 0.0,
        "clarity": 0.0,
        "engagement": 0.0,
        "feasibility": 0.0
      }
    }
  ],
  "selected_variant_id": "variant_1",
  "selection_reason": "..."
}
```

#### Visual HTML Builder Agent

Generates constrained website files.

Allowed:

- semantic HTML
- CSS
- vanilla JS
- approved client-side libraries if bundled or pinned
- simple SVG diagrams
- Mermaid only if approved and locally loaded/pinned

Forbidden:

- arbitrary remote scripts
- analytics scripts
- cookies
- localStorage unless explicitly approved
- network calls from generated site
- inline event handlers if avoidable
- user credential access
- unsandboxed iframes

#### Verifier Agent

Checks:

- source faithfulness
- HTML validity
- no unsafe JS patterns
- mobile responsiveness
- accessibility basics
- broken links/assets
- quiz answers present
- `metadata.json` present and valid

---

## 6. LangGraph Workflow Specification

### 6.1 State model

Create `workflows/chapter_state.py`:

```python
from typing import Literal, TypedDict, NotRequired

class ChapterWorkflowState(TypedDict):
    job_id: str
    book_title: NotRequired[str]
    chapter_title: NotRequired[str]
    source_type: Literal["text", "pdf"]
    source_text: str
    audience_level: Literal["beginner", "intermediate", "expert"]
    experience_style: str
    target_screen_count: int
    band_room_id: NotRequired[str]
    structure_pack: NotRequired[dict]
    pedagogy_pack: NotRequired[dict]
    brainstorm_pack: NotRequired[dict]
    selected_variant: NotRequired[dict]
    generated_files: NotRequired[dict]
    validation_report: NotRequired[dict]
    public_url: NotRequired[str]
    status: str
    errors: list[dict]
```

### 6.2 Nodes

```text
validate_input
extract_text
create_band_room
run_structure_agent
run_pedagogy_agent
run_brainstorm_agent
select_variant
run_visual_builder_agent
run_verifier_agent
repair_generated_site_if_needed
publish_site
mark_completed
mark_failed
```

### 6.3 Conditional edges

```text
run_verifier_agent
  ├─ if validation passed → publish_site
  ├─ if repairable and attempts < 2 → repair_generated_site_if_needed
  └─ otherwise → mark_failed
```

### 6.4 Retry policy

- Agent JSON parse failure: retry same agent once with validation error.
- Site validation failure: allow max 2 repair attempts.
- Band transport failure: retry with exponential backoff.
- Irrecoverable document parsing failure: fail immediately with user-readable error.

---

## 7. Generated Site Contract

The generated site must be self-contained enough to render from a static URL.

### 7.1 Required files

```text
index.html
styles.css
script.js
metadata.json
```

### 7.2 `metadata.json`

```json
{
  "experience_id": "exp_123",
  "job_id": "job_123",
  "book_title": "Operating Systems Notes",
  "chapter_title": "Processes",
  "audience_level": "beginner",
  "experience_style": "visual_story",
  "screen_count": 8,
  "band_room_id": "band_room_123",
  "selected_brainstorm_variant": "variant_2",
  "faithfulness_score": 0.91,
  "engagement_score": 0.86,
  "created_at": "2026-06-14T08:30:00Z"
}
```

### 7.3 HTML requirements

- Must include viewport meta tag.
- Must work on mobile widths from 360px upward.
- Must not require authentication.
- Must not make network calls.
- Must not include forms that submit externally.
- Must include accessible button labels.
- Must provide keyboard-navigable controls.
- Must include title and metadata.

### 7.4 Allowed interactions

```text
next/previous scene
tap/click to reveal
quiz selection
accordion explanation
concept map hover/click
progress indicator
recap checklist
```

### 7.5 Validation checklist

Implement `site_validator.py` to check:

- all required files exist
- metadata schema is valid
- no `<script src="http...">`
- no `fetch(`, `XMLHttpRequest`, `WebSocket`, `eval`, `Function(...)`
- no external iframe
- HTML contains viewport
- HTML references local CSS/JS files only
- no broken local asset references
- file size limits respected

MVP limits:

```text
index.html <= 250 KB
styles.css <= 250 KB
script.js <= 250 KB
assets total <= 5 MB
```

---

## 8. Database Schema Draft

Use PostgreSQL. ORM can be SQLAlchemy or SQLModel.

### `books`

```sql
id UUID PRIMARY KEY;
title TEXT NOT NULL;
created_at TIMESTAMPTZ NOT NULL DEFAULT now();
updated_at TIMESTAMPTZ NOT NULL DEFAULT now();
```

### `chapters`

```sql
id UUID PRIMARY KEY;
book_id UUID REFERENCES books(id);
title TEXT;
source_type TEXT NOT NULL;
source_text TEXT;
source_file_path TEXT;
created_at TIMESTAMPTZ NOT NULL DEFAULT now();
```

### `generation_jobs`

```sql
id UUID PRIMARY KEY;
chapter_id UUID REFERENCES chapters(id);
status TEXT NOT NULL;
audience_level TEXT NOT NULL;
experience_style TEXT NOT NULL;
target_screen_count INTEGER NOT NULL;
band_room_id TEXT;
error_code TEXT;
error_message TEXT;
created_at TIMESTAMPTZ NOT NULL DEFAULT now();
updated_at TIMESTAMPTZ NOT NULL DEFAULT now();
completed_at TIMESTAMPTZ;
```

### `experiences`

```sql
id UUID PRIMARY KEY;
job_id UUID REFERENCES generation_jobs(id);
public_url TEXT NOT NULL;
storage_path TEXT NOT NULL;
metadata JSONB NOT NULL;
created_at TIMESTAMPTZ NOT NULL DEFAULT now();
```

### `agent_trace_events`

```sql
id UUID PRIMARY KEY;
job_id UUID REFERENCES generation_jobs(id);
band_room_id TEXT;
agent_name TEXT;
event_type TEXT NOT NULL;
title TEXT NOT NULL;
message TEXT NOT NULL;
payload JSONB;
created_at TIMESTAMPTZ NOT NULL DEFAULT now();
```

---

# 9. API Documentation

Base path:

```text
/api/v1
```

Content type:

```text
application/json
```

File upload endpoints use:

```text
multipart/form-data
```

## 9.1 Health

### `GET /health`

Returns API health.

Response:

```json
{
  "status": "ok",
  "version": "0.1.0"
}
```

---

## 9.2 Create chapter from pasted text

### `POST /chapters/text`

Request:

```json
{
  "book_title": "Operating Systems Notes",
  "chapter_title": "Process Concept",
  "text": "Full chapter text..."
}
```

Response `201`:

```json
{
  "chapter_id": "ch_01",
  "book_id": "book_01",
  "title": "Process Concept",
  "source_type": "text",
  "created_at": "2026-06-14T08:00:00Z"
}
```

Validation:

```text
text min length: 500 chars
text max length MVP: 80,000 chars
book_title optional but recommended
chapter_title optional
```

---

## 9.3 Create chapter from file

### `POST /chapters/upload`

Request:

```text
multipart/form-data
file: PDF or TXT file
book_title: optional string
chapter_title: optional string
```

Response `201`:

```json
{
  "chapter_id": "ch_02",
  "book_id": "book_01",
  "title": "Chapter 2",
  "source_type": "pdf",
  "created_at": "2026-06-14T08:05:00Z"
}
```

Validation:

```text
Allowed: .pdf, .txt
MVP file size limit: 20 MB
Reject encrypted PDFs
Reject scanned PDFs unless OCR is added later
```

---

## 9.4 Start generation job

### `POST /generation-jobs`

Request:

```json
{
  "chapter_id": "ch_02",
  "audience_level": "beginner",
  "experience_style": "visual_story",
  "target_screen_count": 8,
  "enable_auto_brainstorm": true
}
```

Allowed `audience_level`:

```text
beginner
intermediate
expert
```

Allowed MVP `experience_style`:

```text
visual_story
lecture_mode
concept_map_first
quiz_first
case_study
```

Response `202`:

```json
{
  "job_id": "job_01",
  "chapter_id": "ch_02",
  "status": "queued",
  "status_url": "/api/v1/generation-jobs/job_01",
  "events_url": "/api/v1/generation-jobs/job_01/events"
}
```

Backend behavior:

1. Create `generation_jobs` row.
2. Queue or background-start workflow.
3. Return immediately.

---

## 9.5 Get generation job

### `GET /generation-jobs/{job_id}`

Response while running:

```json
{
  "job_id": "job_01",
  "chapter_id": "ch_02",
  "status": "brainstorming",
  "progress": 0.45,
  "current_step": "Auto-Brainstorm Agent is generating creative presentation concepts",
  "band_room_id": "room_123",
  "experience_id": null,
  "public_url": null,
  "error": null,
  "created_at": "2026-06-14T08:05:00Z",
  "updated_at": "2026-06-14T08:07:00Z"
}
```

Response completed:

```json
{
  "job_id": "job_01",
  "chapter_id": "ch_02",
  "status": "completed",
  "progress": 1.0,
  "current_step": "Completed",
  "band_room_id": "room_123",
  "experience_id": "exp_01",
  "public_url": "https://api.chapterstage.dev/public/experiences/exp_01/index.html",
  "error": null,
  "created_at": "2026-06-14T08:05:00Z",
  "updated_at": "2026-06-14T08:10:00Z"
}
```

---

## 9.6 Stream generation events

### `GET /generation-jobs/{job_id}/events`

Protocol:

```text
text/event-stream
```

SSE event example:

```text
event: job_progress
data: {"job_id":"job_01","status":"structuring","progress":0.20,"message":"Structure Agent is extracting chapter map"}
```

Event types:

```text
job_progress
agent_message
brainstorm_variant
validation_report
experience_ready
job_failed
heartbeat
```

### `job_progress` payload

```json
{
  "job_id": "job_01",
  "status": "structuring",
  "progress": 0.2,
  "message": "Structure Agent is extracting chapter map",
  "created_at": "2026-06-14T08:06:00Z"
}
```

### `agent_message` payload

```json
{
  "job_id": "job_01",
  "agent_name": "Pedagogy Agent",
  "title": "Likely learner confusions identified",
  "message": "The agent found 4 likely misconceptions and 3 quiz opportunities.",
  "created_at": "2026-06-14T08:06:40Z"
}
```

### `experience_ready` payload

```json
{
  "job_id": "job_01",
  "experience_id": "exp_01",
  "public_url": "https://api.chapterstage.dev/public/experiences/exp_01/index.html",
  "created_at": "2026-06-14T08:10:00Z"
}
```

---

## 9.7 Get agent trace

### `GET /generation-jobs/{job_id}/trace`

Response:

```json
{
  "job_id": "job_01",
  "band_room_id": "room_123",
  "events": [
    {
      "id": "trace_01",
      "agent_name": "Coordinator Agent",
      "event_type": "delegation",
      "title": "Chapter task started",
      "message": "Coordinator delegated structure and pedagogy extraction.",
      "payload": {},
      "created_at": "2026-06-14T08:05:30Z"
    }
  ]
}
```

---

## 9.8 Get experience metadata

### `GET /experiences/{experience_id}`

Response:

```json
{
  "experience_id": "exp_01",
  "job_id": "job_01",
  "public_url": "https://api.chapterstage.dev/public/experiences/exp_01/index.html",
  "metadata": {
    "chapter_title": "Process Concept",
    "screen_count": 8,
    "faithfulness_score": 0.91,
    "engagement_score": 0.86
  },
  "created_at": "2026-06-14T08:10:00Z"
}
```

---

## 9.9 List recent jobs

### `GET /generation-jobs?limit=20&offset=0`

Response:

```json
{
  "items": [
    {
      "job_id": "job_01",
      "chapter_title": "Process Concept",
      "status": "completed",
      "progress": 1.0,
      "public_url": "https://api.chapterstage.dev/public/experiences/exp_01/index.html",
      "created_at": "2026-06-14T08:05:00Z"
    }
  ],
  "limit": 20,
  "offset": 0,
  "total": 1
}
```

---

## 10. Backend Error Model

All errors should use this shape:

```json
{
  "error": {
    "code": "INVALID_FILE_TYPE",
    "message": "Only PDF and TXT files are supported in the MVP.",
    "details": {}
  }
}
```

Recommended error codes:

```text
INVALID_REQUEST
INVALID_FILE_TYPE
FILE_TOO_LARGE
EXTRACTION_FAILED
CHAPTER_TOO_SHORT
CHAPTER_TOO_LONG
JOB_NOT_FOUND
JOB_ALREADY_RUNNING
BAND_ROOM_CREATE_FAILED
AGENT_WORKFLOW_FAILED
SITE_VALIDATION_FAILED
PUBLISH_FAILED
INTERNAL_ERROR
```

---

## 11. Security Requirements

### 11.1 Generated-site sandboxing

The generated site is public content. Treat it as untrusted output until validation passes.

Must enforce:

- no outbound network calls
- no arbitrary external scripts
- no credential/token embedding
- no user PII in generated files
- strict file path normalization
- no path traversal writes
- static hosting under isolated directory

### 11.2 Backend secrets

Never expose these to frontend or generated site:

```text
BAND_API_KEY
LLM provider keys
DATABASE_URL
REDIS_URL
storage credentials
```

### 11.3 Upload safety

- Restrict file types.
- Restrict file size.
- Store uploads outside public directory.
- Sanitize generated file names.
- Reject encrypted/unsupported PDFs.

---

## 12. Environment Variables

```bash
APP_ENV=development
API_BASE_URL=http://localhost:8000
PUBLIC_SITE_BASE_URL=http://localhost:8000/public/experiences
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/chapterstage
REDIS_URL=redis://localhost:6379/0

BAND_API_KEY=
BAND_API_URL=https://app.band.ai/api/v1/agent
BAND_WS_URL=wss://app.band.ai/api/v1/socket/websocket
BAND_AGENT_UUID_COORDINATOR=
BAND_AGENT_UUID_STRUCTURE=
BAND_AGENT_UUID_PEDAGOGY=
BAND_AGENT_UUID_BRAINSTORM=
BAND_AGENT_UUID_VISUAL_BUILDER=
BAND_AGENT_UUID_VERIFIER=

OPENAI_API_KEY=
ANTHROPIC_API_KEY=
AI_ML_API_KEY=
FEATHERLESS_API_KEY=

GENERATED_SITE_ROOT=./static/generated
MAX_UPLOAD_MB=20
MAX_CHAPTER_CHARS=80000
```

---

## 13. Implementation Milestones

### Milestone 1 — API skeleton

- FastAPI project setup.
- Health endpoint.
- DB connection.
- Chapter text endpoint.
- Chapter upload endpoint.
- Basic job creation.

### Milestone 2 — Job progress

- Job lifecycle model.
- SSE endpoint.
- In-memory event bus for MVP.
- Frontend can receive fake progress events.

### Milestone 3 — LangGraph workflow

- Define state.
- Add nodes with stub outputs.
- Complete end-to-end fake generation.

### Milestone 4 — Band integration

- Connect one remote Coordinator Agent.
- Create/associate chapter room.
- Post traceable messages.
- Add specialist agents.

### Milestone 5 — Real generated site

- Builder generates static files.
- Validator validates required files and safety rules.
- FastAPI serves site from static directory.

### Milestone 6 — Full demo flow

- Upload/paste chapter.
- Generate real site.
- Stream progress.
- Show trace.
- Open public URL.

---

## 14. Backend Definition of Done

Backend is MVP-complete when:

- KMP can create a chapter from text.
- KMP can upload a PDF/TXT chapter.
- KMP can start a generation job.
- KMP can stream job updates through SSE.
- Band room/trace is created for each job.
- At least 5 agents participate or are visibly represented.
- LangGraph workflow reaches completed state.
- Generated site directory contains required files.
- Validator blocks unsafe JS/network calls.
- Final public URL opens in browser.
- API returns stable DTOs matching the frontend document.
