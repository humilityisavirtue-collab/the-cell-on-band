"""Failure diagnostics gate: provider errors are visible through status/trace/SSE."""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

_TMP = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///%s/test.db" % _TMP.name
os.environ["GENERATED_SITE_ROOT"] = _TMP.name + "/static"
os.environ["BAND_TRANSPORT_MODE"] = "test"
os.environ["CHAPTERSTAGE_ENV_FILE"] = _TMP.name + "/missing.env"
for _key in ("LLM_PROVIDER", "OLLAMA_MODEL", "OLLAMA_BASE_URL"):
    os.environ.pop(_key, None)

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402
from app.services import chapter_agents  # noqa: E402
from app.services.llm.base import LLMProviderError  # noqa: E402

FAILURES: list[str] = []
RAN: list[str] = []


def check(name, cond, receipt=""):
    RAN.append(name)
    print("  [%s] %s" % ("PASS" if cond else "FAIL", name))
    if receipt and not cond:
        print("         receipt: %s" % receipt)
    if not cond:
        FAILURES.append(name)


class BadJsonProvider:
    name = "fake"
    model = "fake-json"

    def generate_json(self, messages, schema, model=None):
        raise LLMProviderError(
            "Provider returned invalid JSON. Preview: 'not json from provider'")


def main():
    print("test_job_failure_diagnostics.py — provider failure diagnostics")
    original_create = chapter_agents.create_provider
    os.environ["OLLAMA_MODEL"] = "fake-local"
    chapter_agents.create_provider = lambda: BadJsonProvider()
    try:
        with TestClient(app) as c:
            good_text = "Processes are running program instances. " * 40
            r = c.post("/api/v1/chapters/text",
                       json={"book_title": "OS", "chapter_title": "Processes",
                             "text": good_text})
            chapter_id = r.json()["chapter_id"]
            r = c.post("/api/v1/generation-jobs",
                       json={"chapter_id": chapter_id})
            job_id = r.json()["job_id"]

            status = None
            for _ in range(10):
                status = c.get("/api/v1/generation-jobs/%s" % job_id).json()
                if status["status"] == "failed_agent_workflow":
                    break
                time.sleep(0.05)

            check("status exposes provider failure message and Band room",
                  status["status"] == "failed_agent_workflow"
                  and status["band_room_id"]
                  and "structure failed" in status["error"]["message"]
                  and "Provider returned invalid JSON" in status["error"]["message"]
                  and "not json from provider" in status["error"]["message"],
                  receipt=status)

            r = c.get("/api/v1/generation-jobs/%s/trace" % job_id)
            trace = r.json()
            check("trace endpoint records early workflow error",
                  r.status_code == 200
                  and len(trace["events"]) == 1
                  and trace["events"][0]["event_type"] == "workflow_error"
                  and trace["events"][0]["agent_name"] == "structure"
                  and trace["events"][0]["payload"]["error_type"]
                  == "LLMProviderError",
                  receipt=trace)

            with c.stream("GET", "/api/v1/generation-jobs/%s/events" % job_id) as s:
                body = "".join(s.iter_text())
            check("SSE replay includes agent_error before job_failed",
                  "event: agent_error" in body
                  and "event: job_failed" in body
                  and body.index("event: agent_error")
                  < body.index("event: job_failed"),
                  receipt=body[:800])
    finally:
        chapter_agents.create_provider = original_create
        os.environ.pop("OLLAMA_MODEL", None)

    print("%d/%d gate checks passed" % (len(RAN) - len(FAILURES), len(RAN)))
    if FAILURES:
        print("GATE FAIL: %s" % ", ".join(FAILURES))
        sys.exit(1)
    print("GATE PASS — failed provider generation is visible in status, trace, "
          "and SSE diagnostics.")
    sys.exit(0)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    main()
