"""Gate for the ngrok public FastAPI runner."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

from scripts import run_public  # noqa: E402

FAILURES: list[str] = []
RAN: list[str] = []


def check(name, cond, receipt=""):
    RAN.append(name)
    print("  [%s] %s" % ("PASS" if cond else "FAIL", name))
    if receipt and not cond:
        print("         receipt: %s" % receipt)
    if not cond:
        FAILURES.append(name)


class FakeListener:
    def __init__(self, url):
        self._url = url

    def url(self):
        return self._url


def _clear_env():
    for key in (
            "API_BASE_URL", "PUBLIC_SITE_BASE_URL", "NGROK_AUTHTOKEN",
            "NGROK_AUTH_TOKEN", "NGROK_DOMAIN", "NGROK_BASIC_AUTH"):
        os.environ.pop(key, None)


def main():
    print("test_run_public_script.py - ngrok public runner")
    _clear_env()

    tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    env_file = Path(tmp.name) / ".env"
    env_file.write_text(
        "NGROK_AUTHTOKEN=token-from-file\n"
        "NGROK_DOMAIN='demo.ngrok.app'\n"
        "NGROK_BASIC_AUTH=demo:secret\n"
        "API_BASE_URL=http://localhost:8000\n",
        encoding="utf-8")
    run_public._load_env_file(env_file)
    options = run_public.parse_args(["--port", "9000"])
    run_public._fill_ngrok_defaults(options)
    kwargs = run_public._ngrok_forward_kwargs(options)
    check("ngrok defaults load from env file",
          kwargs == {
              "authtoken": "token-from-file",
              "domain": "demo.ngrok.app",
              "basic_auth": ["demo:secret"],
          },
          receipt=kwargs)

    os.environ["API_BASE_URL"] = "http://localhost:8000"
    run_public._apply_public_base_urls("https://abc.ngrok-free.app/")
    check("public URL overrides API and generated-site bases",
          os.environ["API_BASE_URL"] == "https://abc.ngrok-free.app"
          and os.environ["PUBLIC_SITE_BASE_URL"]
          == "https://abc.ngrok-free.app/public/experiences",
          receipt={
              "api": os.environ.get("API_BASE_URL"),
              "site": os.environ.get("PUBLIC_SITE_BASE_URL"),
          })

    check("listener URL is read from ngrok listener",
          run_public._listener_url(FakeListener("https://demo.ngrok.app/"))
          == "https://demo.ngrok.app")
    check("wildcard uvicorn host maps to localhost upstream",
          run_public._upstream_url("0.0.0.0", 8000)
          == "http://127.0.0.1:8000")

    _clear_env()
    options = run_public.parse_args([])
    run_public._fill_ngrok_defaults(options)
    failed_without_token = False
    try:
        run_public._ngrok_forward_kwargs(options)
    except run_public.PublicServerError as exc:
        failed_without_token = "NGROK_AUTHTOKEN" in str(exc)
    check("missing ngrok token fails with setup guidance", failed_without_token)

    print("%d/%d gate checks passed" % (len(RAN) - len(FAILURES), len(RAN)))
    if FAILURES:
        print("GATE FAIL: %s" % ", ".join(FAILURES))
        sys.exit(1)
    print("GATE PASS - public runner sets ngrok-backed URLs before app import.")
    sys.exit(0)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    main()
