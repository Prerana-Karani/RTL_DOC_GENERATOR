"""
app.py  —  Streamlit GUI for RTL Documentation Generator

Run with:
    streamlit run app.py
"""

import os
import sys
import shutil
import tempfile
import time
import threading
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

# ── Page config (must be first Streamlit call) ────────────────────────────────
st.set_page_config(
    page_title="RTL Doc Generator",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
  /* Dark theme tweaks */
  .stApp { background: #0f1117; }

  /* File uploader */
  [data-testid="stFileUploader"] {
    border: 2px dashed #2e3150;
    border-radius: 12px;
    padding: 12px;
    background: #1a1d2e;
  }

  /* Metric cards */
  [data-testid="metric-container"] {
    background: #1a1d2e;
    border: 1px solid #2e3150;
    border-radius: 10px;
    padding: 16px;
  }

  /* Stage progress pills */
  .stage-pill {
    display: inline-block;
    padding: 4px 14px;
    border-radius: 20px;
    font-size: 13px;
    font-weight: 600;
    margin: 3px 0;
  }
  .stage-done    { background: rgba(52,211,153,.15); color: #34d399; }
  .stage-running { background: rgba(251,191,36,.15);  color: #fbbf24; }
  .stage-pending { background: rgba(148,163,184,.10); color: #94a3b8; }
  .stage-error   { background: rgba(248,113,113,.15); color: #f87171; }

  /* Module cards in results */
  .mod-card {
    background: #1a1d2e;
    border: 1px solid #2e3150;
    border-radius: 10px;
    padding: 16px 20px;
    margin-bottom: 12px;
  }
  .mod-card h4 {
    font-family: monospace;
    color: #6c8eff;
    margin-bottom: 6px;
  }

  /* Port badges */
  .port-in  { color: #6c8eff; font-weight: 600; }
  .port-out { color: #f87171; font-weight: 600; }

  /* Hide default streamlit header */
  #MainMenu, footer { visibility: hidden; }
</style>
""", unsafe_allow_html=True)


# ── Session state defaults ────────────────────────────────────────────────────
def _init_state():
    defaults = {
        "stage":        "idle",       # idle | running | done | error
        "logs":         [],
        "modules":      {},
        "summaries":    {},
        "docs":         {},
        "graph":        None,
        "html_path":    None,
        "error_msg":    "",
        "stage_status": {             # per-stage status
            "parse":     "pending",
            "summarise": "pending",
            "embed":     "pending",
            "generate":  "pending",
            "write":     "pending",
        },
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init_state()


# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## ⚡ RTL Doc Generator")
    st.markdown("Automated documentation via **RAG + LLM**")
    st.divider()

    st.markdown("### Configuration")

    # API key is loaded from .env / Streamlit Secrets — never shown in UI
    groq_key = os.getenv("GROQ_API_KEY", "")
    if groq_key:
        st.success("🔑 API key loaded", icon="✅")
    else:
        st.error("GROQ_API_KEY not set. Add it to Streamlit Secrets.", icon="🔒")

    project_name = st.text_input(
        "Project Name",
        value="My RTL Design",
        placeholder="e.g. AXI SoC",
    )

    groq_model = st.selectbox(
        "Groq Model",
        options=[
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant",
            "mixtral-8x7b-32768",
            "gemma2-9b-it",
        ],
        index=0,
        help="Larger models = better docs but slower",
    )

    st.divider()
    st.markdown("### Pipeline Stages")

    stage_labels = {
        "parse":     "1 · Parse RTL",
        "summarise": "2 · Summarise (LLM)",
        "embed":     "3 · Embed (ChromaDB)",
        "generate":  "4 · Generate Docs (RAG)",
        "write":     "5 · Write Output",
    }
    for key, label in stage_labels.items():
        status = st.session_state.stage_status[key]
        css = {
            "pending": "stage-pending",
            "running": "stage-running",
            "done":    "stage-done",
            "error":   "stage-error",
        }[status]
        icon = {"pending": "○", "running": "◎", "done": "✓", "error": "✗"}[status]
        st.markdown(
            f'<div class="stage-pill {css}">{icon}  {label}</div>',
            unsafe_allow_html=True,
        )

    st.divider()
    st.caption("Built with PyVerilog · ChromaDB · Groq · Streamlit")


# ── Main area ─────────────────────────────────────────────────────────────────
st.markdown("# RTL Documentation Generator")
st.markdown(
    "Upload your Verilog / SystemVerilog files below, then click **Generate Docs**."
)

# ── Upload zone ───────────────────────────────────────────────────────────────
uploaded_files = st.file_uploader(
    "Upload RTL files",
    type=["v", "sv", "vh", "svh"],
    accept_multiple_files=True,
    help="Drag & drop or click to browse. Multiple files supported.",
)

if uploaded_files:
    st.success(f"✓  {len(uploaded_files)} file(s) ready: "
               + "  ·  ".join(f"`{f.name}`" for f in uploaded_files))

# ── Controls ──────────────────────────────────────────────────────────────────
col_btn, col_reset, col_spacer = st.columns([2, 1, 6])

with col_btn:
    run_disabled = (
        not uploaded_files
        or not groq_key
        or st.session_state.stage == "running"
    )
    run_clicked = st.button(
        "⚡ Generate Docs",
        disabled=run_disabled,
        type="primary",
        use_container_width=True,
    )

with col_reset:
    if st.button("↺ Reset", use_container_width=True):
        for key in ["stage", "logs", "modules", "summaries", "docs",
                    "graph", "html_path", "error_msg"]:
            del st.session_state[key]
        for k in list(st.session_state.stage_status.keys()):
            st.session_state.stage_status[k] = "pending"
        st.rerun()

if not groq_key:
    st.warning("⚠️  GROQ_API_KEY not found. Add it to Streamlit Secrets before generating docs.")

# ── Pipeline runner ───────────────────────────────────────────────────────────

def _set_stage(name: str, status: str):
    st.session_state.stage_status[name] = status

def _log(msg: str):
    st.session_state.logs.append(msg)

def run_pipeline(files, proj_name: str, model: str):
    """Full pipeline — called when Generate Docs is clicked."""

    st.session_state.stage     = "running"
    st.session_state.logs      = []
    st.session_state.docs      = {}
    st.session_state.html_path = None
    st.session_state.error_msg = ""
    for k in st.session_state.stage_status:
        st.session_state.stage_status[k] = "pending"

    # Write uploaded files to a temp directory
    tmp_dir = tempfile.mkdtemp(prefix="rtl_")
    out_dir = tempfile.mkdtemp(prefix="rtl_docs_")
    chroma_dir = os.path.join(tmp_dir, "chroma")

    try:
        # Save uploads
        for f in files:
            dest = Path(tmp_dir) / f.name
            dest.write_bytes(f.read())
        _log(f"Saved {len(files)} file(s) to temp directory")

        # ── Stage 1: Parse ────────────────────────────────────────────────────
        _set_stage("parse", "running")
        _log("Parsing RTL files…")

        from parser.rtl_parser import RTLParser
        from graph.hierarchy import HierarchyGraph

        parser  = RTLParser()
        modules = parser.parse_directory(tmp_dir)

        if not modules:
            raise ValueError("No modules found in uploaded files. "
                             "Check that your files contain valid 'module … endmodule' blocks.")

        modules_by_name = {m.module_name: m for m in modules}
        graph = HierarchyGraph(modules)

        st.session_state.modules = modules_by_name
        st.session_state.graph   = graph
        _log(f"Parsed {len(modules)} module(s): "
             + ", ".join(f"`{n}`" for n in modules_by_name))
        _log(f"Top-level: {graph.top_level_modules()}  |  "
             f"Leaves: {graph.leaf_modules()}")
        _set_stage("parse", "done")

        # ── Stage 2: Summarise ────────────────────────────────────────────────
        _set_stage("summarise", "running")
        _log("Running bottom-up LLM summarisation…")

        from summariser.bottom_up import BottomUpSummariser

        def _prog(cur, tot, name):
            _log(f"  Summarising {name} ({cur}/{tot})")

        summariser = BottomUpSummariser(model=model, progress_callback=_prog)
        summaries  = summariser.run(modules_by_name, graph)
        st.session_state.summaries = summaries
        _log(f"Summarised {len(summaries)} module(s)")
        _set_stage("summarise", "done")

        # ── Stage 3: Embed ────────────────────────────────────────────────────
        _set_stage("embed", "running")
        _log("Indexing into ChromaDB…")

        from rag.embedder import RTLEmbedder

        embedder = RTLEmbedder(persist_dir=chroma_dir)
        embedder.index_modules(modules, summaries)
        _log(f"ChromaDB: {embedder.collection_size()} chunks indexed")
        _set_stage("embed", "done")

        # ── Stage 4: Generate docs ────────────────────────────────────────────
        _set_stage("generate", "running")
        _log("Generating full documentation via RAG…")

        from rag.generator import DocGenerator

        def _dprog(cur, tot, name):
            _log(f"  Documenting {name} ({cur}/{tot})")

        generator = DocGenerator(
            embedder=embedder,
            model=model,
            progress_callback=_dprog,
        )
        docs = generator.generate_all(
            modules_by_name = modules_by_name,
            bottom_up_order = graph.bottom_up_order(),
            summaries       = summaries,
            graph           = graph,
        )
        st.session_state.docs = docs
        _log(f"Generated docs for {len(docs)} module(s)")
        _set_stage("generate", "done")

        # ── Stage 5: Write output ─────────────────────────────────────────────
        _set_stage("write", "running")
        _log("Writing HTML report…")

        from output.writer import DocWriter

        writer    = DocWriter(output_dir=out_dir)
        writer.write_markdown(docs)
        html_path = writer.write_html_report(
            project_name    = proj_name,
            modules_by_name = modules_by_name,
            documentation   = docs,
            graph           = graph,
            summaries       = summaries,
        )
        st.session_state.html_path = html_path
        _log(f"Report written: {html_path}")
        _set_stage("write", "done")

        st.session_state.stage = "done"
        _log("✅ Pipeline complete!")

    except Exception as exc:
        import traceback
        st.session_state.stage     = "error"
        st.session_state.error_msg = str(exc)
        _log(f"❌ Error: {exc}")
        _log(traceback.format_exc())
        # Mark current running stage as error
        for k, v in st.session_state.stage_status.items():
            if v == "running":
                st.session_state.stage_status[k] = "error"

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ── Trigger pipeline ──────────────────────────────────────────────────────────
if run_clicked and uploaded_files and groq_key:
    run_pipeline(uploaded_files, project_name, groq_model)
    st.rerun()


# ── Progress / log display ────────────────────────────────────────────────────
if st.session_state.stage in ("running", "done", "error"):
    st.divider()
    st.markdown("### Pipeline Log")
    log_box = st.container(border=True)
    with log_box:
        for line in st.session_state.logs:
            if line.startswith("❌"):
                st.error(line)
            elif line.startswith("✅"):
                st.success(line)
            elif line.strip().startswith("Summarising") or line.strip().startswith("Documenting"):
                st.caption(line)
            else:
                st.text(line)

if st.session_state.stage == "error":
    st.error(f"**Pipeline failed:** {st.session_state.error_msg}")


# ── Results ───────────────────────────────────────────────────────────────────
if st.session_state.stage == "done" and st.session_state.docs:
    st.divider()
    st.markdown("## ✅ Results")

    # Metrics row
    modules_by_name = st.session_state.modules
    graph           = st.session_state.graph
    docs            = st.session_state.docs

    total_ports = sum(len(m.ports) for m in modules_by_name.values())
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Modules Documented", len(docs))
    m2.metric("Total Ports",        total_ports)
    m3.metric("Top-level Modules",  len(graph.top_level_modules()))
    m4.metric("Leaf Modules",       len(graph.leaf_modules()))

    # Hierarchy tree
    st.markdown("### Module Hierarchy")
    st.code(graph.ascii_tree(), language=None)

    # Download buttons
    st.markdown("### Download")
    dl1, dl2 = st.columns(2)

    # HTML report download
    if st.session_state.html_path:
        html_bytes = Path(st.session_state.html_path).read_bytes()
        dl1.download_button(
            label="⬇ Download HTML Report",
            data=html_bytes,
            file_name="rtl_documentation.html",
            mime="text/html",
            use_container_width=True,
            type="primary",
        )

    # Combined Markdown download
    combined_md = ""
    for name, doc in docs.items():
        combined_md += f"# {name}\n\n{doc}\n\n---\n\n"
    dl2.download_button(
        label="⬇ Download Markdown",
        data=combined_md.encode("utf-8"),
        file_name="rtl_documentation.md",
        mime="text/markdown",
        use_container_width=True,
    )

    # Per-module expandable docs
    st.markdown("### Generated Documentation")
    for name, doc in docs.items():
        mod = modules_by_name.get(name)
        badges = []
        if mod and mod.fsm_states:    badges.append("🔄 FSM")
        if mod and mod.instantiations: badges.append("🔗 Hierarchical")
        if mod and mod.parameters:    badges.append("⚙ Parametric")
        badge_str = "  ·  ".join(badges) if badges else "Leaf Module"

        with st.expander(f"**`{name}`**  —  {badge_str}", expanded=False):
            # Port quick-view
            if mod and mod.ports:
                pcols = st.columns(min(4, len(mod.ports)))
                for i, port in enumerate(mod.ports[:8]):
                    with pcols[i % 4]:
                        color = "🔵" if port.direction == "input" else "🔴"
                        st.markdown(
                            f"{color} **`{port.name}`**  \n"
                            f"<small>{port.direction} · {port.width}</small>",
                            unsafe_allow_html=True,
                        )
                if mod and len(mod.ports) > 8:
                    st.caption(f"…and {len(mod.ports) - 8} more ports")
                st.divider()

            # Summary pill
            summary = st.session_state.summaries.get(name, "")
            if summary:
                st.info(f"**Summary:** {summary}")

            # Full doc
            st.markdown(doc)

    # Q&A section
    st.divider()
    st.markdown("### 💬 Ask a Question About the Design")
    st.caption("Powered by RAG — answers are grounded in your RTL context")

    question = st.text_input(
        "Your question",
        placeholder="e.g. What is the handshake protocol between the ALU and FIFO?",
        key="qa_input",
    )
    if st.button("Ask", disabled=not question):
        with st.spinner("Searching design context…"):
            try:
                # Re-create embedder pointing at the same chroma store
                # (stored path in session would be needed for persistence;
                #  here we fall back to re-indexing if store is gone)
                from rag.embedder import RTLEmbedder
                from rag.generator import DocGenerator
                import tempfile

                tmp_chroma = tempfile.mkdtemp(prefix="rtl_qa_")
                embedder = RTLEmbedder(persist_dir=tmp_chroma)
                embedder.index_modules(
                    list(modules_by_name.values()),
                    st.session_state.summaries,
                )
                generator = DocGenerator(embedder=embedder, model=groq_model)
                answer = generator.answer_question(question)
                st.markdown("**Answer:**")
                st.markdown(answer)
                shutil.rmtree(tmp_chroma, ignore_errors=True)
            except Exception as e:
                st.error(f"Q&A failed: {e}")