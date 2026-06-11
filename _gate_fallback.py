"""Standalone fallback for the K-Cell autonomy gate (public-repo shim).

In the cell, consent.py imports the real organ: satus/hooks/autonomy_gate.py.
In the extracted public repo that file doesn't exist, so this minimal shim
provides the SAME four organs consent.py uses: the destructive-command and
destructive-file classifiers and the consent ledger read path.

PROVENANCE: mirrors satus/hooks/autonomy_gate.py rev 2026-06-11. If the
cell organ's patterns change, this shim must follow — drift here means the
public demo enforces different safety rules than the cell does.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

# Ledger lives next to the package in standalone mode.
CONSENT_LOG = Path(__file__).resolve().parent / "consent_state.json"

DESTRUCTIVE_REGEXES = [
    re.compile(r"\brm\s+-[a-z]*r[a-z]*f\b"),           # rm -rf, rm -fr
    re.compile(r"\bdel\s+/[fsq]", re.IGNORECASE),       # del /f /s /q
    re.compile(r"\bgit\s+push\s+--force\b"),            # git push --force
    re.compile(r"\bgit\s+push\s+-f\b"),                 # git push -f
    re.compile(r"\bgit\s+reset\s+--hard\b"),            # git reset --hard
    re.compile(r"\bgit\s+branch\s+-D\b"),               # git branch -D
    re.compile(r"\bDROP\s+TABLE\b", re.IGNORECASE),     # SQL DROP TABLE
    re.compile(r"\bDELETE\s+FROM\b", re.IGNORECASE),    # SQL DELETE FROM
]

DESTRUCTIVE_FILE_PATTERNS = [
    ".env",
    "cell_state.json",
    "settings.local.json",
    "hooks_config.json",
    "k_context_hook.py",
    "auto_delegate.py",
]


def is_destructive_command(command):
    """Quoted strings stripped first so embedded code can't false-positive
    (python -c "DELETE FROM..." is Python, not SQL)."""
    stripped = re.sub(r'"[^"]*"', '""', command)
    stripped = re.sub(r"'[^']*'", "''", stripped)
    return any(rx.search(stripped) for rx in DESTRUCTIVE_REGEXES)


def is_destructive_file(file_path):
    return any(p in file_path for p in DESTRUCTIVE_FILE_PATTERNS)


def load_consent_state():
    try:
        if CONSENT_LOG.exists():
            return json.loads(CONSENT_LOG.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def check_consent(role, action, target):
    """ttl_minutes: -1 = permanent, N = expires after N minutes, default 5."""
    state = load_consent_state()
    approval = state.get("%s:%s:%s" % (role, action, target))
    if not approval:
        return False
    ttl = approval.get("ttl_minutes", 5)
    if ttl != -1:
        if time.time() - approval.get("approved_at", 0) > (ttl * 60):
            return False
    return approval.get("approved", False)
