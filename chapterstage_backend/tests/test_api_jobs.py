"""test_api_jobs.py — M1 gate (handoff §9 round-trip + §10 rejections).

Round-trips a text chapter -> job row -> status fetch, and asserts the REAL
failure modes are rejected with the exact §10 error codes (a pass-check that
cannot fail is theater). Uses a throwaway temp DB so it never touches dev data.

Run (in the backend venv):
  apps/band/chapterstage_backend/.venv/Scripts/python \
      apps/band/chapterstage_backend/tests/test_api_jobs.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

# isolate: throwaway DB + tiny upload cap + temp static dir, BEFORE importing app
# ignore_cleanup_errors: on Windows the async sqlite engine still holds test.db at
# interpreter exit; the gate has already passed by then, so don't let teardown noise.
_TMP = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///%s/test.db" % _TMP.name
os.environ["GENERATED_SITE_ROOT"] = _TMP.name + "/static"
os.environ["MAX_UPLOAD_MB"] = "1"
os.environ["CHAPTERSTAGE_ENV_FILE"] = _TMP.name + "/missing.env"
for _key in ("LLM_PROVIDER", "OLLAMA_MODEL", "OLLAMA_BASE_URL"):
    os.environ.pop(_key, None)

from fastapi.testclient import TestClient   # noqa: E402
from app.main import app                    # noqa: E402

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
    print("test_api_jobs.py — M1 gate (API + DB round-trip + §10 rejections)")
    with TestClient(app) as c:
        # -- health
        r = c.get("/api/v1/health")
        check("GET /health -> 200 ok 0.1.0",
              r.status_code == 200 and r.json().get("status") == "ok"
              and r.json().get("version") == "0.1.0", receipt=r.text)

        # -- POSCONTROL: text chapter round-trips to a queued job + status fetch
        good_text = "Wizardry is the art of service. " * 40   # >500 chars
        r = c.post("/api/v1/chapters/text",
                   json={"book_title": "YW", "chapter_title": "Ch1",
                         "text": good_text})
        check("POST /chapters/text valid -> 201 with chapter_id",
              r.status_code == 201 and "chapter_id" in r.json()
              and r.json()["source_type"] == "text", receipt=r.text)
        chapter_id = r.json().get("chapter_id")

        r = c.post("/api/v1/generation-jobs",
                   json={"chapter_id": chapter_id, "audience_level": "beginner",
                         "experience_style": "visual_story",
                         "target_screen_count": 6, "enable_auto_brainstorm": True})
        check("POST /generation-jobs -> 202 queued + status/events urls",
              r.status_code == 202 and r.json().get("status") == "queued"
              and r.json().get("status_url") and r.json().get("events_url"),
              receipt=r.text)
        job_id = r.json().get("job_id")

        r = c.get("/api/v1/generation-jobs/%s" % job_id)
        check("GET /generation-jobs/{id} -> 200, round-trip status fetch",
              r.status_code == 200 and r.json().get("status")
              in ("queued", "extracting", "creating_band_room", "building_site",
                  "publishing", "completed")
              and r.json().get("chapter_id") == chapter_id, receipt=r.text)

        # -- NEGATIVE CONTROLS: real failure modes -> exact §10 codes
        r = c.post("/api/v1/chapters/text", json={"text": "too short"})
        check("NEGCONTROL short text -> CHAPTER_TOO_SHORT",
              r.status_code == 422
              and r.json()["error"]["code"] == "CHAPTER_TOO_SHORT", receipt=r.text)

        r = c.post("/api/v1/chapters/text", json={"text": "x" * 80001})
        check("NEGCONTROL over-long text -> CHAPTER_TOO_LONG",
              r.status_code == 422
              and r.json()["error"]["code"] == "CHAPTER_TOO_LONG", receipt=r.text)

        r = c.post("/api/v1/chapters/upload",
                   files={"file": ("notes.md", b"# markdown", "text/markdown")})
        check("NEGCONTROL wrong file type -> INVALID_FILE_TYPE",
              r.status_code == 415
              and r.json()["error"]["code"] == "INVALID_FILE_TYPE", receipt=r.text)

        big = b"a" * (2 * 1024 * 1024)   # 2MB > 1MB cap
        r = c.post("/api/v1/chapters/upload",
                   files={"file": ("big.txt", big, "text/plain")})
        check("NEGCONTROL oversized upload -> FILE_TOO_LARGE",
              r.status_code == 413
              and r.json()["error"]["code"] == "FILE_TOO_LARGE", receipt=r.text)

        # -- positive upload (.txt) round-trips too
        r = c.post("/api/v1/chapters/upload",
                   files={"file": ("ch.txt", good_text.encode(), "text/plain")})
        check("POST /chapters/upload .txt valid -> 201 text chapter",
              r.status_code == 201 and r.json()["source_type"] == "text",
              receipt=r.text)

        r = c.post("/api/v1/generation-jobs",
                   json={"chapter_id": "no-such-chapter",
                         "audience_level": "beginner",
                         "experience_style": "visual_story",
                         "target_screen_count": 6, "enable_auto_brainstorm": True})
        check("NEGCONTROL job for unknown chapter -> INVALID_REQUEST",
              r.json()["error"]["code"] == "INVALID_REQUEST", receipt=r.text)

        r = c.get("/api/v1/generation-jobs/no-such-job")
        check("NEGCONTROL unknown job -> 404 JOB_NOT_FOUND",
              r.status_code == 404
              and r.json()["error"]["code"] == "JOB_NOT_FOUND", receipt=r.text)

    print("%d/%d gate checks passed" % (len(RAN) - len(FAILURES), len(RAN)))
    if FAILURES:
        print("GATE FAIL: %s" % ", ".join(FAILURES))
        sys.exit(1)
    print("GATE PASS — M1 API+DB: text/upload chapters round-trip to queued jobs, "
          "status fetch works, and every §10 failure mode is rejected with its code.")
    sys.exit(0)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    main()
