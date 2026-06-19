# ChapterStage Backend

A FastAPI service that turns a book chapter (text or PDF) into a **verified,
interactive learning mini-site**, built by a visible team of Band agents and
orchestrated with LangGraph — on top of the [Cell-on-Band](../README.md) chassis.

## The one invariant (gated, non-negotiable)

**Agent-to-agent handoffs ride Band @mentions. LangGraph is per-agent internal
logic only — no top-level graph calls another agent directly.** The Band room is
the live coordination layer, not a log.

Acceptance test for the whole backend: **sever Band mid-job → the job MUST stall**
(no `completed`, no published URL). If a job finishes with Band severed, the build
fails regardless of feature completeness. This is enforced in code:

- `tests/test_chapter_graph.py` — orchestration routes every handoff through
  `band_service`; severing it stalls the job.
- `tests/test_m4_band_loadbearing.py` — the same, proven over the real transport
  @mention path.
- `gate_langgraph_loadbearing.py` (repo root) — proves adapter-per-agent is
  load-bearing while a single master graph is Band-removable, against the *real*
  `band.adapters.langgraph` (not a mock).

## Security: the generated site is untrusted until it passes

A generated experience is blocked from remote network egress and injected code by
a server-enforced, default-deny Content-Security-Policy (`connect-src 'self';
script-src 'self'`, no remote/eval script) on `/public/experiences` —
browser-enforced, default-deny, and **un-weakenable by the page** (CSP combines
by intersection). A regex denylist alone would lose to obfuscation
(`window['fet'+'ch']`); the CSP allowlist does not.

- `app/services/site_validator.py` — requires a strict CSP, blocks remote scripts /
  external iframes / traversal / oversized files (defense-in-depth lint).
- `tests/test_site_validator.py` — 22 checks, incl. evasion + CSP-desync negative
  controls (the validator parses CSP **first-wins**, matching the browser).
- `tests/test_public_csp.py` — proves the served CSP header neutralizes an
  obfuscated-`fetch` site that evades the static scan.

## Run

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt        # Windows: .venv\Scripts\pip
.venv/bin/uvicorn app.main:app --reload          # http://localhost:8000
```

The backend auto-loads [`.env`](</Users/zeeshanali/Documents/Hackathons/Band Of Agents/backend/the-cell-on-band/chapterstage_backend/.env>) on startup. Edit that file, then restart uvicorn to pick up changes.

To expose the local server publicly through ngrok, set `NGROK_AUTHTOKEN` in
`.env` or your shell, then run:

```bash
.venv/bin/python scripts/run_public.py
```

The runner opens the tunnel first, sets `API_BASE_URL` and
`PUBLIC_SITE_BASE_URL` to the ngrok URL for this process, then starts uvicorn.
Use `--ngrok-domain` for a reserved domain or `--ngrok-basic-auth user:pass` to
protect the public tunnel during demos.

Gates (offline, no network):

```bash
python tests/test_chapter_graph.py        # M3 orchestration invariant
python tests/test_m4_band_loadbearing.py  # M4 invariant over the transport
.venv/bin/python tests/test_api_jobs.py   # M1 API + DB round-trip + error codes
python tests/test_site_validator.py       # M5 site security (allowlist CSP)
.venv/bin/python tests/test_public_csp.py # M5 runtime CSP boundary
```

For a step-by-step local simulation of the whole API -> Band workflow -> modular
site -> anonymous progress loop, see
[TESTING_FLOW.md](./TESTING_FLOW.md).

## Status

The backend now has the FastAPI service, SQLModel persistence, selectable Band
transport, modular generated-site shell, provider abstraction, background job
execution, SSE replay, trace events, publishing, and anonymous global progress.
The API DTOs follow the frontend handoff contract; see `app/schemas.py`.
