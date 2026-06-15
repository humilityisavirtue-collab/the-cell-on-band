# ChapterStage Full Flow Testing Guide

This guide simulates the whole ChapterStage backend flow locally:

1. create a chapter
2. start a generation job
3. watch job progress
4. verify Band handoff trace events
5. publish a modular generated site
6. open the public experience
7. persist and resume anonymous global progress

The default path is offline and deterministic. It uses `BAND_TRANSPORT_MODE=test`
and does not call the real Band SDK or any remote LLM provider.

## 1. Prepare The Environment

Run these commands from the repository root:

```bash
python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r chapterstage_backend/requirements.txt
```

Use a local SQLite database and generated-site directory for this simulation:

```bash
export APP_ENV=development
export API_BASE_URL=http://127.0.0.1:8000
export PUBLIC_SITE_BASE_URL=http://127.0.0.1:8000/public/experiences
export DATABASE_URL=sqlite+aiosqlite:///./chapterstage_backend/chapterstage_flow.db
export GENERATED_SITE_ROOT=./chapterstage_backend/static/generated
export BAND_TRANSPORT_MODE=test
```

For a fully deterministic offline run, clear provider env vars so the agents use
their built-in fallback logic:

```bash
unset OLLAMA_MODEL
unset OPENAI_API_KEY OPENAI_MODEL
unset ANTHROPIC_API_KEY ANTHROPIC_MODEL
unset FEATHERLESS_API_KEY FEATHERLESS_MODEL
export LLM_PROVIDER=auto
```

Optional Ollama mode:

```bash
# Run this in another terminal if Ollama is not already serving.
ollama serve
```

Then, in the backend terminal:

```bash
ollama pull llama3.1
export LLM_PROVIDER=ollama
export OLLAMA_BASE_URL=http://localhost:11434
export OLLAMA_MODEL=llama3.1
```

Only enable Ollama if the local Ollama server is running. Otherwise generation
will fail when an agent tries to call the provider.

## 2. Run The Offline Gates

These tests use temp databases/directories and should not touch the local
simulation database above.

```bash
set -e
python chapterstage_backend/tests/test_api_jobs.py
python chapterstage_backend/tests/test_global_progress.py
python chapterstage_backend/tests/test_job_execution.py
python chapterstage_backend/tests/test_site_storage.py
python chapterstage_backend/tests/test_site_validator.py
python chapterstage_backend/tests/test_public_csp.py
python chapterstage_backend/tests/test_band_transport_factory.py
python chapterstage_backend/tests/test_chapter_graph.py
python chapterstage_backend/tests/test_m4_band_loadbearing.py
python chapterstage_backend/tests/test_llm_provider_router.py
python chapterstage_backend/tests/test_chapter_agents.py
```

Expected result: every script exits with `GATE PASS`.

## 3. Start The API Server

Keep the env vars from step 1 in the same shell, then start FastAPI:

```bash
uvicorn app.main:app \
  --app-dir chapterstage_backend \
  --host 127.0.0.1 \
  --port 8000 \
  --reload
```

Open a second terminal for the remaining commands and export the same key vars:

```bash
export BASE=http://127.0.0.1:8000/api/v1
export PUBLIC_BASE=http://127.0.0.1:8000/public/experiences
```

Check health:

```bash
curl -sS "$BASE/health" | python -m json.tool
```

Expected response:

```json
{
  "status": "ok",
  "version": "0.1.0"
}
```

## 4. Create A Chapter

Create a JSON payload with enough text to pass the chapter length validator:

```bash
mkdir -p /tmp/chapterstage-flow
python - <<'PY'
import json
from pathlib import Path

text = "Processes are running program instances. " * 40
payload = {
    "book_title": "Operating Systems",
    "chapter_title": "Processes",
    "text": text,
}
Path("/tmp/chapterstage-flow/chapter_payload.json").write_text(json.dumps(payload))
PY
```

Post the chapter:

```bash
curl -sS -X POST "$BASE/chapters/text" \
  -H "Content-Type: application/json" \
  --data @/tmp/chapterstage-flow/chapter_payload.json \
  | tee /tmp/chapterstage-flow/chapter_response.json \
  | python -m json.tool
```

Save the returned id:

```bash
export CHAPTER_ID="$(
  python - <<'PY'
import json
print(json.load(open("/tmp/chapterstage-flow/chapter_response.json"))["chapter_id"])
PY
)"
echo "$CHAPTER_ID"
```

## 5. Start A Generation Job

Create and submit the job payload:

```bash
python - <<'PY'
import json
import os
from pathlib import Path

payload = {
    "chapter_id": os.environ["CHAPTER_ID"],
    "audience_level": "beginner",
    "experience_style": "visual_story",
    "target_screen_count": 3,
    "enable_auto_brainstorm": True,
}
Path("/tmp/chapterstage-flow/job_payload.json").write_text(json.dumps(payload))
PY

curl -sS -X POST "$BASE/generation-jobs" \
  -H "Content-Type: application/json" \
  --data @/tmp/chapterstage-flow/job_payload.json \
  | tee /tmp/chapterstage-flow/job_response.json \
  | python -m json.tool
```

Save the job id:

```bash
export JOB_ID="$(
  python - <<'PY'
import json
print(json.load(open("/tmp/chapterstage-flow/job_response.json"))["job_id"])
PY
)"
echo "$JOB_ID"
```

## 6. Poll Until The Job Completes

```bash
python - <<'PY'
import json
import os
import time
import urllib.request
from pathlib import Path

base = os.environ["BASE"]
job_id = os.environ["JOB_ID"]
status_path = Path("/tmp/chapterstage-flow/job_status.json")

for _ in range(30):
    with urllib.request.urlopen(f"{base}/generation-jobs/{job_id}") as response:
        payload = json.loads(response.read().decode("utf-8"))
    status_path.write_text(json.dumps(payload, indent=2))
    print(payload["status"], payload["progress"], payload.get("current_step"))
    if payload["status"] in {"completed", "failed_agent_workflow"}:
        break
    time.sleep(0.25)
else:
    raise SystemExit("job did not finish in time")

if payload["status"] != "completed":
    raise SystemExit(json.dumps(payload, indent=2))
PY
```

Expected final status: `completed`, with `experience_id` and `public_url`.

Extract them for later steps:

```bash
export EXPERIENCE_ID="$(
  python - <<'PY'
import json
print(json.load(open("/tmp/chapterstage-flow/job_status.json"))["experience_id"])
PY
)"
export PUBLIC_URL="$(
  python - <<'PY'
import json
print(json.load(open("/tmp/chapterstage-flow/job_status.json"))["public_url"])
PY
)"
echo "$EXPERIENCE_ID"
echo "$PUBLIC_URL"
```

## 7. Inspect Events, Trace, And Recent Jobs

SSE replay:

```bash
curl --max-time 5 -N "$BASE/generation-jobs/$JOB_ID/events"
```

Expected event names include:

- `job_progress`
- `agent_message`
- `experience_ready`

Agent trace:

```bash
curl -sS "$BASE/generation-jobs/$JOB_ID/trace" | python -m json.tool
```

Expected shape:

- `band_room_id` is present in test mode
- `events` contains four Band handoff events

Recent jobs:

```bash
curl -sS "$BASE/generation-jobs?limit=5&offset=0" | python -m json.tool
```

Expected result: the current `JOB_ID` appears in `jobs`.

## 8. Inspect The Published Experience

Fetch the experience metadata endpoint:

```bash
curl -sS "$BASE/experiences/$EXPERIENCE_ID" | python -m json.tool
```

Inspect the generated files:

```bash
find "chapterstage_backend/static/generated/$EXPERIENCE_ID" -maxdepth 2 -type f | sort
python -m json.tool < "chapterstage_backend/static/generated/$EXPERIENCE_ID/manifest.json"
python -m json.tool < "chapterstage_backend/static/generated/$EXPERIENCE_ID/metadata.json"
```

Expected files:

- `index.html`
- `styles.css`
- `script.js`
- `manifest.json`
- `metadata.json`
- `screens/intro.json`
- `screens/map.json`
- `screens/recap.json`

Open the public site:

```bash
open "$PUBLIC_URL"
```

On Linux, use `xdg-open "$PUBLIC_URL"` instead.

## 9. Simulate Anonymous Global Progress

Progress is intentionally not tied to a user, cookie, or bearer token. The backend
stores one global progress row per experience.

Read the initial progress:

```bash
curl -sS "$BASE/experiences/$EXPERIENCE_ID/progress" | python -m json.tool
```

Save a checkpoint:

```bash
curl -sS -X PUT "$BASE/experiences/$EXPERIENCE_ID/progress" \
  -H "Content-Type: application/json" \
  -d '{
    "current_screen_id": "map",
    "completed_screen_ids": ["intro", "map"],
    "last_checkpoint": "map",
    "interaction_state": {"demo": "manual checkpoint"}
  }' \
  | python -m json.tool
```

Read it back from a fresh request:

```bash
curl -sS "$BASE/experiences/$EXPERIENCE_ID/progress" | python -m json.tool
```

Restart the server and run the same `GET` again. Because the simulation uses a
file-backed SQLite database, the saved checkpoint should still be there.

## 10. Simulate Failure Paths

Bad chapter text:

```bash
curl -sS -X POST "$BASE/chapters/text" \
  -H "Content-Type: application/json" \
  -d '{"text":"too short"}' \
  | python -m json.tool
```

Expected error code: `CHAPTER_TOO_SHORT`.

Unknown job:

```bash
curl -sS "$BASE/generation-jobs/no-such-job" | python -m json.tool
```

Expected error code: `JOB_NOT_FOUND`.

Band sever/load-bearing checks:

```bash
python chapterstage_backend/tests/test_band_transport_factory.py
python chapterstage_backend/tests/test_m4_band_loadbearing.py
```

Expected result: severing the Band transport stalls the workflow and prevents a
completed module/public URL.

## 11. Optional Live Band Transport

Only use this when you want real Band SDK calls.

```bash
python -m pip install -r chapterstage_backend/requirements-live.txt
export BAND_TRANSPORT_MODE=live
export BAND_API_KEY=replace-me
export BAND_API_URL=https://app.band.ai
export BAND_WS_URL=wss://app.band.ai/api/v1/socket/websocket
export BAND_AGENT_UUID_COORDINATOR=replace-me
export BAND_AGENT_UUID_STRUCTURE=replace-me
export BAND_AGENT_UUID_PEDAGOGY=replace-me
export BAND_AGENT_UUID_BRAINSTORM=replace-me
export BAND_AGENT_UUID_VISUAL_BUILDER=replace-me
export BAND_AGENT_UUID_VERIFIER=replace-me
```

Then restart the server and repeat steps 4-8. Live mode fails fast if the SDK or
required credentials are missing. Keep `BAND_TRANSPORT_MODE=test` for local gates
and deterministic development.

## 12. Cleanup

Stop the server, then remove local simulation artifacts:

```bash
rm -f chapterstage_backend/chapterstage_flow.db
rm -rf chapterstage_backend/static/generated
rm -rf /tmp/chapterstage-flow
```

## Troubleshooting

- `ModuleNotFoundError: app`: start uvicorn with `--app-dir chapterstage_backend`.
- Job fails after enabling Ollama: confirm `ollama serve` is running and
  `OLLAMA_MODEL` matches an installed model.
- Job fails in live Band mode: check `BAND_API_KEY`,
  `BAND_AGENT_UUID_COORDINATOR`, and per-agent UUID env vars.
- Public URL points to `localhost:8000`: set `API_BASE_URL` and
  `PUBLIC_SITE_BASE_URL` before starting the server.
- Progress does not persist after restart: confirm `DATABASE_URL` points to a
  file-backed SQLite database, not a temp file.
