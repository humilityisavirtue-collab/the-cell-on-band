# ChapterStage Backend TODOs

## Current Decisions

- Keep the Cell-on-Band invariant: agent-to-agent handoffs must ride Band @mentions.
- Keep ChapterStage product logic separate from the reusable Cell-on-Band chassis.
- Use FastAPI as the backend service.
- Use SQLAlchemy/SQLModel for persistence.
- Use a modular generated-site architecture: static chapter shell plus progressive screen/component rendering.
- Persist one anonymous global reader-progress record per experience in the local database and resume from the last checkpoint.
- Do not add authentication for visualization pages in this MVP. The generated chapter pages are anonymous and share progress globally.
- Use Ollama as the local-first LLM provider.
- Add a provider abstraction so OpenAI, Anthropic/Claude, Featherless, or other providers can be enabled through environment variables later.
- Provider selection should be dynamic: use the first configured provider by priority, with Ollama preferred for local development.
- Default Band transport mode must be offline and deterministic. Real Band SDK calls happen only when `BAND_TRANSPORT_MODE=live`.

## Implementation Status

- Completed through `codex/stage-7-anonymous-progress`:
  - FastAPI service skeleton, SQLModel persistence, generated static site serving, and strict public-site CSP.
  - Selectable Band transport with deterministic test mode and fail-fast live mode.
  - Modular generated-site contract with progressive screen loading.
  - Ollama-first provider abstraction with OpenAI, Anthropic/Claude, and Featherless portability hooks.
  - Provider-backed agent hooks with the Cell-on-Band handoff invariant preserved.
  - Background job execution, SSE replay, agent trace persistence, publishing, experience metadata lookup, recent job listing, and global anonymous progress.
- Still pending:
  - Production-grade schema migrations for non-SQLite databases.
  - Real live Band SDK smoke testing with credentials.
  - Rich generated visualization components beyond the current minimal modular shell.
  - Provider failure/retry hardening across all agent outputs.

## Phase 0: Runtime And Dependency Fixes

- Add missing runtime dependencies to `chapterstage_backend/requirements.txt`:
  - `greenlet`
  - `pypdf`
  - optional live mode: `band-sdk[langgraph]` in `requirements-live.txt`
- Re-run current tests after dependency fix:
  - `./venv/bin/python chapterstage_backend/tests/test_api_jobs.py`
  - `./venv/bin/python chapterstage_backend/tests/test_public_csp.py`
  - `./venv/bin/python chapterstage_backend/tests/test_chapter_graph.py`
  - `./venv/bin/python chapterstage_backend/tests/test_m4_band_loadbearing.py`
  - `./venv/bin/python chapterstage_backend/tests/test_site_validator.py`

## Phase 0.5: Selectable Band Transport

- Add config:
  - `BAND_TRANSPORT_MODE=test`
  - allowed values: `test`, `live`
  - `BAND_API_KEY=`
  - `BAND_API_URL=https://app.band.ai`
  - `BAND_WS_URL=wss://app.band.ai/api/v1/socket/websocket`
  - per-agent UUID env vars from the handoff
- Add transport package:
  - `app/services/band_transport/base.py`
  - `app/services/band_transport/test_transport.py`
  - `app/services/band_transport/sdk_transport.py`
  - `app/services/band_transport/factory.py`
- Define transport interface:
  - `open_room(room_id: str) -> str | None`
  - `recruit(role: str) -> None`
  - `post(to_role: str, text: str) -> bool`
  - `sever() -> None`
  - `alive: bool`
- Keep `BandService` independent of SDK details.
  - `BandService` only calls the transport interface.
  - `BandService.handoff()` remains the only inter-agent channel.
- Implement `TestBandTransport`.
  - no network
  - records rooms, recruited roles, and posts
  - supports `sever()`
  - used in unit/integration tests
- Implement `BandSdkTransport`.
  - wraps Band SDK calls through `BandLink` and room-bound `AgentTools`
  - creates or associates rooms
  - recruits remote agents
  - posts @mention messages
  - exposes WebSocket connect/disconnect for future inbound event handling
  - raises clear configuration errors if SDK or credentials are missing
- Add tests:
  - test mode never imports/calls Band SDK
  - live mode fails fast without credentials
  - `BandService` works with `TestBandTransport`
  - severed test transport stalls workflow
  - existing load-bearing tests still pass

## Phase 1: Global Anonymous Reader Progress

- Do not create account/auth models for visualization pages.
- Remove auth endpoints and auth dependencies from the MVP backend.
- Add `ReaderProgress` model only.
- Add progress endpoints:
  - `GET /api/v1/experiences/{experience_id}/progress`
  - `PUT /api/v1/experiences/{experience_id}/progress`
- Persist progress fields:
  - `experience_id`
  - `current_screen_id`
  - `completed_screen_ids`
  - `last_checkpoint`
  - `interaction_state`
  - `updated_at`
- Ensure progress is globally scoped by experience only.
- If old SQLite dev databases still have user-scoped `reader_progress`, migrate latest progress per experience into the global table on startup.

## Phase 2: Modular Site Contract

- Replace single monolithic generated experience assumptions with a modular contract.
- Generated output should remain static-hostable, but the runtime should progressively render screens/components.
- Required generated files:
  - `index.html`
  - `styles.css`
  - `script.js`
  - `metadata.json`
  - `manifest.json`
  - `screens/*.json`
  - optional `assets/`
- Add `manifest.json` schema:
  - `experience_id`
  - `job_id`
  - `title`
  - `screen_order`
  - `initial_screen_id`
  - `components_used`
  - `checkpoint_rules`
- Each screen JSON should describe one renderable unit:
  - screen id
  - title
  - component type
  - content payload
  - interactions
  - next/previous links
  - checkpoint behavior
- The site shell should:
  - fetch or load local `manifest.json`
  - render only the current screen
  - lazy-load next screen data
  - save progress after screen completion/checkpoint
  - resume from backend progress without requiring auth, cookies, or a user account
- Keep generated site CSP-compatible:
  - allow only same-origin backend progress APIs if progress sync is called from the generated shell
  - continue blocking arbitrary remote network calls

## Phase 3: Site Validator Updates

- Extend `site_validator.py` to validate:
  - `manifest.json`
  - `screens/*.json`
  - local-only screen references
  - valid component types
  - no path traversal in screen/assets refs
  - no oversized screen payloads
- Revisit CSP policy:
  - keep `connect-src 'self'` so the static shell can sync progress with the same-origin backend
  - test that remote network calls still fail
- Add tests:
  - modular clean site passes
  - missing manifest fails
  - invalid screen schema fails
  - screen path traversal fails
  - same-origin progress API allowed
  - remote fetch still blocked

## Phase 4: Provider Abstraction

- Add `app/services/llm/` package:
  - `base.py`
  - `ollama_provider.py`
  - `openai_provider.py`
  - `anthropic_provider.py`
  - `featherless_provider.py`
  - `router.py`
- Define a provider interface:
  - `generate_text(messages, model=None, temperature=None, json_schema=None)`
  - `generate_json(messages, schema, model=None)`
  - streaming optional later
- Env-based provider priority:
  - Ollama if `OLLAMA_BASE_URL` and `OLLAMA_MODEL` are set
  - OpenAI if `OPENAI_API_KEY` is set
  - Anthropic if `ANTHROPIC_API_KEY` is set
  - Featherless if `FEATHERLESS_API_KEY` is set
- Add config env vars:
  - `LLM_PROVIDER=auto`
  - `OLLAMA_BASE_URL=http://localhost:11434`
  - `OLLAMA_MODEL=`
  - `OPENAI_API_KEY=`
  - `OPENAI_MODEL=`
  - `ANTHROPIC_API_KEY=`
  - `ANTHROPIC_MODEL=`
  - `FEATHERLESS_API_KEY=`
  - `FEATHERLESS_MODEL=`
- ChapterStage agents should call the provider interface, not vendor SDKs directly.

## Phase 5: Real Agent Workflows

- Replace stub nodes with provider-backed agent work:
  - structure agent
  - pedagogy agent
  - brainstorm agent
  - visual builder agent
  - verifier agent
- Preserve current invariant:
  - each agent may use its own LangGraph internally
  - inter-agent transitions still go through `BandService.handoff()`
- Validate every agent output through `chapterstage_envelopes.py`.
- Add retry behavior:
  - JSON parse failure: retry once with validation error
  - validation failure: fail job or repair when safe
  - model/provider failure: mark job failed with stable error code

## Phase 6: Job Execution And Events

- Wire `POST /generation-jobs` to start background execution.
- Persist job lifecycle transitions:
  - `queued`
  - `extracting`
  - `creating_band_room`
  - `structuring`
  - `pedagogy_review`
  - `brainstorming`
  - `building_site`
  - `verifying`
  - `publishing`
  - `completed`
  - failure states
- Add SSE endpoint:
  - `GET /api/v1/generation-jobs/{job_id}/events`
- Add trace endpoint:
  - `GET /api/v1/generation-jobs/{job_id}/trace`
- Add recent jobs endpoint:
  - `GET /api/v1/generation-jobs?limit=&offset=`
- Store agent trace events in the existing `AgentTraceEvent` table.

## Phase 7: Publishing And Resume Flow

- Add `site_storage.py` service.
- On successful validation:
  - write generated modular site to `GENERATED_SITE_ROOT/{experience_id}/`
  - create `Experience` row
  - update job with `experience_id` and `public_url`
- Add endpoint:
  - `GET /api/v1/experiences/{experience_id}`
- Ensure opening a public experience:
  - loads shell
  - requests global backend progress anonymously
  - resumes at last checkpoint
  - saves new progress as the reader advances

## Phase 8: Tests To Add

- Progress:
  - auth endpoints are not mounted
  - save global anonymous progress
  - resume global anonymous progress across clients
  - keep progress separate between experiences
- Modular site:
  - valid modular site passes validator
  - invalid screen schema rejected
  - progressive shell does not render all screens at once
- Provider abstraction:
  - Ollama provider selected when Ollama env is set
  - OpenAI/Anthropic/Featherless ignored when env missing
  - provider failure maps to stable backend error
- Workflow:
  - job progresses beyond `queued`
  - agent outputs persist trace events
  - generated experience gets public URL
  - severed Band transport still prevents completion
  - experience metadata endpoint returns published experience
  - recent jobs endpoint lists created jobs
