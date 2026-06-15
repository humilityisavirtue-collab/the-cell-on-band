"""site_storage.py — publish a generated site under the isolated static root.

Takes the {filename: content} dict from workflows.site_builder, writes it to
GENERATED_SITE_ROOT/<experience_id>/ (§11 isolated dir, path-normalized so a
crafted filename can't escape), runs the §7.5/§11 validator, and returns the
public URL ONLY if validation passes. A failing site is left on disk for
debugging but NEVER gets a public_url — the caller raises SITE_VALIDATION_FAILED.
"""
from __future__ import annotations

from pathlib import Path

from app.config import settings
from app.services.site_validator import validate_site


def publish_site(experience_id: str, files: dict) -> dict:
    """Write + validate. Returns
    {"passed": bool, "violations": [...], "storage_path": str, "public_url": str|None}.
    public_url is None unless the validator passed."""
    root = Path(settings.GENERATED_SITE_ROOT).resolve()
    site_dir = (root / experience_id).resolve()
    # path-normalization guard: the resolved dir MUST stay under the root (§11).
    try:
        site_dir.relative_to(root)
    except ValueError:
        raise ValueError("experience_id escapes the site root: %r" % experience_id)

    site_dir.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        target = (site_dir / name).resolve()
        try:
            target.relative_to(site_dir)            # no '../' in a filename
        except ValueError:
            raise ValueError("generated filename escapes the site dir: %r" % name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    report = validate_site(site_dir)
    public_url = None
    if report["passed"]:
        base = settings.PUBLIC_SITE_BASE_URL.rstrip("/")
        public_url = "%s/%s/index.html" % (base, experience_id)
    return {
        "passed": report["passed"],
        "violations": report["violations"],
        "storage_path": str(site_dir),
        "public_url": public_url,
    }
