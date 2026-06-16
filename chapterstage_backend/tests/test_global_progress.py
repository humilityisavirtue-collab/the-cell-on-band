"""Phase 7 gate: global anonymous progress and resume state."""
from __future__ import annotations

import os
import sys
import tempfile
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
    print("test_global_progress.py — anonymous global progress")
    with TestClient(app) as c:
        r = c.get("/api/v1/auth/me")
        check("auth endpoints are not mounted",
              r.status_code == 404, receipt=r.text)

        r = c.get("/api/v1/experiences/exp-1/progress")
        check("empty global progress resumes as blank state",
              r.status_code == 200 and r.json()["experience_id"] == "exp-1"
              and r.json()["current_screen_id"] is None
              and r.json()["completed_screen_ids"] == [], receipt=r.text)

        payload = {
            "current_screen_id": "screen-2",
            "completed_screen_ids": ["screen-1", "screen-1", "screen-2"],
            "last_checkpoint": "checkpoint-2",
            "interaction_state": {"quiz": {"q1": "b"}},
        }
        r = c.put("/api/v1/experiences/exp-1/progress", json=payload)
        check("PUT progress persists globally and de-dupes screens",
              r.status_code == 200
              and r.json()["current_screen_id"] == "screen-2"
              and r.json()["completed_screen_ids"] == ["screen-1", "screen-2"],
              receipt=r.text)

    with TestClient(app) as c:
        r = c.get("/api/v1/experiences/exp-1/progress")
        check("fresh client sees the same persisted progress",
              r.status_code == 200
              and r.json()["last_checkpoint"] == "checkpoint-2"
              and r.json()["interaction_state"]["quiz"]["q1"] == "b",
              receipt=r.text)

        r = c.get("/api/v1/experiences/exp-2/progress")
        check("different experience keeps separate global progress",
              r.status_code == 200 and r.json()["current_screen_id"] is None,
              receipt=r.text)

    print("%d/%d gate checks passed" % (len(RAN) - len(FAILURES), len(RAN)))
    if FAILURES:
        print("GATE FAIL: %s" % ", ".join(FAILURES))
        sys.exit(1)
    print("GATE PASS — progress is anonymous, global per experience, persisted, "
          "and independent of auth.")
    sys.exit(0)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    main()
