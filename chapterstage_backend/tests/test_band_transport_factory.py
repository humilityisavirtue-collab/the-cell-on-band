"""Selectable Band transport gate.

Default/test mode must stay deterministic and offline. Live mode is allowed to
touch the Band SDK, but it must fail fast when credentials are absent.
"""
from __future__ import annotations

import builtins
import os
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "workflows"))

from app.services.band_transport.base import BandTransportConfigError  # noqa: E402
from app.services.band_transport.factory import create_band_service  # noqa: E402
from app.services.band_transport.test_transport import TestBandTransport  # noqa: E402
import chapter_graph  # noqa: E402

FAILURES: list[str] = []
RAN: list[str] = []


def check(name, cond, receipt=""):
    RAN.append(name)
    print("  [%s] %s" % ("PASS" if cond else "FAIL", name))
    if receipt and not cond:
        print("         receipt: %s" % receipt)
    if not cond:
        FAILURES.append(name)


def _clear_band_env():
    for key in list(os.environ):
        if key.startswith("BAND_"):
            os.environ.pop(key)


def test_mode_never_imports_band_sdk():
    _clear_band_env()
    os.environ["BAND_TRANSPORT_MODE"] = "test"
    original_import = builtins.__import__

    def refusing_import(name, *args, **kwargs):
        if name == "band" or name.startswith("band."):
            raise AssertionError("test mode imported Band SDK")
        return original_import(name, *args, **kwargs)

    builtins.__import__ = refusing_import
    try:
        service = create_band_service()
    finally:
        builtins.__import__ = original_import
    check("test mode creates BandService without importing Band SDK",
          isinstance(service.transport, TestBandTransport),
          receipt="transport=%r" % type(service.transport))


def live_mode_fails_fast_without_credentials():
    _clear_band_env()
    os.environ["BAND_TRANSPORT_MODE"] = "live"
    failed = False
    try:
        create_band_service()
    except BandTransportConfigError as exc:
        failed = "BAND_API_KEY" in str(exc) and "BAND_AGENT_UUID_COORDINATOR" in str(exc)
    check("live mode fails fast without Band credentials", failed)


def test_transport_runs_and_severs_workflow():
    _clear_band_env()
    os.environ["BAND_TRANSPORT_MODE"] = "test"
    band = create_band_service()
    state = chapter_graph.ChapterWorkflow(band).run("job-factory", "Source")
    tx = band.transport
    check("factory test transport completes live workflow",
          state["status"] == "completed" and len(tx.posts) == 4,
          receipt="status=%r posts=%r" % (state["status"], tx.posts))
    check("factory test transport recorded room and recruited roles",
          tx.rooms == ["room-job-factory"]
          and tx.recruited == ["structure", "brainstorm", "visual", "verifier"],
          receipt="rooms=%r recruited=%r" % (tx.rooms, tx.recruited))

    dead = create_band_service("test")
    dead.transport.sever()
    state = chapter_graph.ChapterWorkflow(dead).run("job-dead", "Source")
    check("severed factory test transport stalls workflow",
          state["status"] == "stalled" and state.get("module") is None,
          receipt="status=%r module=%r" % (state["status"], state.get("module")))


def main():
    print("test_band_transport_factory.py — selectable Band transport")
    test_mode_never_imports_band_sdk()
    live_mode_fails_fast_without_credentials()
    test_transport_runs_and_severs_workflow()
    print("%d/%d gate checks passed" % (len(RAN) - len(FAILURES), len(RAN)))
    if FAILURES:
        print("GATE FAIL: %s" % ", ".join(FAILURES))
        sys.exit(1)
    print("GATE PASS — test mode is offline, live mode is explicit, and the "
          "load-bearing invariant survives the selectable transport factory.")
    sys.exit(0)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    main()
