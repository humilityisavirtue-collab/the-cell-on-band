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

A generated experience cannot reach the network or run injected code. The boundary
is a **server-enforced Content-Security-Policy** (`connect-src 'none'; script-src
'self'`, no `unsafe-*`) on `/public/experiences` — browser-enforced, default-deny,
and **un-weakenable by the page** (CSP combines by intersection). A regex denylist
alone would lose to obfuscation (`window['fet'+'ch']`); the CSP allowlist does not.

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

Gates (offline, no network):

```bash
python tests/test_chapter_graph.py        # M3 orchestration invariant
python tests/test_m4_band_loadbearing.py  # M4 invariant over the transport
.venv/bin/python tests/test_api_jobs.py   # M1 API + DB round-trip + error codes
python tests/test_site_validator.py       # M5 site security (allowlist CSP)
.venv/bin/python tests/test_public_csp.py # M5 runtime CSP boundary
```

## Status

M1 (API + DB), M3 (orchestration), M4 (Band invariant), M5 (site validator) are
built and gated. M2 (SSE progress) and M6 (full demo) are in progress. The API
DTOs follow the frontend handoff contract (§9); see `app/schemas.py`.
