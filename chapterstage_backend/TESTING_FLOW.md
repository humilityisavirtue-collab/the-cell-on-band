# ChapterStage Testing Flow

This guide shows the normal local test flow first: one CLI command against an
already-running FastAPI server. Curl and Postman are still included for manual
debugging, but they should not be the daily happy path anymore.

The flow covers:

- create a chapter from `examples/kids_story_payload.json`
- start a generation job
- poll until completion or agent failure
- save job status, trace, and SSE artifacts
- verify the generated public experience returns HTML
- save and read back anonymous global progress

All generated test artifacts stay inside the repo under
`chapterstage_backend/.local/testing-flow/`.

## 1. Prepare Local Environment

From the repository root:

```bash
python3 -m venv venv
./venv/bin/python -m pip install --upgrade pip
./venv/bin/python -m pip install -r chapterstage_backend/requirements.txt
```

The backend and flow runner both load `chapterstage_backend/.env`
automatically. You do not need to export environment variables for the normal
flow.

Recommended `.env` values for local test mode:

```dotenv
APP_ENV=development
API_BASE_URL=http://127.0.0.1:8000
PUBLIC_SITE_BASE_URL=http://127.0.0.1:8000/public/experiences
DATABASE_URL=sqlite+aiosqlite:///./chapterstage_backend/chapterstage_flow.db
GENERATED_SITE_ROOT=./chapterstage_backend/static/generated
BAND_TRANSPORT_MODE=test
LOG_LEVEL=INFO

# Ollama-first provider mode.
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5:7b
```

Adjust `OLLAMA_MODEL` to the exact name shown by:

```bash
ollama list
```

If you are using the Ollama macOS app, confirm the local API is available:

```bash
curl -sS http://localhost:11434/api/tags | ./venv/bin/python -m json.tool
```

## 2. Start The API Server

Run this from the repository root and leave it running:

```bash
./venv/bin/uvicorn app.main:app \
  --app-dir chapterstage_backend \
  --host 127.0.0.1 \
  --port 8000 \
  --reload
```

The flow runner does not start or stop uvicorn. If the server is down, it fails
at `GET /health` before creating any chapter.

## 3. Run The Full Flow With One Command

In a second terminal, from the repository root:

```bash
./venv/bin/python chapterstage_backend/scripts/run_flow.py
```

Defaults:

- API base URL: `API_BASE_URL` from `.env`, falling back to
  `http://127.0.0.1:8000/api/v1`
- payload: `chapterstage_backend/examples/kids_story_payload.json`
- artifacts: `chapterstage_backend/.local/testing-flow/latest/`
- timeout: `60` seconds
- poll interval: `0.5` seconds

Useful overrides:

```bash
./venv/bin/python chapterstage_backend/scripts/run_flow.py \
  --timeout-seconds 120 \
  --poll-interval 1
```

```bash
./venv/bin/python chapterstage_backend/scripts/run_flow.py \
  --base-url http://127.0.0.1:8000 \
  --payload chapterstage_backend/examples/kids_story_payload.json \
  --out-dir chapterstage_backend/.local/testing-flow/qwen-run \
  --open
```

Successful output ends with:

```text
PASS completed
experience_id=...
public_url=http://127.0.0.1:8000/public/experiences/.../index.html
```

The runner writes these artifacts on a normal completed or failed job:

- `chapter_response.json`
- `job_response.json`
- `job_status_history.json`
- `job_status_final.json`
- `trace.json`
- `events.sse`

On success it also writes:

- `experience_response.json`
- `progress_initial.json`
- `progress_saved.json`
- `progress_final.json`

## 4. Inspect Failed Runs

If the runner exits nonzero, start here:

```bash
./venv/bin/python -m json.tool \
  < chapterstage_backend/.local/testing-flow/latest/job_status_final.json
```

```bash
./venv/bin/python -m json.tool \
  < chapterstage_backend/.local/testing-flow/latest/trace.json
```

```bash
sed -n '1,160p' chapterstage_backend/.local/testing-flow/latest/events.sse
```

For provider issues, `job_status_final.json` should include `error.message`.
For workflow issues, `trace.json` should include a `workflow_error` event with
the failing stage and provider error preview when available.

## 5. Run Offline Gates

These tests use fake clients, temp databases, or deterministic test transports.
They do not require Ollama or live Band credentials.

```bash
set -e
./venv/bin/python chapterstage_backend/tests/test_run_flow_script.py
./venv/bin/python chapterstage_backend/tests/test_job_execution.py
./venv/bin/python chapterstage_backend/tests/test_job_failure_diagnostics.py
./venv/bin/python chapterstage_backend/tests/test_global_progress.py
./venv/bin/python chapterstage_backend/tests/test_api_jobs.py
```

Expected result: every script exits with `GATE PASS`.

## 6. Manual Debugging With Curl

Use this section when you want to inspect one API call at a time. These commands
also write artifacts under `chapterstage_backend/.local/testing-flow/manual/`.

```bash
export BASE=http://127.0.0.1:8000/api/v1
export FLOW_DIR=chapterstage_backend/.local/testing-flow/manual
mkdir -p "$FLOW_DIR"
```

Health:

```bash
curl -sS "$BASE/health" | ./venv/bin/python -m json.tool
```

Create a chapter:

```bash
curl -sS -X POST "$BASE/chapters/text" \
  -H "Content-Type: application/json" \
  --data @chapterstage_backend/examples/kids_story_payload.json \
  | tee "$FLOW_DIR/chapter_response.json" \
  | ./venv/bin/python -m json.tool
```

```bash
export CHAPTER_ID="$(
  ./venv/bin/python - <<'PY'
import json
from pathlib import Path
print(json.loads(Path("chapterstage_backend/.local/testing-flow/manual/chapter_response.json").read_text())["chapter_id"])
PY
)"
```

Start a generation job:

```bash
./venv/bin/python - <<'PY'
import json
import os
from pathlib import Path

payload = {
    "chapter_id": os.environ["CHAPTER_ID"],
    "audience_level": "beginner",
    "experience_style": "visual_story",
}
Path("chapterstage_backend/.local/testing-flow/manual/job_payload.json").write_text(
    json.dumps(payload, indent=2)
)
PY
```

```bash
curl -sS -X POST "$BASE/generation-jobs" \
  -H "Content-Type: application/json" \
  --data @"$FLOW_DIR/job_payload.json" \
  | tee "$FLOW_DIR/job_response.json" \
  | ./venv/bin/python -m json.tool
```

```bash
export JOB_ID="$(
  ./venv/bin/python - <<'PY'
import json
from pathlib import Path
print(json.loads(Path("chapterstage_backend/.local/testing-flow/manual/job_response.json").read_text())["job_id"])
PY
)"
```

Poll status:

```bash
./venv/bin/python - <<'PY'
import json
import os
import time
import urllib.request
from pathlib import Path

base = os.environ["BASE"]
job_id = os.environ["JOB_ID"]
history_path = Path("chapterstage_backend/.local/testing-flow/manual/job_status_history.json")
final_path = Path("chapterstage_backend/.local/testing-flow/manual/job_status_final.json")
history = []

for _ in range(120):
    with urllib.request.urlopen(f"{base}/generation-jobs/{job_id}") as response:
        payload = json.loads(response.read().decode("utf-8"))
    history.append(payload)
    history_path.write_text(json.dumps(history, indent=2))
    final_path.write_text(json.dumps(payload, indent=2))
    print(payload["status"], payload["progress"], payload.get("current_step"))
    if payload["status"] in {"completed", "failed_agent_workflow"}:
        break
    time.sleep(0.5)
else:
    raise SystemExit("job did not finish in time")

if payload["status"] != "completed":
    raise SystemExit(json.dumps(payload, indent=2))
PY
```

Fetch trace and SSE events:

```bash
curl -sS "$BASE/generation-jobs/$JOB_ID/trace" \
  | tee "$FLOW_DIR/trace.json" \
  | ./venv/bin/python -m json.tool
```

```bash
curl --max-time 10 -N "$BASE/generation-jobs/$JOB_ID/events" \
  | tee "$FLOW_DIR/events.sse"
```

Extract the generated experience ids:

```bash
export EXPERIENCE_ID="$(
  ./venv/bin/python - <<'PY'
import json
from pathlib import Path
print(json.loads(Path("chapterstage_backend/.local/testing-flow/manual/job_status_final.json").read_text())["experience_id"])
PY
)"
export PUBLIC_URL="$(
  ./venv/bin/python - <<'PY'
import json
from pathlib import Path
print(json.loads(Path("chapterstage_backend/.local/testing-flow/manual/job_status_final.json").read_text())["public_url"])
PY
)"
```

Verify metadata and public HTML:

```bash
curl -sS "$BASE/experiences/$EXPERIENCE_ID" \
  | tee "$FLOW_DIR/experience_response.json" \
  | ./venv/bin/python -m json.tool
```

```bash
curl -sS "$PUBLIC_URL" | sed -n '1,40p'
```

Test anonymous global progress:

```bash
curl -sS "$BASE/experiences/$EXPERIENCE_ID/progress" \
  | tee "$FLOW_DIR/progress_initial.json" \
  | ./venv/bin/python -m json.tool
```

```bash
curl -sS -X PUT "$BASE/experiences/$EXPERIENCE_ID/progress" \
  -H "Content-Type: application/json" \
  -d '{
    "current_screen_id": "map",
    "completed_screen_ids": ["intro", "map"],
    "last_checkpoint": "map",
    "interaction_state": {"demo": "manual checkpoint"}
  }' \
  | tee "$FLOW_DIR/progress_saved.json" \
  | ./venv/bin/python -m json.tool
```

```bash
curl -sS "$BASE/experiences/$EXPERIENCE_ID/progress" \
  | tee "$FLOW_DIR/progress_final.json" \
  | ./venv/bin/python -m json.tool
```

## 7. Manual Debugging With Postman

Create a Postman environment with:

- `base_url`: `http://127.0.0.1:8000/api/v1`
- `chapter_id`: blank initially
- `job_id`: blank initially
- `experience_id`: blank initially
- `public_url`: blank initially

Requests:

- Health: `GET {{base_url}}/health`
- Create chapter: `POST {{base_url}}/chapters/text`
  - Header: `Content-Type: application/json`
  - Body: raw JSON copied from `chapterstage_backend/examples/kids_story_payload.json`
  - Test script: `pm.environment.set("chapter_id", pm.response.json().chapter_id);`
- Start job: `POST {{base_url}}/generation-jobs`
  - Header: `Content-Type: application/json`
  - Body:

```json
{
  "chapter_id": "{{chapter_id}}",
  "audience_level": "beginner",
  "experience_style": "visual_story"
}
```

  - Test script: `pm.environment.set("job_id", pm.response.json().job_id);`
- Poll status: `GET {{base_url}}/generation-jobs/{{job_id}}`
  - Send repeatedly until `status` is `completed` or `failed_agent_workflow`
  - Test script:

```javascript
const body = pm.response.json();
if (body.experience_id) pm.environment.set("experience_id", body.experience_id);
if (body.public_url) pm.environment.set("public_url", body.public_url);
```

- Trace: `GET {{base_url}}/generation-jobs/{{job_id}}/trace`
- Events: `GET {{base_url}}/generation-jobs/{{job_id}}/events`
  - If Postman does not display SSE cleanly, use the curl event command above.
- Experience metadata: `GET {{base_url}}/experiences/{{experience_id}}`
- Progress read: `GET {{base_url}}/experiences/{{experience_id}}/progress`
- Progress save: `PUT {{base_url}}/experiences/{{experience_id}}/progress`
  - Header: `Content-Type: application/json`
  - Body:

```json
{
  "current_screen_id": "map",
  "completed_screen_ids": ["intro", "map"],
  "last_checkpoint": "map",
  "interaction_state": {"demo": "postman checkpoint"}
}
```

## 8. Optional Live Band Transport

Only use this when you want real Band SDK calls.

```bash
./venv/bin/python -m pip install -r chapterstage_backend/requirements-live.txt
```

Then set live values in `chapterstage_backend/.env`:

```dotenv
BAND_TRANSPORT_MODE=live
BAND_API_KEY=replace-me
BAND_API_URL=https://app.band.ai
BAND_WS_URL=wss://app.band.ai/api/v1/socket/websocket
BAND_AGENT_UUID_COORDINATOR=replace-me
BAND_AGENT_UUID_STRUCTURE=replace-me
BAND_AGENT_UUID_PEDAGOGY=replace-me
BAND_AGENT_UUID_BRAINSTORM=replace-me
BAND_AGENT_UUID_VISUAL_BUILDER=replace-me
BAND_AGENT_UUID_VERIFIER=replace-me
```

Restart the server before running the flow again. Keep
`BAND_TRANSPORT_MODE=test` for deterministic local development.

## 9. Cleanup

Stop uvicorn, then remove local artifacts:

```bash
rm -f chapterstage_backend/chapterstage_flow.db
rm -rf chapterstage_backend/static/generated
rm -rf chapterstage_backend/.local/testing-flow
```

## Troubleshooting

- `ModuleNotFoundError: app`: start uvicorn with `--app-dir chapterstage_backend`.
- Health check fails in `run_flow.py`: confirm uvicorn is running on the same
  port as `API_BASE_URL` in `.env`.
- Ollama generation fails: confirm the Ollama app/server is running and
  `OLLAMA_MODEL` exactly matches `ollama list`.
- Job fails with invalid provider JSON: inspect `trace.json` and `events.sse`
  from the runner output directory.
- Public URL points to the wrong host: update `API_BASE_URL` and
  `PUBLIC_SITE_BASE_URL` in `.env`, then restart uvicorn.
- Progress does not survive restart: confirm `DATABASE_URL` points to a
  file-backed SQLite database.
