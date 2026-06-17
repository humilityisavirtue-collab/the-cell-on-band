"""Run the local ChapterStage API -> job -> site -> progress flow.

The script expects FastAPI to already be running. It writes all artifacts for the
run into a repo-local output directory and exits nonzero with trace details when
the job fails.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

BACKEND_DIR = Path(__file__).resolve().parents[1]
DEFAULT_PAYLOAD = BACKEND_DIR / "examples" / "kids_story_payload.json"
DEFAULT_OUT_DIR = BACKEND_DIR / ".local" / "testing-flow" / "latest"

sys.path.insert(0, str(BACKEND_DIR))
from app.config import load_env_file  # noqa: E402

load_env_file(BACKEND_DIR / ".env")


class FlowError(RuntimeError):
    pass


@dataclass
class FlowOptions:
    base_url: str
    payload: Path
    out_dir: Path
    timeout_seconds: float = 60
    poll_interval: float = 0.5
    open_browser: bool = False


@dataclass
class HttpResponse:
    status_code: int
    headers: dict[str, str]
    body: bytes

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")

    def json(self) -> Any:
        return json.loads(self.text)


class UrllibClient:
    def request(
            self, method: str, url: str, json_body: Any | None = None,
            headers: dict[str, str] | None = None,
            timeout: float = 15) -> HttpResponse:
        request_headers = dict(headers or {})
        data = None
        if json_body is not None:
            data = json.dumps(json_body).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")
        req = urllib.request.Request(
            url, data=data, headers=request_headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return HttpResponse(
                    status_code=response.status,
                    headers=dict(response.headers.items()),
                    body=response.read(),
                )
        except urllib.error.HTTPError as exc:
            return HttpResponse(
                status_code=exc.code,
                headers=dict(exc.headers.items()),
                body=exc.read(),
            )
        except TimeoutError as exc:
            raise FlowError("Timed out waiting for %s" % url) from exc
        except urllib.error.URLError as exc:
            raise FlowError("Could not reach %s: %s" % (url, exc.reason)) from exc


def parse_args(argv: list[str] | None = None) -> FlowOptions:
    parser = argparse.ArgumentParser(
        description="Run the ChapterStage local API flow against a running server.")
    parser.add_argument("--base-url", default=_default_base_url(),
                        help="API base URL, with or without /api/v1.")
    parser.add_argument("--payload", default=str(DEFAULT_PAYLOAD),
                        help="Chapter payload JSON file.")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR),
                        help="Directory for flow artifacts.")
    parser.add_argument("--timeout-seconds", type=float, default=60,
                        help="Maximum time to wait for job completion.")
    parser.add_argument("--poll-interval", type=float, default=0.5,
                        help="Seconds between job status polls.")
    parser.add_argument("--open", action="store_true", dest="open_browser",
                        help="Open the generated public URL on success.")
    args = parser.parse_args(argv)
    return FlowOptions(
        base_url=_normalize_base_url(args.base_url),
        payload=Path(args.payload),
        out_dir=Path(args.out_dir),
        timeout_seconds=args.timeout_seconds,
        poll_interval=args.poll_interval,
        open_browser=args.open_browser,
    )


def run_flow(
        options: FlowOptions, client=None, opener=None,
        stdout: TextIO | None = None) -> int:
    out = stdout or sys.stdout
    http = client or UrllibClient()
    open_url = opener or webbrowser.open
    options.out_dir.mkdir(parents=True, exist_ok=True)

    try:
        _print(out, "ChapterStage flow")
        _print(out, "API: %s" % options.base_url)
        _print(out, "Artifacts: %s" % options.out_dir)
        _healthcheck(http, options)

        payload = _read_json(options.payload)
        chapter = _request_json(
            http, "POST", _url(options, "/chapters/text"), json_body=payload)
        _write_json(options.out_dir / "chapter_response.json", chapter)
        chapter_id = chapter["chapter_id"]
        _print(out, "chapter_id=%s" % chapter_id)

        job_payload = {
            "chapter_id": chapter_id,
            "audience_level": "beginner",
            "experience_style": "visual_story",
        }
        job = _request_json(
            http, "POST", _url(options, "/generation-jobs"),
            json_body=job_payload)
        _write_json(options.out_dir / "job_response.json", job)
        job_id = job["job_id"]
        _print(out, "job_id=%s" % job_id)

        try:
            final_status = _poll_job(http, options, job_id, out)
        except FlowError:
            trace = _safe_fetch_trace(http, options, job_id)
            events = _fetch_events(http, options, job_id)
            _write_json(options.out_dir / "trace.json", trace)
            (options.out_dir / "events.sse").write_text(events, encoding="utf-8")
            raise
        _write_json(options.out_dir / "job_status_final.json", final_status)
        trace = _safe_fetch_trace(http, options, job_id)
        events = _fetch_events(http, options, job_id)
        _write_json(options.out_dir / "trace.json", trace)
        (options.out_dir / "events.sse").write_text(events, encoding="utf-8")

        if final_status["status"] != "completed":
            _print_failure(out, final_status, trace, options.out_dir)
            return 1

        experience = _verify_experience(http, options, final_status)
        _write_json(options.out_dir / "experience_response.json", experience)
        progress = _exercise_progress(http, options, final_status["experience_id"])
        _write_json(options.out_dir / "progress_initial.json", progress["initial"])
        _write_json(options.out_dir / "progress_saved.json", progress["saved"])
        _write_json(options.out_dir / "progress_final.json", progress["final"])

        public_url = final_status["public_url"]
        _print(out, "PASS completed")
        _print(out, "experience_id=%s" % final_status["experience_id"])
        _print(out, "public_url=%s" % public_url)
        _print(out, "trace_events=%s" % len(trace.get("events", [])))
        if options.open_browser and public_url:
            open_url(public_url)
        return 0
    except FlowError as exc:
        _print(out, "FAIL %s" % exc)
        _print(out, "Artifacts: %s" % options.out_dir)
        return 1


def main(argv: list[str] | None = None) -> int:
    return run_flow(parse_args(argv))


def _default_base_url() -> str:
    return _normalize_base_url(os.environ.get(
        "API_BASE_URL", "http://127.0.0.1:8000"))


def _normalize_base_url(value: str) -> str:
    base = value.rstrip("/")
    if base.endswith("/api/v1"):
        return base
    return base + "/api/v1"


def _url(options: FlowOptions, path: str) -> str:
    return options.base_url.rstrip("/") + path


def _healthcheck(http, options: FlowOptions) -> None:
    try:
        data = _request_json(http, "GET", _url(options, "/health"))
    except FlowError as exc:
        raise FlowError("Health check failed: %s" % exc) from exc
    if data.get("status") != "ok":
        raise FlowError("Health check returned unexpected payload: %r" % data)


def _request_json(
        http, method: str, url: str, json_body: Any | None = None,
        timeout: float = 15) -> Any:
    response = http.request(method, url, json_body=json_body, timeout=timeout)
    if response.status_code < 200 or response.status_code >= 300:
        raise FlowError("HTTP %s %s returned %s: %s" % (
            method, url, response.status_code, response.text[:500]))
    try:
        return response.json()
    except json.JSONDecodeError as exc:
        raise FlowError("HTTP %s %s returned invalid JSON: %s" % (
            method, url, response.text[:500])) from exc


def _request_text(http, method: str, url: str, timeout: float = 15) -> str:
    response = http.request(method, url, timeout=timeout)
    if response.status_code < 200 or response.status_code >= 300:
        raise FlowError("HTTP %s %s returned %s: %s" % (
            method, url, response.status_code, response.text[:500]))
    return response.text


def _poll_job(http, options: FlowOptions, job_id: str, out: TextIO) -> dict:
    history = []
    deadline = time.monotonic() + options.timeout_seconds
    final_status = None
    last_printed = None
    while time.monotonic() <= deadline:
        try:
            status = _request_json(
                http, "GET", _url(options, "/generation-jobs/%s" % job_id))
        except FlowError:
            if history:
                _write_json(options.out_dir / "job_status_final.json", history[-1])
            raise
        history.append(status)
        _write_json(options.out_dir / "job_status_history.json", history)
        visible_status = (
            status.get("status"), float(status.get("progress", 0)),
            status.get("current_step") or "")
        if visible_status != last_printed:
            _print(out, "%s %.2f %s" % visible_status)
            last_printed = visible_status
        if status.get("status") in {"completed", "failed_agent_workflow"}:
            final_status = status
            break
        time.sleep(options.poll_interval)
    if final_status is None:
        if history:
            _write_json(options.out_dir / "job_status_final.json", history[-1])
        raise FlowError("Job %s did not finish within %.1fs" % (
            job_id, options.timeout_seconds))
    return final_status


def _fetch_trace(http, options: FlowOptions, job_id: str) -> dict:
    return _request_json(
        http, "GET", _url(options, "/generation-jobs/%s/trace" % job_id))


def _safe_fetch_trace(http, options: FlowOptions, job_id: str) -> dict:
    try:
        return _fetch_trace(http, options, job_id)
    except FlowError as exc:
        return {
            "job_id": job_id,
            "band_room_id": None,
            "events": [],
            "error": "Unable to fetch trace: %s" % exc,
        }


def _fetch_events(http, options: FlowOptions, job_id: str) -> str:
    try:
        return _request_text(
            http, "GET", _url(options, "/generation-jobs/%s/events" % job_id),
            timeout=10)
    except FlowError as exc:
        return "Unable to fetch SSE events: %s\n" % exc


def _verify_experience(http, options: FlowOptions, status: dict) -> dict:
    experience_id = status.get("experience_id")
    public_url = status.get("public_url")
    if not experience_id or not public_url:
        raise FlowError("Completed job is missing experience_id/public_url.")
    experience = _request_json(
        http, "GET", _url(options, "/experiences/%s" % experience_id))
    html = _request_text(http, "GET", public_url, timeout=15)
    if "<html" not in html.lower():
        raise FlowError("Public URL did not return an HTML document.")
    return experience


def _exercise_progress(http, options: FlowOptions, experience_id: str) -> dict:
    progress_url = _url(options, "/experiences/%s/progress" % experience_id)
    initial = _request_json(http, "GET", progress_url)
    payload = {
        "current_screen_id": "map",
        "completed_screen_ids": ["intro", "map"],
        "last_checkpoint": "map",
        "interaction_state": {"runner": "chapterstage flow"},
    }
    saved = _request_json(http, "PUT", progress_url, json_body=payload)
    final = _request_json(http, "GET", progress_url)
    if final.get("current_screen_id") != "map":
        raise FlowError("Progress readback did not preserve current_screen_id.")
    return {"initial": initial, "saved": saved, "final": final}


def _print_failure(out: TextIO, status: dict, trace: dict, out_dir: Path) -> None:
    _print(out, "FAIL job_id=%s status=%s" % (
        status.get("job_id"), status.get("status")))
    error = status.get("error") or {}
    if error:
        _print(out, "error=%s: %s" % (
            error.get("code", "UNKNOWN"), error.get("message", "")))
    event = _first_error_event(trace)
    if event:
        _print(out, "trace=%s %s" % (
            event.get("agent_name"), event.get("message")))
    _print(out, "Artifacts: %s" % out_dir)


def _first_error_event(trace: dict) -> dict | None:
    for event in trace.get("events", []):
        if "error" in event.get("event_type", ""):
            return event
    events = trace.get("events", [])
    return events[-1] if events else None


def _read_json(path: Path) -> Any:
    if not path.is_file():
        raise FlowError("Payload file does not exist: %s" % path)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise FlowError("Payload file is not valid JSON: %s" % path) from exc


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _print(out: TextIO, text: str) -> None:
    print(text, file=out)


if __name__ == "__main__":
    raise SystemExit(main())
