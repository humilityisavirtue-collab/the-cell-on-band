"""Gate for the one-command local ChapterStage flow runner."""
from __future__ import annotations

import io
import json
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

from scripts import run_flow  # noqa: E402

FAILURES: list[str] = []
RAN: list[str] = []


def check(name, cond, receipt=""):
    RAN.append(name)
    print("  [%s] %s" % ("PASS" if cond else "FAIL", name))
    if receipt and not cond:
        print("         receipt: %s" % receipt)
    if not cond:
        FAILURES.append(name)


class FakeClient:
    def __init__(self, scenario="success"):
        self.scenario = scenario
        self.calls = []
        self.status_calls = 0

    def request(self, method, url, json_body=None, headers=None, timeout=15):
        self.calls.append((method, url, json_body))
        path = urlparse(url).path
        if path == "/api/v1/health":
            if self.scenario == "missing_server":
                return _json_response(503, {"status": "down"})
            return _json_response(200, {"status": "ok", "version": "0.1.0"})
        if path == "/api/v1/chapters/text" and method == "POST":
            return _json_response(201, {
                "chapter_id": "chapter-1",
                "book_id": "book-1",
                "title": json_body.get("chapter_title", "Chapter"),
                "source_type": "text",
                "created_at": "2026-06-16T00:00:00",
            })
        if path == "/api/v1/generation-jobs" and method == "POST":
            return _json_response(202, {
                "job_id": "job-1",
                "chapter_id": json_body["chapter_id"],
                "status": "queued",
                "status_url": "http://test/api/v1/generation-jobs/job-1",
                "events_url": "http://test/api/v1/generation-jobs/job-1/events",
            })
        if path == "/api/v1/generation-jobs/job-1" and method == "GET":
            self.status_calls += 1
            if self.scenario == "status_timeout":
                if self.status_calls == 1:
                    return _json_response(200, _status("queued", progress=0.0))
                raise run_flow.FlowError("Timed out waiting for %s" % url)
            if self.scenario == "failed":
                return _json_response(200, _status("failed_agent_workflow", error={
                    "code": "AGENT_WORKFLOW_FAILED",
                    "message": "structure failed: Provider returned invalid JSON.",
                }))
            if self.status_calls == 1:
                return _json_response(200, _status("building_site", progress=0.72))
            return _json_response(200, _status("completed", progress=1.0))
        if path == "/api/v1/generation-jobs/job-1/trace":
            events = []
            if self.scenario == "failed":
                events.append({
                    "id": "trace-1",
                    "agent_name": "structure",
                    "event_type": "workflow_error",
                    "title": "Workflow failed at structure",
                    "message": "structure failed: Provider returned invalid JSON.",
                    "payload": {"error_stage": "structure"},
                    "created_at": "2026-06-16T00:00:00",
                })
            else:
                events.append({
                    "id": "trace-1",
                    "agent_name": "structure",
                    "event_type": "handoff",
                    "title": "structure to brainstorm",
                    "message": "Delivered knowledge_pack envelope.",
                    "payload": {},
                    "created_at": "2026-06-16T00:00:00",
                })
            return _json_response(200, {
                "job_id": "job-1",
                "band_room_id": "room-job-1",
                "events": events,
            })
        if path == "/api/v1/generation-jobs/job-1/events":
            return run_flow.HttpResponse(
                status_code=200,
                headers={"content-type": "text/event-stream"},
                body=b"event: job_progress\ndata: {}\n\nevent: job_failed\ndata: {}\n\n"
                if self.scenario == "failed"
                else b"event: job_progress\ndata: {}\n\nevent: experience_ready\ndata: {}\n\n",
            )
        if path == "/api/v1/experiences/exp-1":
            return _json_response(200, {
                "experience_id": "exp-1",
                "job_id": "job-1",
                "public_url": "http://public.test/exp-1/index.html",
                "metadata": {},
                "created_at": "2026-06-16T00:00:00",
            })
        if path == "/exp-1/index.html":
            return run_flow.HttpResponse(
                status_code=200, headers={"content-type": "text/html"},
                body=b"<html><body>ok</body></html>")
        if path == "/api/v1/experiences/exp-1/progress":
            if method == "PUT":
                return _json_response(200, dict(json_body, experience_id="exp-1"))
            return _json_response(200, {
                "experience_id": "exp-1",
                "current_screen_id": "map",
                "completed_screen_ids": ["intro", "map"],
                "last_checkpoint": "map",
                "interaction_state": {},
            })
        return _json_response(404, {"error": "unexpected %s %s" % (method, url)})


def _json_response(status_code, payload):
    return run_flow.HttpResponse(
        status_code=status_code,
        headers={"content-type": "application/json"},
        body=json.dumps(payload).encode("utf-8"),
    )


def _status(status, progress=0.18, error=None):
    return {
        "job_id": "job-1",
        "chapter_id": "chapter-1",
        "status": status,
        "progress": progress,
        "current_step": "Completed" if status == "completed" else "Working",
        "band_room_id": "room-job-1",
        "experience_id": "exp-1" if status == "completed" else None,
        "public_url": "http://public.test/exp-1/index.html"
        if status == "completed" else None,
        "error": error,
        "created_at": "2026-06-16T00:00:00",
        "updated_at": "2026-06-16T00:00:00",
    }


def _payload_file(root):
    path = Path(root) / "payload.json"
    path.write_text(json.dumps({
        "book_title": "Test Book",
        "chapter_title": "Test Chapter",
        "text": "A chapter sentence for testing. " * 40,
    }), encoding="utf-8")
    return path


def _options(root, base_url="http://api.test"):
    return run_flow.FlowOptions(
        base_url=run_flow._normalize_base_url(base_url),
        payload=_payload_file(root),
        out_dir=Path(root) / "artifacts",
        timeout_seconds=2,
        poll_interval=0,
    )


def main():
    print("test_run_flow_script.py - one-command flow runner")

    tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    client = FakeClient("success")
    stdout = io.StringIO()
    code = run_flow.run_flow(_options(tmp.name), client=client, stdout=stdout)
    out_dir = Path(tmp.name) / "artifacts"
    expected_files = {
        "chapter_response.json", "job_response.json", "job_status_history.json",
        "job_status_final.json", "trace.json", "events.sse",
        "experience_response.json", "progress_initial.json",
        "progress_saved.json", "progress_final.json",
    }
    check("happy path exits 0 and writes expected artifacts",
          code == 0
          and expected_files.issubset({p.name for p in out_dir.iterdir()})
          and "public_url=http://public.test/exp-1/index.html" in stdout.getvalue(),
          receipt=stdout.getvalue())
    check("base URL override is normalized for API calls",
          client.calls[0][1] == "http://api.test/api/v1/health",
          receipt=client.calls[:2])

    tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    client = FakeClient("failed")
    stdout = io.StringIO()
    code = run_flow.run_flow(_options(tmp.name), client=client, stdout=stdout)
    out_dir = Path(tmp.name) / "artifacts"
    final_status = json.loads((out_dir / "job_status_final.json").read_text())
    trace = json.loads((out_dir / "trace.json").read_text())
    events = (out_dir / "events.sse").read_text()
    check("failed job exits 1 and preserves diagnostics",
          code == 1
          and final_status["status"] == "failed_agent_workflow"
          and trace["events"][0]["event_type"] == "workflow_error"
          and "job_failed" in events
          and "structure failed" in stdout.getvalue(),
          receipt=stdout.getvalue())

    tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    client = FakeClient("missing_server")
    stdout = io.StringIO()
    code = run_flow.run_flow(_options(tmp.name), client=client, stdout=stdout)
    check("failed health check exits before posting chapter",
          code == 1 and len(client.calls) == 1 and "Health check" in stdout.getvalue(),
          receipt=stdout.getvalue())

    tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    client = FakeClient("status_timeout")
    stdout = io.StringIO()
    code = run_flow.run_flow(_options(tmp.name), client=client, stdout=stdout)
    out_dir = Path(tmp.name) / "artifacts"
    final_status = json.loads((out_dir / "job_status_final.json").read_text())
    check("mid-poll timeout exits 1 with latest status and diagnostics",
          code == 1
          and final_status["status"] == "queued"
          and (out_dir / "trace.json").is_file()
          and (out_dir / "events.sse").is_file()
          and "Timed out waiting" in stdout.getvalue(),
          receipt=stdout.getvalue())

    parsed = run_flow.parse_args([
        "--base-url", "http://override.test",
        "--payload", str(_payload_file(tmp.name)),
        "--out-dir", str(Path(tmp.name) / "custom"),
        "--timeout-seconds", "3",
        "--poll-interval", "0.1",
    ])
    check("CLI overrides parse into runner options",
          parsed.base_url == "http://override.test/api/v1"
          and parsed.payload == Path(tmp.name) / "payload.json"
          and parsed.out_dir == Path(tmp.name) / "custom"
          and parsed.timeout_seconds == 3
          and parsed.poll_interval == 0.1,
          receipt=parsed)

    print("%d/%d gate checks passed" % (len(RAN) - len(FAILURES), len(RAN)))
    if FAILURES:
        print("GATE FAIL: %s" % ", ".join(FAILURES))
        sys.exit(1)
    print("GATE PASS - flow runner covers happy path, failures, health checks, "
          "and CLI overrides.")
    sys.exit(0)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    main()
