"""Petri tag viewer — browse analyses and raw responses."""

from __future__ import annotations

import csv
import html
import json
import re
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import unquote

HERE = Path(__file__).resolve().parent
BY_TAG_DIR = HERE / "petri_by_tag"
ANALYSES_DIR = HERE / "petri_analyses"
SUMMARY_CSV = HERE / "petri_tag_summary.csv"

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8502


# ---------------------------------------------------------------------------
# Minimal markdown-to-HTML (covers what the analysis files use)
# ---------------------------------------------------------------------------

def md_to_html(text: str) -> str:
    """Convert a subset of markdown to HTML (headings, bold, italic, lists, paragraphs, code)."""
    lines = text.split("\n")
    out: list[str] = []
    in_list = False
    in_code = False

    for line in lines:
        # Fenced code blocks
        if line.strip().startswith("```"):
            if in_code:
                out.append("</pre>")
                in_code = False
            else:
                out.append("<pre class='code-block'>")
                in_code = True
            continue
        if in_code:
            out.append(html.escape(line))
            continue

        # Close list if we left it
        stripped = line.strip()
        if in_list and not stripped.startswith("- ") and not stripped.startswith("* ") and stripped:
            out.append("</ul>")
            in_list = False

        # Headings
        m = re.match(r"^(#{1,4})\s+(.*)", line)
        if m:
            level = len(m.group(1))
            content = _inline(m.group(2))
            out.append(f"<h{level}>{content}</h{level}>")
            continue

        # List items
        m = re.match(r"^\s*[-*]\s+(.*)", line)
        if m:
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{_inline(m.group(1))}</li>")
            continue

        # Blank line
        if not stripped:
            out.append("")
            continue

        # Paragraph
        out.append(f"<p>{_inline(line)}</p>")

    if in_list:
        out.append("</ul>")
    if in_code:
        out.append("</pre>")
    return "\n".join(out)


def _inline(text: str) -> str:
    """Handle bold, italic, inline code, links."""
    text = html.escape(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
    text = re.sub(r"`(.+?)`", r"<code>\1</code>", text)
    return text


# ---------------------------------------------------------------------------
# Data loaders (read fresh each request)
# ---------------------------------------------------------------------------

def load_tags() -> list[dict]:
    """Load tag summary from CSV."""
    if not SUMMARY_CSV.exists():
        return []
    rows = []
    with open(SUMMARY_CSV) as f:
        for row in csv.DictReader(f):
            rows.append(row)
    return rows


def load_analysis(tag: str) -> str:
    """Load and render a tag analysis markdown file."""
    p = ANALYSES_DIR / f"{tag}.md"
    if not p.exists():
        return "<p><em>No analysis available for this tag.</em></p>"
    return md_to_html(p.read_text())


def load_responses(tag: str) -> dict | None:
    """Load raw response data for a tag."""
    p = BY_TAG_DIR / f"{tag}.json"
    if not p.exists():
        return None
    return json.loads(p.read_text())


# ---------------------------------------------------------------------------
# Score colour
# ---------------------------------------------------------------------------

def score_color_css() -> str:
    """CSS function for score colouring (used in JS)."""
    return ""


# ---------------------------------------------------------------------------
# HTML page
# ---------------------------------------------------------------------------

INDEX_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Petri Tag Viewer</title>
<style>
:root {
  --bg: #0d1117; --surface: #161b22; --border: #30363d;
  --text: #e6edf3; --text2: #8b949e; --accent: #58a6ff;
  --green: #3fb950; --red: #f85149; --yellow: #d29922;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
       background: var(--bg); color: var(--text); display: flex; height: 100vh; overflow: hidden; }

/* Sidebar */
#sidebar { width: 320px; min-width: 320px; background: var(--surface); border-right: 1px solid var(--border);
           display: flex; flex-direction: column; overflow: hidden; }
#sidebar-header { padding: 16px; border-bottom: 1px solid var(--border); }
#sidebar-header h2 { font-size: 15px; margin-bottom: 8px; }
#search { width: 100%; padding: 6px 10px; background: var(--bg); border: 1px solid var(--border);
          border-radius: 6px; color: var(--text); font-size: 13px; outline: none; }
#search:focus { border-color: var(--accent); }
#tag-list { flex: 1; overflow-y: auto; }
.tag-item { padding: 10px 16px; cursor: pointer; border-bottom: 1px solid var(--border);
            transition: background 0.1s; display: flex; justify-content: space-between; align-items: center; }
.tag-item:hover { background: #1c2128; }
.tag-item.active { background: #1c2128; border-left: 3px solid var(--accent); }
.tag-name { font-size: 13px; font-weight: 600; }
.tag-scores { font-size: 11px; color: var(--text2); text-align: right; line-height: 1.6; }
.delta { font-weight: 700; font-size: 12px; }
.delta-good { color: var(--green); }
.delta-bad { color: var(--red); }
.delta-neutral { color: var(--yellow); }
.tag-badge { display: inline-block; font-size: 9px; padding: 1px 5px; border-radius: 8px; font-weight: 600; margin-left: 4px; }
.badge-helps { background: #0d2818; color: var(--green); }
.badge-hurts { background: #2d1117; color: var(--red); }
.badge-mixed { background: #2d2200; color: var(--yellow); }

/* Main */
#main { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
#tab-bar { display: flex; gap: 0; border-bottom: 1px solid var(--border); background: var(--surface); }
.tab { padding: 10px 20px; cursor: pointer; font-size: 13px; font-weight: 600; color: var(--text2);
       border-bottom: 2px solid transparent; transition: all 0.15s; }
.tab:hover { color: var(--text); }
.tab.active { color: var(--text); border-bottom-color: var(--accent); }
#content { flex: 1; overflow-y: auto; padding: 24px; }

/* Analysis styles */
#analysis h1 { font-size: 22px; margin-bottom: 12px; }
#analysis h2 { font-size: 18px; margin: 20px 0 8px; border-bottom: 1px solid var(--border); padding-bottom: 6px; }
#analysis h3 { font-size: 15px; margin: 16px 0 6px; }
#analysis p { margin: 8px 0; line-height: 1.65; font-size: 14px; }
#analysis ul { margin: 8px 0 8px 20px; }
#analysis li { margin: 4px 0; line-height: 1.6; font-size: 14px; }
#analysis strong { color: #fff; }
#analysis code { background: var(--bg); padding: 2px 6px; border-radius: 4px; font-size: 12px; }
#analysis .code-block { background: var(--bg); padding: 12px; border-radius: 6px; font-size: 12px;
                        overflow-x: auto; margin: 8px 0; }

/* Responses */
.question-block { margin-bottom: 32px; border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
.question-header { background: var(--surface); padding: 14px 16px; border-bottom: 1px solid var(--border);
                   display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; }
.question-id { font-weight: 700; font-size: 14px; color: var(--accent); white-space: nowrap; }
.question-prompt { font-size: 13px; line-height: 1.5; flex: 1; }
.question-avgs { white-space: nowrap; font-size: 12px; text-align: right; }
.rubric-toggle { cursor: pointer; color: var(--accent); font-size: 12px; padding: 4px 0; }
.rubric-text { font-size: 12px; color: var(--text2); line-height: 1.6; padding: 8px 16px;
               background: #0d1117; border-bottom: 1px solid var(--border); display: none; }
.rubric-text.show { display: block; }

/* Response table */
.resp-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.resp-table th { background: var(--surface); padding: 8px 12px; text-align: left; font-size: 11px;
                 text-transform: uppercase; color: var(--text2); border-bottom: 1px solid var(--border); }
.resp-table td { padding: 8px 12px; border-bottom: 1px solid var(--border); vertical-align: top; }
.resp-table tr:hover { background: #1c2128; }
.score-cell { font-weight: 700; font-size: 14px; text-align: center; width: 50px; }
.expandable { position: relative; cursor: pointer; line-height: 1.5; color: var(--text2);
             white-space: pre-wrap; word-break: break-word; }
.expandable.collapsed { max-height: 120px; overflow: hidden; }
.expandable.collapsed::after { content: '\a0\a0\a0▾ click to expand'; position: absolute; bottom: 0; left: 0; right: 0;
                               padding-top: 20px; background: linear-gradient(transparent, var(--bg));
                               text-align: center; font-size: 10px; color: var(--accent); pointer-events: none; }
.expandable.expanded { max-height: none; overflow: visible; }
.expandable.expanded::after { display: none; }
.response-text { font-size: 12px; }
.judge-text { font-size: 11px; }
.expandable.collapsed.judge-text { max-height: 80px; }
.model-label { font-size: 10px; text-transform: uppercase; font-weight: 700; letter-spacing: 0.5px;
               padding: 2px 6px; border-radius: 3px; }
.label-base { background: #1c2128; color: var(--text2); }
.label-sft { background: #0d2818; color: var(--green); }

/* Empty state */
.empty-state { text-align: center; padding: 80px 20px; color: var(--text2); }
.empty-state h3 { font-size: 18px; margin-bottom: 8px; color: var(--text); }

/* Loading */
.loading { text-align: center; padding: 40px; color: var(--text2); }

/* Scrollbar */
::-webkit-scrollbar { width: 8px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--border); border-radius: 4px; }
::-webkit-scrollbar-thumb:hover { background: #484f58; }
</style>
</head>
<body>

<div id="sidebar">
  <div id="sidebar-header">
    <h2>Petri Safety Tags</h2>
    <input id="search" type="text" placeholder="Filter tags...">
  </div>
  <div id="tag-list"></div>
</div>

<div id="main">
  <div id="tab-bar">
    <div class="tab active" data-tab="analysis">Analysis</div>
    <div class="tab" data-tab="responses">Responses</div>
  </div>
  <div id="content">
    <div class="empty-state">
      <h3>Select a tag from the sidebar</h3>
      <p>Click on any tag to view its analysis and raw responses.</p>
    </div>
  </div>
</div>

<script>
let currentTag = null;
let currentTab = 'analysis';
let tagsData = [];

function scoreColor(score) {
  if (score === null || score === undefined) return 'var(--text2)';
  const s = parseFloat(score);
  if (s <= -3) return '#3fb950';
  if (s <= -1) return '#56d364';
  if (s < 1) return '#d29922';
  if (s < 3) return '#f0883e';
  return '#f85149';
}

function deltaClass(d) {
  const v = parseFloat(d);
  if (v <= -1.5) return 'delta-good';
  if (v >= 1.0) return 'delta-bad';
  return 'delta-neutral';
}

function badgeClass(d) {
  const v = parseFloat(d);
  if (v <= -1.5) return 'badge-helps';
  if (v >= 1.0) return 'badge-hurts';
  return 'badge-mixed';
}

function badgeLabel(d) {
  const v = parseFloat(d);
  if (v <= -1.5) return 'HELPS';
  if (v >= 1.0) return 'HURTS';
  return 'MIXED';
}

function escapeHtml(t) {
  const d = document.createElement('div');
  d.textContent = t;
  return d.innerHTML;
}

// Load tags
async function loadTags() {
  const resp = await fetch('/api/tags');
  tagsData = await resp.json();
  renderTagList();
}

function renderTagList(filter = '') {
  const list = document.getElementById('tag-list');
  const f = filter.toLowerCase();
  const filtered = tagsData.filter(t => t.tag !== 'ALL' && t.tag.toLowerCase().includes(f));

  list.innerHTML = filtered.map(t => `
    <div class="tag-item ${t.tag === currentTag ? 'active' : ''}" onclick="selectTag('${t.tag}')">
      <div>
        <span class="tag-name">${t.tag}</span> <span style="color:var(--text2);font-size:11px">(${t.n_questions}q)</span>
        <span class="tag-badge ${badgeClass(t.diff)}">${badgeLabel(t.diff)}</span>
      </div>
      <div class="tag-scores">
        <div>Base <strong style="color:${scoreColor(t.base_avg)}">${parseFloat(t.base_avg).toFixed(2)}</strong></div>
        <div>SFT <strong style="color:${scoreColor(t.sft_avg)}">${parseFloat(t.sft_avg).toFixed(2)}</strong></div>
        <div class="delta ${deltaClass(t.diff)}">&Delta; ${parseFloat(t.diff) > 0 ? '+' : ''}${parseFloat(t.diff).toFixed(2)}</div>
      </div>
    </div>
  `).join('');
}

async function selectTag(tag) {
  currentTag = tag;
  renderTagList(document.getElementById('search').value);
  await renderContent();
}

// Tabs
document.querySelectorAll('.tab').forEach(tab => {
  tab.addEventListener('click', async () => {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    tab.classList.add('active');
    currentTab = tab.dataset.tab;
    if (currentTag) await renderContent();
  });
});

async function renderContent() {
  const content = document.getElementById('content');
  if (!currentTag) return;
  content.innerHTML = '<div class="loading">Loading...</div>';

  if (currentTab === 'analysis') {
    const resp = await fetch(`/api/analysis/${currentTag}`);
    const html = await resp.text();
    content.innerHTML = `<div id="analysis">${html}</div>`;
  } else {
    const resp = await fetch(`/api/responses/${currentTag}`);
    if (!resp.ok) {
      content.innerHTML = '<div class="empty-state"><h3>No response data</h3></div>';
      return;
    }
    const data = await resp.json();
    renderResponses(content, data);
  }
}

function renderResponses(container, data) {
  if (!data.questions || !data.questions.length) {
    container.innerHTML = '<div class="empty-state"><h3>No questions found</h3></div>';
    return;
  }

  container.innerHTML = data.questions.map((q, qi) => {
    const baseAvg = q.base_avg !== undefined ? parseFloat(q.base_avg).toFixed(2) : '—';
    const sftAvg = q.sft_avg !== undefined ? parseFloat(q.sft_avg).toFixed(2) : '—';
    const delta = (q.base_avg !== undefined && q.sft_avg !== undefined)
      ? (parseFloat(q.sft_avg) - parseFloat(q.base_avg)).toFixed(2) : '—';
    const deltaNum = parseFloat(delta);
    const deltaSign = deltaNum > 0 ? '+' : '';

    // Interleave base and sft responses by epoch
    const maxEpochs = Math.max(
      (q.base_responses || []).length,
      (q.sft_responses || []).length
    );

    let rows = '';
    for (let e = 0; e < maxEpochs; e++) {
      const br = (q.base_responses || [])[e];
      const sr = (q.sft_responses || [])[e];
      if (br) {
        rows += responseRow('base', br, e);
      }
      if (sr) {
        rows += responseRow('sft', sr, e);
      }
    }

    return `
      <div class="question-block">
        <div class="question-header">
          <span class="question-id">${escapeHtml(q.id)}</span>
          <div class="question-prompt expandable collapsed response-text" onclick="toggleExpand(this)">${escapeHtml(q.prompt || '')}</div>
          <div class="question-avgs">
            Base: <strong style="color:${scoreColor(baseAvg)}">${baseAvg}</strong><br>
            SFT: <strong style="color:${scoreColor(sftAvg)}">${sftAvg}</strong><br>
            <span class="delta ${deltaClass(delta)}">&Delta; ${deltaSign}${delta}</span>
          </div>
        </div>
        <div class="rubric-toggle" onclick="this.nextElementSibling.classList.toggle('show')">
          ▸ Show rubric
        </div>
        <div class="rubric-text">${escapeHtml(q.rubric || 'No rubric available')}</div>
        <table class="resp-table">
          <thead>
            <tr>
              <th>Model</th>
              <th style="width:40px">Ep.</th>
              <th style="width:50px">Score</th>
              <th>Response</th>
              <th style="width:250px">Judge Explanation</th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    `;
  }).join('');
}

function responseRow(model, r, epochIdx) {
  const label = model === 'base'
    ? '<span class="model-label label-base">BASE</span>'
    : '<span class="model-label label-sft">SFT</span>';
  const score = r.score !== undefined ? r.score : '—';
  const epoch = r.epoch !== undefined ? r.epoch : epochIdx + 1;

  return `<tr>
    <td>${label}</td>
    <td style="text-align:center">${epoch}</td>
    <td class="score-cell" style="color:${scoreColor(score)}">${score}</td>
    <td><div class="expandable collapsed response-text" onclick="toggleExpand(this)">${escapeHtml(r.response || '')}</div></td>
    <td><div class="expandable collapsed judge-text" onclick="toggleExpand(this)">${escapeHtml(r.judge_explanation || '')}</div></td>
  </tr>`;
}

function toggleExpand(el) {
  if (el.classList.contains('collapsed')) {
    el.classList.remove('collapsed');
    el.classList.add('expanded');
  } else {
    el.classList.remove('expanded');
    el.classList.add('collapsed');
  }
}

// Search
document.getElementById('search').addEventListener('input', e => {
  renderTagList(e.target.value);
});

// Init
loadTags();
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = unquote(self.path)

        if path == "/" or path == "":
            self._html(INDEX_HTML)
        elif path == "/api/tags":
            self._json(load_tags())
        elif path.startswith("/api/analysis/"):
            tag = path.split("/api/analysis/", 1)[1].strip("/")
            self._html(load_analysis(tag))
        elif path.startswith("/api/responses/"):
            tag = path.split("/api/responses/", 1)[1].strip("/")
            data = load_responses(tag)
            if data is None:
                self.send_error(404)
                return
            self._json(data)
        else:
            self.send_error(404)

    def _html(self, body: str):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body.encode())

    def _json(self, obj):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(obj).encode())

    def log_message(self, fmt, *args):
        # Quieter logging
        pass


class ReusableHTTPServer(HTTPServer):
    allow_reuse_address = True


def main():
    server = ReusableHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Petri Tag Viewer running at http://localhost:{PORT}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        server.server_close()


if __name__ == "__main__":
    main()
