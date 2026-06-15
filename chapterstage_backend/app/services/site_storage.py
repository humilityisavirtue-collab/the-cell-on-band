"""Static modular site assembly for ChapterStage experiences."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from app.config import settings
from app.services.site_validator import STRICT_CSP_HEADER, validate_site


SHELL_JS = """\
(function () {
  const app = document.querySelector('[data-chapterstage-app]');
  let manifest = null;
  let currentIndex = 0;

  function text(value) {
    return value == null ? '' : String(value);
  }

  function api(path, options) {
    return fetch(path, Object.assign({ credentials: 'same-origin' }, options || {}));
  }

  async function loadJson(path) {
    const response = await fetch(path, { credentials: 'same-origin' });
    if (!response.ok) throw new Error('load_failed:' + path);
    return response.json();
  }

  async function loadProgress() {
    try {
      const response = await api('/api/v1/experiences/' + manifest.experience_id + '/progress');
      if (!response.ok) return null;
      return response.json();
    } catch (_) {
      return null;
    }
  }

  async function saveProgress(screenId) {
    try {
      await api('/api/v1/experiences/' + manifest.experience_id + '/progress', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          current_screen_id: screenId,
          completed_screen_ids: manifest.screen_order.slice(0, currentIndex + 1),
          last_checkpoint: screenId,
          interaction_state: {}
        })
      });
    } catch (_) {}
  }

  async function render(screenId) {
    const screen = await loadJson('screens/' + screenId + '.json');
    app.replaceChildren();
    const section = document.createElement('section');
    section.className = 'screen';
    const title = document.createElement('h1');
    title.textContent = text(screen.title);
    const body = document.createElement('div');
    body.className = 'screen-body';
    const content = screen.content || {};
    body.textContent = text(content.text || content.body || '');
    const nav = document.createElement('nav');
    const prev = document.createElement('button');
    prev.type = 'button';
    prev.textContent = 'Previous';
    prev.disabled = currentIndex === 0;
    prev.addEventListener('click', () => go(currentIndex - 1));
    const next = document.createElement('button');
    next.type = 'button';
    next.textContent = currentIndex === manifest.screen_order.length - 1 ? 'Done' : 'Next';
    next.addEventListener('click', async () => {
      await saveProgress(screenId);
      if (currentIndex < manifest.screen_order.length - 1) go(currentIndex + 1);
    });
    nav.append(prev, next);
    section.append(title, body, nav);
    app.append(section);
  }

  function go(index) {
    currentIndex = Math.max(0, Math.min(index, manifest.screen_order.length - 1));
    render(manifest.screen_order[currentIndex]);
  }

  async function start() {
    manifest = await loadJson('manifest.json');
    const progress = await loadProgress();
    const resumeId = progress && progress.current_screen_id;
    const resumeIndex = manifest.screen_order.indexOf(resumeId);
    currentIndex = resumeIndex >= 0 ? resumeIndex : manifest.screen_order.indexOf(manifest.initial_screen_id);
    if (currentIndex < 0) currentIndex = 0;
    go(currentIndex);
  }

  start().catch((error) => {
    app.textContent = 'Unable to load this chapter experience.';
    console.error(error);
  });
})();
"""


SHELL_CSS = """\
:root { color-scheme: light; font-family: system-ui, sans-serif; }
body { margin: 0; background: #f7f7f4; color: #1d2525; }
main { min-height: 100vh; display: grid; place-items: center; padding: 24px; }
.screen { width: min(760px, 100%); }
.screen-body { margin: 18px 0 28px; line-height: 1.6; font-size: 1.05rem; }
nav { display: flex; gap: 12px; justify-content: space-between; }
button { border: 1px solid #1d2525; background: #fff; padding: 10px 14px; }
button:disabled { opacity: .45; }
"""


def write_modular_site(
        experience_id: str, job_id: str, title: str,
        screens: list[dict], metadata: dict | None = None,
        root: str | Path | None = None) -> dict:
    if not screens:
        raise ValueError("screens must contain at least one screen")
    site_root = Path(root or settings.GENERATED_SITE_ROOT)
    site_dir = site_root / experience_id
    screens_dir = site_dir / "screens"
    screens_dir.mkdir(parents=True, exist_ok=True)

    normalized = [_normalize_screen(s) for s in screens]
    order = [s["id"] for s in normalized]
    manifest = {
        "experience_id": experience_id,
        "job_id": job_id,
        "title": title,
        "screen_order": order,
        "initial_screen_id": order[0],
        "components_used": sorted({s["component_type"] for s in normalized}),
        "checkpoint_rules": {"save_on_next": True, "resume": "last_screen"},
    }
    meta = {
        "experience_id": experience_id,
        "job_id": job_id,
        "book_title": metadata.get("book_title", title) if metadata else title,
        "chapter_title": metadata.get("chapter_title", title) if metadata else title,
        "audience_level": metadata.get("audience_level", "beginner") if metadata else "beginner",
        "experience_style": metadata.get("experience_style", "visual_story") if metadata else "visual_story",
        "screen_count": len(normalized),
        "band_room_id": metadata.get("band_room_id", "") if metadata else "",
        "selected_brainstorm_variant": metadata.get("selected_brainstorm_variant", "") if metadata else "",
        "faithfulness_score": metadata.get("faithfulness_score", 0) if metadata else 0,
        "engagement_score": metadata.get("engagement_score", 0) if metadata else 0,
        "created_at": metadata.get("created_at", datetime.utcnow().isoformat() + "Z") if metadata else datetime.utcnow().isoformat() + "Z",
    }

    (site_dir / "index.html").write_text(_index_html(title), encoding="utf-8")
    (site_dir / "styles.css").write_text(SHELL_CSS, encoding="utf-8")
    (site_dir / "script.js").write_text(SHELL_JS, encoding="utf-8")
    (site_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8")
    (site_dir / "metadata.json").write_text(
        json.dumps(meta, indent=2), encoding="utf-8")
    for screen in normalized:
        (screens_dir / ("%s.json" % screen["id"])).write_text(
            json.dumps(screen, indent=2), encoding="utf-8")

    report = validate_site(site_dir)
    if not report["passed"]:
        raise ValueError("generated modular site failed validation: %r" % report)
    return {"site_dir": str(site_dir), "manifest": manifest, "metadata": meta}


def _normalize_screen(screen: dict) -> dict:
    sid = str(screen.get("id") or "").strip()
    if not sid:
        raise ValueError("screen id is required")
    return {
        "id": sid,
        "title": str(screen.get("title") or sid),
        "component_type": str(screen.get("component_type") or "text_screen"),
        "content": screen.get("content") or {},
        "interactions": screen.get("interactions") or [],
    }


def _index_html(title: str) -> str:
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<meta http-equiv='Content-Security-Policy' content=\"%s\">"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<link rel='stylesheet' href='styles.css'><title>%s</title></head>"
        "<body><main data-chapterstage-app aria-live='polite'></main>"
        "<script src='script.js'></script></body></html>"
    ) % (STRICT_CSP_HEADER, _escape(title))


def _escape(value: str) -> str:
    return (value or "").replace("&", "&amp;").replace("<", "&lt;").replace(
        ">", "&gt;").replace('"', "&quot;")
