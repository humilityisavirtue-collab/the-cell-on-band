"""Run the ChapterStage FastAPI server behind an ngrok public URL.

The app reads API_BASE_URL and PUBLIC_SITE_BASE_URL when app.config is imported,
so this runner intentionally opens the ngrok tunnel and sets those env vars
before uvicorn imports app.main.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
DEFAULT_ENV_FILE = BACKEND_DIR / ".env"

LOGGER = logging.getLogger("chapterstage.public")


class PublicServerError(RuntimeError):
    pass


@dataclass
class PublicServerOptions:
    host: str
    port: int
    reload: bool
    env_file: Path
    ngrok_authtoken: str | None
    ngrok_domain: str | None
    ngrok_basic_auth: str | None
    log_level: str


def parse_args(argv: list[str] | None = None) -> PublicServerOptions:
    parser = argparse.ArgumentParser(
        description="Start ChapterStage FastAPI with a public ngrok tunnel.")
    parser.add_argument("--host", default="127.0.0.1",
                        help="Local interface for uvicorn.")
    parser.add_argument("--port", type=int, default=8000,
                        help="Local port for uvicorn and the ngrok upstream.")
    parser.add_argument("--reload", action="store_true",
                        help="Enable uvicorn reload for local development.")
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_FILE),
                        help="Env file to load before opening the tunnel.")
    parser.add_argument("--ngrok-authtoken", default=None,
                        help="ngrok authtoken. Defaults to NGROK_AUTHTOKEN.")
    parser.add_argument("--ngrok-domain", default=None,
                        help="Optional reserved ngrok domain.")
    parser.add_argument("--ngrok-basic-auth", default=None,
                        help="Optional basic auth as username:password.")
    parser.add_argument("--log-level", default="info",
                        help="uvicorn log level.")
    args = parser.parse_args(argv)
    return PublicServerOptions(
        host=args.host,
        port=args.port,
        reload=args.reload,
        env_file=Path(args.env_file),
        ngrok_authtoken=args.ngrok_authtoken,
        ngrok_domain=args.ngrok_domain,
        ngrok_basic_auth=args.ngrok_basic_auth,
        log_level=args.log_level,
    )


def main(argv: list[str] | None = None) -> int:
    options = parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, options.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    _load_env_file(options.env_file)
    _fill_ngrok_defaults(options)

    listener = None
    try:
        listener = _open_ngrok_tunnel(options)
        public_url = _listener_url(listener)
        _apply_public_base_urls(public_url)
        _print_public_urls(public_url)

        sys.path.insert(0, str(BACKEND_DIR))
        import uvicorn

        uvicorn.run(
            "app.main:app",
            host=options.host,
            port=options.port,
            reload=options.reload,
            reload_dirs=[str(BACKEND_DIR)] if options.reload else None,
            log_level=options.log_level,
        )
        return 0
    except PublicServerError as exc:
        print("ERROR: %s" % exc, file=sys.stderr)
        return 1
    finally:
        if listener is not None:
            _disconnect_ngrok(listener)


def _load_env_file(path: str | Path, override: bool = False) -> None:
    env_path = Path(path)
    if not env_path.is_file():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if override or key not in os.environ:
            os.environ[key] = value


def _fill_ngrok_defaults(options: PublicServerOptions) -> None:
    options.ngrok_authtoken = (
        options.ngrok_authtoken
        or os.environ.get("NGROK_AUTHTOKEN")
        or os.environ.get("NGROK_AUTH_TOKEN")
    )
    options.ngrok_domain = options.ngrok_domain or os.environ.get("NGROK_DOMAIN")
    options.ngrok_basic_auth = (
        options.ngrok_basic_auth or os.environ.get("NGROK_BASIC_AUTH"))


def _open_ngrok_tunnel(options: PublicServerOptions) -> Any:
    try:
        import ngrok
    except ImportError as exc:
        raise PublicServerError(
            "Missing ngrok Python SDK. Install requirements.txt first.") from exc

    forward_kwargs = _ngrok_forward_kwargs(options)
    upstream = _upstream_url(options.host, options.port)
    LOGGER.info("opening ngrok tunnel upstream=%s", upstream)
    try:
        return ngrok.forward(addr=upstream, **forward_kwargs)
    except Exception as exc:
        raise PublicServerError("Could not open ngrok tunnel: %s" % exc) from exc


def _ngrok_forward_kwargs(options: PublicServerOptions) -> dict[str, Any]:
    if not options.ngrok_authtoken:
        raise PublicServerError(
            "Set NGROK_AUTHTOKEN in the environment or chapterstage_backend/.env.")
    kwargs: dict[str, Any] = {"authtoken": options.ngrok_authtoken}
    if options.ngrok_domain:
        kwargs["domain"] = options.ngrok_domain
    if options.ngrok_basic_auth:
        kwargs["basic_auth"] = [options.ngrok_basic_auth]
    return kwargs


def _upstream_url(host: str, port: int) -> str:
    upstream_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    return "http://%s:%d" % (upstream_host, port)


def _listener_url(listener: Any) -> str:
    url_attr = getattr(listener, "url", None)
    if callable(url_attr):
        url = url_attr()
    else:
        url = str(url_attr or listener)
    if not url:
        raise PublicServerError("ngrok listener did not expose a public URL.")
    return url.rstrip("/")


def _apply_public_base_urls(public_url: str) -> None:
    base_url = public_url.rstrip("/")
    os.environ["API_BASE_URL"] = base_url
    os.environ["PUBLIC_SITE_BASE_URL"] = base_url + "/public/experiences"


def _print_public_urls(public_url: str) -> None:
    base_url = public_url.rstrip("/")
    print("ngrok public URL: %s" % base_url)
    print("API docs: %s/docs" % base_url)
    print("API base URL: %s" % os.environ["API_BASE_URL"])
    print("Generated sites base: %s" % os.environ["PUBLIC_SITE_BASE_URL"])


def _disconnect_ngrok(listener: Any) -> None:
    try:
        import ngrok

        ngrok.disconnect(_listener_url(listener))
    except Exception as exc:
        LOGGER.warning("could not disconnect ngrok listener cleanly: %s", exc)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    raise SystemExit(main())
