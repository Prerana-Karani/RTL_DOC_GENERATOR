"""
output/writer.py

Writes generated documentation to disk:
  • Individual Markdown files per module  →  docs/<module>.md
  • Combined HTML report                 →  docs/index.html

Uses Jinja2 for the HTML template and a built-in Markdown renderer.
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from jinja2 import Environment, BaseLoader

from parser.rtl_parser import ModuleInfo
from graph.hierarchy import HierarchyGraph


DOCS_DIR = "./docs"


# ──────────────────────────────────────────────────────────────────────────────
# Jinja2 HTML template
# ──────────────────────────────────────────────────────────────────────────────

HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>RTL Documentation — {{ project_name }}</title>
<style>
  :root{--bg:#0f1117;--surf:#1a1d2e;--surf2:#252840;--border:#2e3150;
    --acc:#6c8eff;--acc2:#a78bfa;--txt:#e2e8f0;--muted:#94a3b8;
    --green:#34d399;--red:#f87171;--yellow:#fbbf24;--code-bg:#0d1117;
    --font:'Segoe UI',system-ui,sans-serif;--mono:'Fira Code','Consolas',monospace;}
  *{box-sizing:border-box;margin:0;padding:0;}
  body{background:var(--bg);color:var(--txt);font-family:var(--font);
    font-size:15px;line-height:1.7;}
  #sidebar{position:fixed;top:0;left:0;width:260px;height:100vh;
    background:var(--surf);border-right:1px solid var(--border);
    overflow-y:auto;padding:24px 0;z-index:100;}
  #sidebar .logo{padding:0 20px 20px;border-bottom:1px solid var(--border);margin-bottom:16px;}
  #sidebar .logo h2{font-size:13px;font-weight:700;color:var(--acc);
    letter-spacing:.06em;text-transform:uppercase;}
  #sidebar .logo p{font-size:11px;color:var(--muted);margin-top:4px;}
  #sidebar nav a{display:block;padding:7px 20px;color:var(--muted);
    text-decoration:none;font-size:13px;border-left:3px solid transparent;transition:all .15s;}
  #sidebar nav a:hover,#sidebar nav a.active{color:var(--txt);
    background:var(--surf2);border-left-color:var(--acc);}
  .nav-label{padding:12px 20px 4px;font-size:10px;color:var(--muted);
    text-transform:uppercase;letter-spacing:.08em;font-weight:600;}
  #main{margin-left:260px;padding:40px 48px;max-width:960px;}
  .hero{background:linear-gradient(135deg,var(--surf),var(--surf2));
    border:1px solid var(--border);border-radius:12px;padding:36px;margin-bottom:40px;}
  .hero h1{font-size:26px;font-weight:700;margin-bottom:6px;}
  .hero p{color:var(--muted);}
  .meta{display:flex;gap:20px;margin-top:18px;flex-wrap:wrap;}
  .meta-item{background:var(--surf);border:1px solid var(--border);
    border-radius:8px;padding:10px 16px;text-align:center;}
  .meta-item .val{font-size:22px;font-weight:700;color:var(--acc);}
  .meta-item .lbl{font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;}
  .tags{display:flex;gap:8px;flex-wrap:wrap;margin-top:14px;}
  .tag{background:#1e3a5f;color:var(--acc);border:1px solid var(--acc);
    border-radius:4px;padding:2px 8px;font-size:12px;font-family:var(--mono);}
  .card{background:var(--surf);border:1px solid var(--border);
    border-radius:10px;margin-bottom:36px;overflow:hidden;}
  .card-header{padding:18px 26px;border-bottom:1px solid var(--border);
    display:flex;align-items:center;justify-content:space-between;background:var(--surf2);}
  .card-header h2{font-size:19px;font-weight:600;font-family:var(--mono);}
  .badges{display:flex;gap:8px;}
  .badge{padding:3px 10px;border-radius:20px;font-size:10px;font-weight:600;
    text-transform:uppercase;letter-spacing:.04em;}
  .b-green{background:rgba(52,211,153,.15);color:var(--green);}
  .b-blue{background:rgba(108,142,255,.15);color:var(--acc);}
  .b-purple{background:rgba(167,139,250,.15);color:var(--acc2);}
  .b-red{background:rgba(248,113,113,.15);color:var(--red);}
  .card-body{padding:26px;}
  /* Port grid */
  .port-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));
    gap:8px;margin:12px 0 20px;}
  .port-card{background:var(--code-bg);border:1px solid var(--border);
    border-radius:6px;padding:9px 13px;font-family:var(--mono);font-size:12px;}
  .port-card .pname{font-weight:600;}
  .port-card .pmeta{color:var(--muted);font-size:11px;margin-top:2px;}
  /* Markdown-rendered content */
  .md h2{font-size:16px;font-weight:600;color:var(--acc2);
    margin:22px 0 8px;padding-bottom:5px;border-bottom:1px solid var(--border);}
  .md h3{font-size:14px;font-weight:600;color:var(--acc);margin:14px 0 5px;}
  .md p{margin-bottom:10px;}
  .md ul,.md ol{margin:6px 0 10px 20px;}
  .md li{margin-bottom:3px;}
  .md code{background:var(--code-bg);color:#a5f3fc;font-family:var(--mono);
    font-size:12px;padding:2px 6px;border-radius:4px;border:1px solid var(--border);}
  .md pre{background:var(--code-bg);border:1px solid var(--border);
    border-radius:8px;padding:14px 18px;overflow-x:auto;margin:10px 0;}
  .md pre code{border:none;padding:0;color:#c3e88d;}
  .md table{width:100%;border-collapse:collapse;margin:10px 0;font-size:13px;}
  .md th{background:var(--surf2);color:var(--acc);padding:7px 11px;
    text-align:left;font-weight:600;border:1px solid var(--border);}
  .md td{padding:7px 11px;border:1px solid var(--border);}
  .md tr:nth-child(even) td{background:rgba(255,255,255,.02);}
  /* Hierarchy tree */
  .hier{background:var(--code-bg);border:1px solid var(--border);
    border-radius:8px;padding:14px 18px;font-family:var(--mono);font-size:13px;}
  .hier .root{color:var(--acc2);}
  .hier .child{color:var(--acc);padding-left:22px;}
  footer{text-align:center;padding:32px;color:var(--muted);font-size:13px;
    border-top:1px solid var(--border);margin-top:40px;}
  ::-webkit-scrollbar{width:5px;}
  ::-webkit-scrollbar-track{background:var(--bg);}
  ::-webkit-scrollbar-thumb{background:var(--border);border-radius:3px;}
</style>
</head>
<body>
<div id="sidebar">
  <div class="logo">
    <h2>RTL Docs</h2>
    <p>{{ project_name }}</p>
  </div>
  <nav>
    <div class="nav-label">Overview</div>
    <a href="#summary">Project Summary</a>
    <a href="#hierarchy">Module Hierarchy</a>
    <div class="nav-label">Modules</div>
    {% for name in module_names %}<a href="#{{ name }}">{{ name }}</a>
    {% endfor %}
  </nav>
</div>

<div id="main">
  <!-- Hero -->
  <div class="hero" id="summary">
    <h1>RTL Documentation</h1>
    <p>{{ project_name }} &mdash; Auto-generated via RAG + LLM pipeline</p>
    <div class="meta">
      <div class="meta-item"><div class="val">{{ module_count }}</div><div class="lbl">Modules</div></div>
      <div class="meta-item"><div class="val">{{ port_count }}</div><div class="lbl">Total Ports</div></div>
      <div class="meta-item"><div class="val">{{ date }}</div><div class="lbl">Generated</div></div>
    </div>
    <div class="tags">
      {% for t in tags %}<span class="tag">{{ t }}</span>{% endfor %}
    </div>
  </div>

  <!-- Hierarchy -->
  <div class="card" id="hierarchy">
    <div class="card-header">
      <h2>Module Hierarchy</h2>
      <div class="badges"><span class="badge b-blue">Design Tree</span></div>
    </div>
    <div class="card-body">
      <div class="hier">{{ hierarchy_tree | safe }}</div>
    </div>
  </div>

  <!-- Per-module sections -->
  {% for name, doc_html in modules %}
  {% set mod = module_map[name] %}
  <div class="card" id="{{ name }}">
    <div class="card-header">
      <h2>{{ name }}</h2>
      <div class="badges">
        {% if mod.fsm_states %}<span class="badge b-purple">FSM</span>{% endif %}
        {% if mod.instantiations %}<span class="badge b-green">Hierarchical</span>{% endif %}
        {% if mod.parameters %}<span class="badge b-blue">Parametric</span>{% endif %}
        {% if not mod.fsm_states and not mod.instantiations and not mod.parameters %}
          <span class="badge b-red">Leaf</span>{% endif %}
      </div>
    </div>
    <div class="card-body">
      <!-- Port quick-view -->
      {% if mod.ports %}
      <div class="port-grid">
        {% for p in mod.ports[:10] %}
        <div class="port-card">
          <div class="pname" style="color:{% if p.direction=='input' %}#6c8eff{% elif p.direction=='output' %}#f87171{% else %}#fbbf24{% endif %}">{{ p.name }}</div>
          <div class="pmeta">{{ p.direction }} &nbsp;·&nbsp; {{ p.width }}</div>
        </div>
        {% endfor %}
        {% if mod.ports|length > 10 %}
        <div class="port-card" style="display:flex;align-items:center;justify-content:center;color:#94a3b8">
          +{{ mod.ports|length - 10 }} more
        </div>
        {% endif %}
      </div>
      {% endif %}
      <!-- Generated documentation -->
      <div class="md">{{ doc_html | safe }}</div>
    </div>
  </div>
  {% endfor %}

  <footer>
    Generated by RTL Documentation Generator &bull; RAG + Groq LLM &bull; {{ date }}
  </footer>
</div>

<script>
const links = document.querySelectorAll('#sidebar nav a');
const observer = new IntersectionObserver(entries => {
  entries.forEach(e => {
    if (e.isIntersecting) {
      links.forEach(l => l.classList.remove('active'));
      const l = document.querySelector(`#sidebar nav a[href="#${e.target.id}"]`);
      if (l) l.classList.add('active');
    }
  });
}, { rootMargin: '-15% 0px -75% 0px' });
document.querySelectorAll('[id]').forEach(el => observer.observe(el));
</script>
</body>
</html>
"""


# ──────────────────────────────────────────────────────────────────────────────
# Minimal Markdown → HTML converter (no extra deps)
# ──────────────────────────────────────────────────────────────────────────────

def _md_to_html(md: str) -> str:
    lines = md.split("\n")
    out: List[str] = []
    in_code = False
    in_table = False
    in_list = False
    in_ol = False

    for raw in lines:
        line = raw

        # Fenced code block
        if line.strip().startswith("```"):
            if not in_code:
                lang = line.strip()[3:].strip() or ""
                out.append(f'<pre><code class="lang-{lang}">')
                in_code = True
            else:
                out.append("</code></pre>")
                in_code = False
            continue
        if in_code:
            out.append(
                line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            )
            continue

        # Close open lists / tables if needed
        if in_list and not re.match(r"^[-*+] ", line):
            out.append("</ul>"); in_list = False
        if in_ol and not re.match(r"^\d+\. ", line):
            out.append("</ol>"); in_ol = False
        if in_table and not (line.strip().startswith("|") and "|" in line):
            out.append("</table>"); in_table = False

        # Table
        if line.strip().startswith("|") and "|" in line:
            if re.match(r"^\|[\s\-|:]+\|$", line.strip()):
                continue  # separator row
            if not in_table:
                out.append('<table>'); in_table = True
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            # First row = header if table just opened
            tag = "th" if out[-1] == "<table>" else "td"
            row = "".join(f"<{tag}>{_inline(c)}</{tag}>" for c in cells)
            out.append(f"<tr>{row}</tr>")
            continue

        # Headings
        if line.startswith("#### "):
            out.append(f"<h4>{_inline(line[5:])}</h4>")
        elif line.startswith("### "):
            out.append(f"<h3>{_inline(line[4:])}</h3>")
        elif line.startswith("## "):
            out.append(f"<h2>{_inline(line[3:])}</h2>")
        elif line.startswith("# "):
            out.append(f"<h2>{_inline(line[2:])}</h2>")
        # Unordered list
        elif re.match(r"^[-*+] ", line):
            if not in_list:
                out.append("<ul>"); in_list = True
            out.append(f"<li>{_inline(line[2:])}</li>")
        # Ordered list
        elif re.match(r"^\d+\. ", line):
            if not in_ol:
                out.append("<ol>"); in_ol = True
            out.append(f"<li>{_inline(re.sub(r'^\d+\. ', '', line))}</li>")
        # Blank line
        elif not line.strip():
            out.append("")
        # Paragraph
        else:
            out.append(f"<p>{_inline(line)}</p>")

    # Close dangling tags
    if in_list:  out.append("</ul>")
    if in_ol:    out.append("</ol>")
    if in_table: out.append("</table>")
    if in_code:  out.append("</code></pre>")
    return "\n".join(out)


def _inline(text: str) -> str:
    """Apply inline Markdown formatting."""
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", text)
    text = re.sub(r"_([^_]+)_", r"<em>\1</em>", text)
    return text


# ──────────────────────────────────────────────────────────────────────────────
# Writer
# ──────────────────────────────────────────────────────────────────────────────

class DocWriter:
    """Writes Markdown and HTML documentation files to docs/."""

    def __init__(self, output_dir: str = DOCS_DIR):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    # ── Public API ────────────────────────────────────────────────────────────

    def write_markdown(self, documentation: Dict[str, str]) -> List[str]:
        """Write one .md file per module. Returns list of file paths."""
        paths: List[str] = []
        for name, doc in documentation.items():
            out = self.output_dir / f"{name}.md"
            out.write_text(f"# {name}\n\n{doc}", encoding="utf-8")
            paths.append(str(out))
        return paths

    def write_html_report(
        self,
        project_name: str,
        modules_by_name: Dict[str, ModuleInfo],
        documentation: Dict[str, str],
        graph: HierarchyGraph,
        summaries: Dict[str, str],
    ) -> str:
        """Render and write the combined HTML report. Returns output path."""
        env = Environment(loader=BaseLoader())
        template = env.from_string(HTML_TEMPLATE)

        total_ports = sum(len(m.ports) for m in modules_by_name.values())
        hier_tree   = self._build_hier_tree(graph)
        module_names = sorted(documentation.keys())

        # Convert each module's markdown to HTML
        modules_rendered = [
            (name, _md_to_html(documentation[name]))
            for name in module_names
        ]

        tags = ["Verilog", "SystemVerilog", "PyVerilog", "NetworkX",
                "ChromaDB", "Groq", "RAG", "LLM"]

        html = template.render(
            project_name   = project_name,
            module_count   = len(documentation),
            port_count     = total_ports,
            date           = datetime.now().strftime("%Y-%m-%d"),
            tags           = tags,
            hierarchy_tree = hier_tree,
            module_names   = module_names,
            modules        = modules_rendered,
            module_map     = modules_by_name,
        )

        out = self.output_dir / "index.html"
        out.write_text(html, encoding="utf-8")
        return str(out)

    # ── Internal ──────────────────────────────────────────────────────────────

    @staticmethod
    def _build_hier_tree(graph: HierarchyGraph) -> str:
        lines: List[str] = []
        visited: set = set()

        def _render(name: str, depth: int):
            if name in visited:
                lines.append("  " * depth + f'<span style="color:#94a3b8">↩ {name}</span>')
                return
            visited.add(name)
            cls = "root" if depth == 0 else "child"
            prefix = "  " * depth + ("└─ " if depth > 0 else "")
            lines.append(f'<div class="{cls}">{prefix}{name}</div>')
            for child in sorted(graph.children_of(name)):
                _render(child, depth + 1)

        roots = graph.top_level_modules() or sorted(graph.modules.keys())
        for r in roots:
            _render(r, 0)

        return "\n".join(lines) if lines else '<div style="color:#94a3b8">No hierarchy detected</div>'
