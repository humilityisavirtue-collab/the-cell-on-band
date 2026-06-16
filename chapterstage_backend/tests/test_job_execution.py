"""Phase 6 gate: job execution, SSE replay, trace, and public URL."""
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

FAILURES: list[str] = []
RAN: list[str] = []


def check(name, cond, receipt=""):
    RAN.append(name)
    print("  [%s] %s" % ("PASS" if cond else "FAIL", name))
    if receipt and not cond:
        print("         receipt: %s" % receipt)
    if not cond:
        FAILURES.append(name)


def main():
    print("test_job_execution.py — job execution + publish")
    with TestClient(app) as c:
        good_text = "Processes are running program instances. " * 40
        r = c.post("/api/v1/chapters/text",
                   json={"book_title": "OS", "chapter_title": "Processes",
                         "text": good_text})
        chapter_id = r.json()["chapter_id"]
        r = c.post("/api/v1/generation-jobs",
                   json={"chapter_id": chapter_id, "audience_level": "beginner",
                         "experience_style": "visual_story",
                         "target_screen_count": 3, "enable_auto_brainstorm": True})
        job = r.json()
        job_id = job["job_id"]
        check("POST /generation-jobs returns accepted job",
              r.status_code == 202 and job["events_url"].endswith("/events"),
              receipt=r.text)

        status = None
        for _ in range(10):
            status = c.get("/api/v1/generation-jobs/%s" % job_id).json()
            if status["status"] == "completed":
                break
            time.sleep(0.05)
        check("background job reaches completed with public URL",
              status["status"] == "completed" and status["public_url"],
              receipt=status)

        site_path = Path(os.environ["GENERATED_SITE_ROOT"]) / status["experience_id"]
        check("published modular site exists",
              (site_path / "index.html").is_file()
              and (site_path / "manifest.json").is_file()
              and (site_path / "screens" / "intro.json").is_file(),
              receipt=str(site_path))

        r = c.get("/api/v1/experiences/%s" % status["experience_id"])
        check("experience metadata endpoint returns public URL",
              r.status_code == 200
              and r.json()["experience_id"] == status["experience_id"]
              and r.json()["public_url"] == status["public_url"],
              receipt=r.text)

        r = c.get("/api/v1/generation-jobs", params={"limit": 5, "offset": 0})
        check("recent jobs endpoint lists generated job",
              r.status_code == 200
              and any(row["job_id"] == job_id for row in r.json()["jobs"]),
              receipt=r.text)

        r = c.get("/api/v1/generation-jobs/%s/trace" % job_id)
        trace = r.json()
        check("trace endpoint returns Band handoff events",
              r.status_code == 200 and len(trace["events"]) == 4,
              receipt=r.text)

        with c.stream("GET", "/api/v1/generation-jobs/%s/events" % job_id) as s:
            body = "".join(s.iter_text())
        check("SSE endpoint replays progress and ready events",
              "event: job_progress" in body and "event: experience_ready" in body,
              receipt=body[:500])

    print("%d/%d gate checks passed" % (len(RAN) - len(FAILURES), len(RAN)))
    if FAILURES:
        print("GATE FAIL: %s" % ", ".join(FAILURES))
        sys.exit(1)
    print("GATE PASS — jobs execute through BandService, publish modular sites, "
          "and expose trace/SSE progress.")
    sys.exit(0)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    main()
