"""Phase 1 gate: account-backed reader progress and resume state."""
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
    print("test_auth_progress.py — account auth + reader progress")
    with TestClient(app) as c:
        r = c.get("/api/v1/auth/me")
        check("GET /auth/me before login -> AUTH_REQUIRED",
              r.status_code == 401
              and r.json()["error"]["code"] == "AUTH_REQUIRED", receipt=r.text)

        r = c.post("/api/v1/auth/register",
                   json={"email": "Reader@Example.com",
                         "password": "chapterstage-secret"})
        token = r.json().get("access_token")
        check("register -> 201 bearer token",
              r.status_code == 201 and token and r.json()["user"]["email"]
              == "reader@example.com", receipt=r.text)

        r = c.post("/api/v1/auth/register",
                   json={"email": "reader@example.com",
                         "password": "chapterstage-secret"})
        check("duplicate register -> EMAIL_ALREADY_REGISTERED",
              r.status_code == 409
              and r.json()["error"]["code"] == "EMAIL_ALREADY_REGISTERED",
              receipt=r.text)

        r = c.get("/api/v1/auth/me")
        check("GET /auth/me with auth cookie -> user",
              r.status_code == 200 and r.json()["email"] == "reader@example.com",
              receipt=r.text)

        headers = {"Authorization": "Bearer %s" % token}
        r = c.get("/api/v1/auth/me", headers=headers)
        check("GET /auth/me with token -> user",
              r.status_code == 200 and r.json()["email"] == "reader@example.com",
              receipt=r.text)

        r = c.post("/api/v1/auth/login",
                   json={"email": "reader@example.com",
                         "password": "chapterstage-secret"})
        check("login -> second bearer token",
              r.status_code == 200 and r.json().get("access_token"),
              receipt=r.text)

        r = c.get("/api/v1/experiences/exp-1/progress", headers=headers)
        check("empty progress resumes as blank state",
              r.status_code == 200 and r.json()["experience_id"] == "exp-1"
              and r.json()["completed_screen_ids"] == [], receipt=r.text)

        payload = {
            "current_screen_id": "screen-2",
            "completed_screen_ids": ["screen-1", "screen-1"],
            "last_checkpoint": "checkpoint-2",
            "interaction_state": {"quiz": {"q1": "b"}},
        }
        r = c.put("/api/v1/experiences/exp-1/progress",
                  json=payload, headers=headers)
        check("PUT progress persists checkpoint and de-dupes screens",
              r.status_code == 200
              and r.json()["current_screen_id"] == "screen-2"
              and r.json()["completed_screen_ids"] == ["screen-1"],
              receipt=r.text)

        r = c.get("/api/v1/experiences/exp-1/progress", headers=headers)
        check("GET progress resumes saved checkpoint",
              r.status_code == 200
              and r.json()["last_checkpoint"] == "checkpoint-2"
              and r.json()["interaction_state"]["quiz"]["q1"] == "b",
              receipt=r.text)

        r = c.post("/api/v1/auth/register",
                   json={"email": "other@example.com",
                         "password": "chapterstage-secret"})
        other_headers = {"Authorization": "Bearer %s" % r.json()["access_token"]}
        r = c.get("/api/v1/experiences/exp-1/progress", headers=other_headers)
        check("progress is isolated between users",
              r.status_code == 200 and r.json()["current_screen_id"] is None,
              receipt=r.text)

    print("%d/%d gate checks passed" % (len(RAN) - len(FAILURES), len(RAN)))
    if FAILURES:
        print("GATE FAIL: %s" % ", ".join(FAILURES))
        sys.exit(1)
    print("GATE PASS — authenticated users can persist and resume per-experience "
          "reader progress, isolated by account.")
    sys.exit(0)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    main()
