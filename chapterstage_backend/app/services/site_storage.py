"""Static modular site assembly for ChapterStage experiences."""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from app.config import settings
from app.services.site_validator import STRICT_CSP_HEADER, validate_site


SHELL_JS = """\
(function () {
  const app = document.querySelector('[data-chapterstage-app]');
  let manifest = null;
  let currentIndex = 0;
  const SVG_NS = 'http:' + String.fromCharCode(47, 47) + 'www.w3.org/2000/svg';

  function text(value) {
    return value == null ? '' : String(value);
  }

  function asArray(value) {
    return Array.isArray(value) ? value : [];
  }

  function firstText() {
    for (let i = 0; i < arguments.length; i += 1) {
      const value = text(arguments[i]).trim();
      if (value) return value;
    }
    return '';
  }

  function slug(value) {
    return text(value).toLowerCase().replace(/[^a-z0-9_-]+/g, '-').replace(/^-+|-+$/g, '') || 'screen';
  }

  function el(tagName, className, value) {
    const node = document.createElement(tagName);
    if (className) node.className = className;
    if (value != null && value !== '') node.textContent = text(value);
    return node;
  }

  function appendText(parent, tagName, className, value) {
    const body = text(value).trim();
    if (!body) return null;
    const node = el(tagName, className, body);
    parent.append(node);
    return node;
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
    const componentType = text(screen.component_type || 'narrative_scene');
    section.className = 'screen screen-' + slug(componentType);
    const header = el('header', 'screen-header');
    appendText(header, 'p', 'screen-kicker', componentLabel(componentType));
    appendText(header, 'h1', '', screen.title);
    const content = screen.content || {};
    appendText(header, 'p', 'screen-summary', firstText(
      content.visual_summary, content.summary, content.subtitle));
    const body = document.createElement('div');
    body.className = 'screen-body';
    renderComponent(body, componentType, content);
    const nav = document.createElement('nav');
    nav.className = 'screen-nav';
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
    section.append(header, body, nav);
    app.append(section);
  }

  function componentLabel(componentType) {
    const labels = {
      narrative_scene: 'Visual scene',
      text_screen: 'Visual scene',
      diagram: 'Diagram',
      flow_diagram: 'Flow diagram',
      timeline: 'Timeline',
      state_machine: 'State diagram',
      debug_trace: 'Debug trace',
      concept_map: 'Concept map',
      process_flow: 'Process flow',
      quiz: 'Checkpoint',
      recap: 'Recap'
    };
    return labels[componentType] || componentType.replace(/_/g, ' ');
  }

  function renderComponent(parent, componentType, content) {
    if (isDiagramComponent(componentType)) return renderDiagram(parent, content, componentType);
    if (componentType === 'timeline') return renderTimeline(parent, content);
    if (componentType === 'concept_map') return renderConceptMap(parent, content);
    if (componentType === 'process_flow') return renderProcessFlow(parent, content);
    if (componentType === 'quiz') return renderQuiz(parent, content);
    if (componentType === 'recap') return renderRecap(parent, content);
    return renderNarrative(parent, content);
  }

  function isDiagramComponent(componentType) {
    return [
      'diagram', 'flow_diagram', 'state_machine', 'debug_trace'
    ].indexOf(componentType) >= 0;
  }

  function renderNarrative(parent, content) {
    const stage = el('div', 'visual-stage');
    appendText(stage, 'p', 'visual-title', firstText(content.visual_title, content.callout));
    appendText(stage, 'p', 'screen-copy', firstText(content.text, content.body, content.description));
    const beats = asArray(content.beats);
    const steps = asArray(content.steps);
    const items = beats.length ? beats : steps;
    if (items.length) stage.append(renderList(items, 'beat-list'));
    parent.append(stage);
  }

  function renderConceptMap(parent, content) {
    return renderDiagram(parent, content, 'concept_map');
  }

  function renderDiagram(parent, content, componentType) {
    appendText(parent, 'p', 'screen-copy', firstText(
      content.text, content.body, content.summary, content.description));
    const nodes = diagramNodes(content);
    const edges = diagramEdges(content, nodes, componentType);
    if (!nodes.length) {
      return renderNarrative(parent, content);
    }
    const layout = positionNodes(nodes, componentType);
    const shell = el('div', 'diagram-shell diagram-' + slug(componentType));
    const svg = svgEl('svg', {
      viewBox: '0 0 720 ' + layout.height,
      role: 'img',
      'aria-label': firstText(content.aria_label, content.visual_title, 'Generated diagram')
    });
    svg.append(diagramDefs());
    const edgeLayer = svgEl('g', { class: 'diagram-edges' });
    const nodeLayer = svgEl('g', { class: 'diagram-nodes' });
    edges.forEach((edge) => drawEdge(edgeLayer, edge, layout.byKey));
    layout.nodes.forEach((node) => drawNode(nodeLayer, node));
    svg.append(edgeLayer, nodeLayer);
    shell.append(svg);
    parent.append(shell);
  }

  function renderProcessFlow(parent, content) {
    appendText(parent, 'p', 'screen-copy', firstText(content.text, content.body));
    const explicitSteps = asArray(content.steps);
    const beats = asArray(content.beats);
    const steps = explicitSteps.length ? explicitSteps : beats;
    const flow = el('ol', 'process-flow');
    steps.forEach((item) => {
      const step = el('li', '');
      const label = typeof item === 'object' ? firstText(item.label, item.title) : item;
      const detail = typeof item === 'object' ? firstText(item.detail, item.text) : '';
      appendText(step, 'h2', '', label);
      appendText(step, 'p', '', detail);
      flow.append(step);
    });
    parent.append(flow);
  }

  function renderTimeline(parent, content) {
    appendText(parent, 'p', 'screen-copy', firstText(content.text, content.body));
    const explicitEvents = asArray(content.events);
    const steps = asArray(content.steps);
    const beats = asArray(content.beats);
    const events = explicitEvents.length ? explicitEvents : (steps.length ? steps : beats);
    if (!events.length) return renderNarrative(parent, content);
    const timeline = el('div', 'timeline-visual');
    events.forEach((item, index) => {
      const event = normalizeNode(item, index);
      const row = el('article', 'timeline-event');
      row.append(el('span', 'timeline-marker', index + 1));
      const copy = el('div', 'timeline-copy');
      appendText(copy, 'h2', '', event.label);
      appendText(copy, 'p', '', event.detail);
      row.append(copy);
      timeline.append(row);
    });
    parent.append(timeline);
  }

  function renderQuiz(parent, content) {
    appendText(parent, 'p', 'quiz-question', firstText(content.question, content.text));
    const options = asArray(content.options);
    const answer = text(content.answer).trim();
    const status = el('p', 'quiz-status');
    const list = el('div', 'quiz-options');
    options.forEach((option) => {
      const label = typeof option === 'object' ? firstText(option.label, option.text) : option;
      const button = el('button', 'choice-button', label);
      button.type = 'button';
      button.addEventListener('click', () => {
        Array.from(list.children).forEach((child) => child.classList.remove('is-selected', 'is-correct'));
        button.classList.add('is-selected');
        if (answer && label === answer) button.classList.add('is-correct');
        status.textContent = answer && label === answer
          ? firstText(content.explanation, 'Correct.')
          : firstText(content.try_again, content.explanation, 'Saved.');
      });
      list.append(button);
    });
    parent.append(list, status);
  }

  function renderRecap(parent, content) {
    appendText(parent, 'p', 'screen-copy', firstText(content.text, content.body));
    const explicitHighlights = asArray(content.highlights);
    const beats = asArray(content.beats);
    const highlights = explicitHighlights.length ? explicitHighlights : beats;
    if (highlights.length) parent.append(renderList(highlights, 'recap-list'));
  }

  function renderList(items, className) {
    const list = el('ul', className);
    items.forEach((item) => {
      const label = typeof item === 'object' ? firstText(item.label, item.title, item.text) : item;
      appendText(list, 'li', '', label);
    });
    return list;
  }

  function svgEl(tagName, attrs) {
    const node = document.createElementNS(SVG_NS, tagName);
    Object.keys(attrs || {}).forEach((key) => node.setAttribute(key, text(attrs[key])));
    return node;
  }

  function diagramDefs() {
    const defs = svgEl('defs');
    const marker = svgEl('marker', {
      id: 'diagram-arrow',
      markerWidth: 12,
      markerHeight: 12,
      refX: 10,
      refY: 6,
      orient: 'auto',
      markerUnits: 'strokeWidth'
    });
    marker.append(svgEl('path', { d: 'M2,2 L10,6 L2,10 Z', class: 'diagram-arrow' }));
    defs.append(marker);
    return defs;
  }

  function diagramNodes(content) {
    const rawNodes = asArray(content.nodes);
    const states = asArray(content.states);
    const steps = asArray(content.steps);
    const events = asArray(content.events);
    const source = rawNodes.length ? rawNodes : (states.length ? states : (steps.length ? steps : events));
    return source.slice(0, 10).map(normalizeNode);
  }

  function diagramEdges(content, nodes, componentType) {
    const explicitEdges = asArray(content.edges);
    const connections = asArray(content.connections);
    const transitions = asArray(content.transitions);
    const source = explicitEdges.length ? explicitEdges : (connections.length ? connections : transitions);
    const edges = source
      .map((item) => normalizeEdge(item))
      .filter((item) => item.from && item.to);
    if (edges.length || nodes.length < 2) return edges.slice(0, 14);
    if (componentType === 'flow_diagram' || componentType === 'debug_trace') {
      return nodes.slice(0, -1).map((node, index) => ({
        from: node.id,
        to: nodes[index + 1].id,
        label: 'then'
      }));
    }
    return [];
  }

  function normalizeNode(item, index) {
    const fallback = 'node_' + (index + 1);
    if (item && typeof item === 'object') {
      const label = firstText(item.label, item.title, item.name, item.id, fallback);
      return {
        id: firstText(item.id, item.key, item.label, fallback),
        label: label,
        detail: firstText(item.detail, item.text, item.summary, item.body),
        group: firstText(item.group, item.type, item.kind)
      };
    }
    return {
      id: fallback,
      label: firstText(item, 'Node ' + (index + 1)),
      detail: '',
      group: ''
    };
  }

  function normalizeEdge(item) {
    if (item && typeof item === 'object') {
      return {
        from: firstText(item.from, item.source, item.start),
        to: firstText(item.to, item.target, item.end),
        label: firstText(item.label, item.text, item.relationship)
      };
    }
    return { from: '', to: '', label: text(item) };
  }

  function positionNodes(nodes, componentType) {
    const linear = componentType === 'flow_diagram' || componentType === 'debug_trace';
    const rows = linear ? (nodes.length > 4 ? 2 : 1) : Math.ceil(nodes.length / Math.min(3, Math.max(1, nodes.length)));
    const cols = linear
      ? Math.ceil(nodes.length / rows)
      : Math.min(3, Math.max(1, nodes.length));
    const height = Math.max(300, rows * 145 + 90);
    const byKey = {};
    const placed = nodes.map((node, index) => {
      const row = Math.floor(index / cols);
      const col = index % cols;
      const xGap = cols > 1 ? 560 / (cols - 1) : 0;
      const x = cols > 1 ? 80 + (col * xGap) : 360;
      const y = 80 + (row * 145);
      const out = Object.assign({}, node, { x: x, y: y });
      byKey[node.id] = out;
      byKey[node.label] = out;
      return out;
    });
    return { nodes: placed, byKey: byKey, height: height };
  }

  function drawEdge(parent, edge, byKey) {
    const from = byKey[edge.from];
    const to = byKey[edge.to];
    if (!from || !to) return;
    const x1 = from.x + (to.x >= from.x ? 82 : -82);
    const x2 = to.x + (to.x >= from.x ? -82 : 82);
    const y1 = from.y;
    const y2 = to.y;
    parent.append(svgEl('line', {
      x1: x1,
      y1: y1,
      x2: x2,
      y2: y2,
      class: 'diagram-edge',
      'marker-end': 'url(#diagram-arrow)'
    }));
    if (edge.label) {
      appendSvgText(parent, 'diagram-edge-label', (x1 + x2) / 2, ((y1 + y2) / 2) - 8,
        edge.label, 18, 13, 2);
    }
  }

  function drawNode(parent, node) {
    const group = svgEl('g', { class: 'diagram-node' });
    group.append(svgEl('rect', {
      x: node.x - 84,
      y: node.y - 42,
      width: 168,
      height: 84,
      rx: 10,
      ry: 10
    }));
    appendSvgText(group, 'diagram-node-label', node.x, node.y - 10, node.label, 18, 16, 2);
    appendSvgText(group, 'diagram-node-detail', node.x, node.y + 22, node.detail, 24, 13, 2);
    parent.append(group);
  }

  function appendSvgText(parent, className, x, y, value, maxChars, lineHeight, maxLines) {
    const lines = wrapText(value, maxChars, maxLines);
    if (!lines.length) return null;
    const node = svgEl('text', {
      x: x,
      y: y,
      class: className,
      'text-anchor': 'middle'
    });
    lines.forEach((line, index) => {
      const tspan = svgEl('tspan', { x: x, dy: index === 0 ? 0 : lineHeight });
      tspan.textContent = line;
      node.append(tspan);
    });
    parent.append(node);
    return node;
  }

  function wrapText(value, maxChars, maxLines) {
    const words = text(value).trim().split(/\\s+/).filter(Boolean);
    const lines = [];
    let line = '';
    words.forEach((word) => {
      const next = line ? line + ' ' + word : word;
      if (next.length > maxChars && line) {
        lines.push(line);
        line = word;
      } else {
        line = next;
      }
    });
    if (line) lines.push(line);
    return lines.slice(0, maxLines).map((item, index) => {
      if (index === maxLines - 1 && lines.length > maxLines) {
        return item.length > maxChars - 1 ? item.slice(0, maxChars - 1) + '...' : item + '...';
      }
      return item.length > maxChars ? item.slice(0, maxChars - 1) + '...' : item;
    });
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
:root {
  color-scheme: light;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  background: #f5f1e8;
  color: #202322;
}
* { box-sizing: border-box; }
body { margin: 0; background: #f5f1e8; color: #202322; }
main {
  min-height: 100vh;
  display: grid;
  align-items: center;
  padding: clamp(18px, 4vw, 48px);
}
.screen {
  width: min(1040px, 100%);
  margin: 0 auto;
  display: grid;
  grid-template-columns: minmax(0, .9fr) minmax(0, 1.3fr);
  gap: clamp(20px, 5vw, 56px);
  align-items: center;
}
.screen-header h1 {
  margin: 0;
  max-width: 12ch;
  font-size: clamp(2.15rem, 7vw, 5.8rem);
  line-height: .98;
}
.screen-kicker {
  width: fit-content;
  margin: 0 0 18px;
  border: 1px solid #202322;
  border-radius: 999px;
  padding: 6px 10px;
  background: #f4c95d;
  font-size: .78rem;
  font-weight: 800;
  text-transform: uppercase;
}
.screen-summary,
.screen-copy {
  max-width: 66ch;
  color: #48504c;
  line-height: 1.65;
  font-size: 1.02rem;
}
.screen-body {
  min-height: 390px;
  border: 1px solid #202322;
  border-radius: 8px;
  background: #fffaf0;
  box-shadow: 10px 10px 0 #202322;
  padding: clamp(18px, 3vw, 34px);
  overflow: hidden;
}
.visual-stage {
  min-height: 320px;
  display: grid;
  align-content: center;
  gap: 22px;
  border-radius: 8px;
  padding: clamp(18px, 4vw, 40px);
  background:
    linear-gradient(135deg, rgba(38, 124, 113, .18), rgba(244, 201, 93, .24)),
    #fffdf7;
}
.visual-title {
  margin: 0;
  color: #a23e48;
  font-size: 1.15rem;
  font-weight: 800;
}
.diagram-shell {
  margin-top: 18px;
  min-height: 320px;
  border: 1px solid #202322;
  border-radius: 8px;
  background:
    linear-gradient(rgba(32, 35, 34, .055) 1px, transparent 1px),
    linear-gradient(90deg, rgba(32, 35, 34, .055) 1px, transparent 1px),
    #fffdf7;
  background-size: 28px 28px;
  overflow: hidden;
}
.diagram-shell svg {
  display: block;
  width: 100%;
  height: auto;
  min-height: 300px;
}
.diagram-edge {
  stroke: #267c71;
  stroke-width: 3;
  stroke-linecap: round;
}
.diagram-arrow {
  fill: #267c71;
}
.diagram-edge-label {
  fill: #a23e48;
  paint-order: stroke;
  stroke: #fffdf7;
  stroke-width: 5px;
  stroke-linejoin: round;
  font-size: 12px;
  font-weight: 800;
}
.diagram-node rect {
  fill: #ffffff;
  stroke: #202322;
  stroke-width: 2;
  filter: drop-shadow(4px 4px 0 rgba(32, 35, 34, .95));
}
.diagram-node-label {
  fill: #202322;
  font-size: 15px;
  font-weight: 850;
}
.diagram-node-detail {
  fill: #5c625f;
  font-size: 12px;
  font-weight: 650;
}
.diagram-flow-diagram .diagram-node rect,
.diagram-debug-trace .diagram-node rect {
  fill: #f4c95d;
}
.diagram-state-machine .diagram-node rect {
  fill: #eaf6f3;
}
.timeline-visual {
  position: relative;
  display: grid;
  gap: 14px;
  margin-top: 18px;
  padding-left: 22px;
}
.timeline-visual::before {
  content: "";
  position: absolute;
  top: 10px;
  bottom: 10px;
  left: 17px;
  width: 3px;
  border-radius: 999px;
  background: #267c71;
}
.timeline-event {
  position: relative;
  display: grid;
  grid-template-columns: 38px minmax(0, 1fr);
  gap: 12px;
  align-items: start;
}
.timeline-marker {
  z-index: 1;
  display: grid;
  place-items: center;
  width: 36px;
  height: 36px;
  border: 2px solid #202322;
  border-radius: 999px;
  background: #f4c95d;
  font-weight: 850;
}
.timeline-copy {
  border: 1px solid #202322;
  border-radius: 8px;
  background: #ffffff;
  padding: 12px;
}
.timeline-copy h2 {
  margin: 0 0 6px;
  font-size: 1rem;
}
.timeline-copy p {
  margin: 0;
  color: #5c625f;
  line-height: 1.45;
}
.beat-list,
.recap-list {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 10px;
  margin: 0;
  padding: 0;
  list-style: none;
}
.beat-list li,
.recap-list li,
.map-node,
.process-flow li {
  border: 1px solid #202322;
  border-radius: 8px;
  background: #ffffff;
  padding: 12px;
}
.concept-map {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 12px;
  margin-top: 18px;
}
.map-node h2,
.process-flow h2 {
  margin: 0 0 8px;
  font-size: 1rem;
}
.map-node p,
.process-flow p {
  margin: 0;
  color: #5c625f;
  line-height: 1.45;
}
.connection-list {
  display: grid;
  gap: 8px;
  margin-top: 18px;
}
.connection-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  margin: 0;
}
.connection-row b {
  color: #267c71;
}
.connection-row em {
  color: #a23e48;
  font-style: normal;
  font-weight: 700;
}
.process-flow {
  display: grid;
  gap: 12px;
  margin: 18px 0 0;
  padding-left: 22px;
}
.quiz-question {
  margin: 0 0 18px;
  font-size: 1.3rem;
  line-height: 1.35;
  font-weight: 800;
}
.quiz-options {
  display: grid;
  gap: 10px;
}
button,
.choice-button {
  min-height: 42px;
  border: 1px solid #202322;
  border-radius: 8px;
  background: #ffffff;
  color: #202322;
  padding: 10px 14px;
  font: inherit;
  font-weight: 750;
  cursor: pointer;
}
button:disabled { cursor: default; opacity: .45; }
.choice-button {
  text-align: left;
}
.choice-button.is-selected {
  background: #f4c95d;
}
.choice-button.is-correct {
  background: #267c71;
  color: #ffffff;
}
.quiz-status {
  min-height: 28px;
  color: #48504c;
  font-weight: 700;
}
.screen-nav {
  grid-column: 1 / -1;
  display: flex;
  gap: 12px;
  justify-content: space-between;
}
.screen-nav button {
  min-width: 112px;
  background: #202322;
  color: #ffffff;
}
@media (max-width: 760px) {
  main { align-items: start; }
  .screen { grid-template-columns: 1fr; }
  .screen-header h1 { max-width: 100%; font-size: clamp(2rem, 14vw, 4rem); }
  .screen-body { min-height: 300px; box-shadow: 6px 6px 0 #202322; }
}
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

    normalized = []
    seen: set[str] = set()
    for index, screen in enumerate(screens, start=1):
        normalized.append(_normalize_screen(screen, index, seen))
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
    expected_screen_files = {"%s.json" % screen["id"] for screen in normalized}
    for stale in screens_dir.glob("*.json"):
        if stale.name not in expected_screen_files:
            stale.unlink()
    return {"site_dir": str(site_dir), "manifest": manifest, "metadata": meta}


def _normalize_screen(screen: dict, index: int, seen: set[str]) -> dict:
    sid = _screen_id(screen.get("id") or "screen_%d" % index)
    base = sid
    counter = 2
    while sid in seen:
        sid = "%s_%d" % (base, counter)
        counter += 1
    seen.add(sid)
    content = screen.get("content") or {}
    if not isinstance(content, dict):
        content = {"text": str(content)}
    return {
        "id": sid,
        "title": str(screen.get("title") or sid),
        "component_type": str(
            screen.get("component_type") or screen.get("kind")
            or "narrative_scene"),
        "content": content,
        "interactions": screen.get("interactions")
        if isinstance(screen.get("interactions"), list) else [],
    }


def _screen_id(value) -> str:
    sid = re.sub(r"[^A-Za-z0-9_-]+", "_", str(value or "").strip()).strip("_")
    return sid or "screen"


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
