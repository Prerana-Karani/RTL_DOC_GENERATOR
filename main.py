"""
main.py

RTL Documentation Generator — Full Pipeline Entry Point

Usage:
    # Document RTL files in ./rtl/ directory
    python main.py

    # Document a specific directory
    python main.py --rtl path/to/rtl/

    # Interactive Q&A mode (after first run)
    python main.py --qa

    # Skip LLM calls, output parse/hierarchy info only
    python main.py --parse-only

    # Specify project name for the report header
    python main.py --project "My SoC"
"""

from __future__ import annotations

import os
import sys
import argparse
import time
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _print_banner():
    print("""
╔══════════════════════════════════════════════════════════════════╗
║          RTL Documentation Generator  v1.0                      ║
║          RAG + Bottom-Up LLM Summarisation Pipeline             ║
╚══════════════════════════════════════════════════════════════════╝
""")


def _step(n: int, label: str):
    print(f"\n{'─'*60}")
    print(f"  Step {n}: {label}")
    print(f"{'─'*60}")


def _progress(current: int, total: int, name: str):
    bar_len = 30
    filled  = int(bar_len * current / total)
    bar     = "█" * filled + "░" * (bar_len - filled)
    print(f"  [{bar}] {current}/{total}  {name}", end="\r", flush=True)
    if current == total:
        print()


# ──────────────────────────────────────────────────────────────────────────────
# Pipeline stages
# ──────────────────────────────────────────────────────────────────────────────

def stage_parse(rtl_dir: str):
    """Stage 1 & 2: Parse RTL files and build hierarchy graph."""
    from parser.rtl_parser import RTLParser
    from graph.hierarchy import HierarchyGraph

    parser  = RTLParser()
    modules = parser.parse_directory(rtl_dir)

    if not modules:
        print(f"  ✗  No .v / .sv files found in '{rtl_dir}'")
        sys.exit(1)

    print(f"  ✓  Parsed {len(modules)} module(s):")
    for m in modules:
        print(f"       {m.module_name:30} ({m.parse_method})  "
              f"ports={len(m.ports)}  insts={len(m.instantiations)}")

    graph   = HierarchyGraph(modules)
    summary = graph.summary()
    print(f"\n  Hierarchy summary:")
    print(f"    Top-level modules : {summary['top_level']}")
    print(f"    Leaf modules      : {summary['leaf_modules']}")
    print(f"\n{graph.ascii_tree()}")

    modules_by_name = {m.module_name: m for m in modules}
    return modules_by_name, graph


def stage_summarise(modules_by_name, graph):
    """Stage 3: Bottom-up LLM summarisation."""
    from summariser.bottom_up import BottomUpSummariser

    summariser = BottomUpSummariser(progress_callback=_progress)
    summaries  = summariser.run(modules_by_name, graph)

    print(f"\n  ✓  Summarised {len(summaries)} module(s)")
    return summaries


def stage_embed(modules_by_name, summaries, persist_dir: str):
    """Stage 4: Embed into ChromaDB."""
    from rag.embedder import RTLEmbedder

    embedder = RTLEmbedder(persist_dir=persist_dir)
    embedder.index_modules(list(modules_by_name.values()), summaries)
    print(f"  ✓  ChromaDB contains {embedder.collection_size()} chunks")
    return embedder


def stage_generate(modules_by_name, graph, summaries, embedder):
    """Stage 5: RAG-based full documentation generation."""
    from rag.generator import DocGenerator

    generator = DocGenerator(embedder=embedder, progress_callback=_progress)
    docs = generator.generate_all(
        modules_by_name=modules_by_name,
        bottom_up_order=graph.bottom_up_order(),
        summaries=summaries,
        graph=graph,
    )
    print(f"\n  ✓  Generated docs for {len(docs)} module(s)")
    return docs, generator


def stage_write(project_name, modules_by_name, docs, graph, summaries, output_dir: str):
    """Stage 6: Write Markdown + HTML output."""
    from output.writer import DocWriter

    writer   = DocWriter(output_dir=output_dir)
    md_paths = writer.write_markdown(docs)
    html_path = writer.write_html_report(
        project_name    = project_name,
        modules_by_name = modules_by_name,
        documentation   = docs,
        graph           = graph,
        summaries       = summaries,
    )

    print(f"  ✓  Markdown files : {len(md_paths)}")
    print(f"  ✓  HTML report    : {html_path}")
    return html_path


def qa_mode(persist_dir: str):
    """Interactive Q&A over the design knowledge base."""
    from rag.embedder import RTLEmbedder
    from rag.generator import DocGenerator

    print("\n  Loading knowledge base…")
    embedder  = RTLEmbedder(persist_dir=persist_dir)
    generator = DocGenerator(embedder=embedder)

    print("  Q&A ready. Type your question (or 'exit' to quit).\n")
    while True:
        try:
            question = input("  > ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if question.lower() in ("exit", "quit", "q"):
            break
        if not question:
            continue
        print()
        answer = generator.answer_question(question)
        print(f"  {answer}\n")


# ──────────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────────

def main():
    _print_banner()

    parser = argparse.ArgumentParser(
        description="RTL Documentation Generator — RAG + LLM pipeline"
    )
    parser.add_argument("--rtl",        default="./rtl",         help="RTL source directory")
    parser.add_argument("--project",    default="RTL Design",    help="Project name for report")
    parser.add_argument("--output",     default="./docs",        help="Output directory")
    parser.add_argument("--chroma",     default="./chroma_store",help="ChromaDB persist dir")
    parser.add_argument("--parse-only", action="store_true",     help="Parse + hierarchy only, no LLM")
    parser.add_argument("--qa",         action="store_true",     help="Interactive Q&A mode")
    args = parser.parse_args()

    # ── Q&A mode ──────────────────────────────────────────────────────────────
    if args.qa:
        _step(0, "Q&A Mode — querying existing knowledge base")
        qa_mode(args.chroma)
        return

    t0 = time.time()

    # ── Stage 1 & 2: Parse + Hierarchy ────────────────────────────────────────
    _step(1, "Parsing RTL files + building hierarchy graph")
    modules_by_name, graph = stage_parse(args.rtl)

    if args.parse_only:
        print("\n  --parse-only flag set. Stopping after parse/hierarchy.")
        return

    # ── Stage 3: Bottom-up summarisation ──────────────────────────────────────
    _step(2, "Bottom-up LLM summarisation (Groq)")
    summaries = stage_summarise(modules_by_name, graph)

    # ── Stage 4: Embed into ChromaDB ──────────────────────────────────────────
    _step(3, "Embedding into ChromaDB vector store")
    embedder = stage_embed(modules_by_name, summaries, args.chroma)

    # ── Stage 5: RAG + doc generation ─────────────────────────────────────────
    _step(4, "RAG-based documentation generation (Groq)")
    docs, generator = stage_generate(modules_by_name, graph, summaries, embedder)

    # ── Stage 6: Write output ─────────────────────────────────────────────────
    _step(5, "Writing Markdown + HTML output")
    html_path = stage_write(
        project_name    = args.project,
        modules_by_name = modules_by_name,
        docs            = docs,
        graph           = graph,
        summaries       = summaries,
        output_dir      = args.output,
    )

    elapsed = time.time() - t0
    print(f"""
{'═'*60}
  ✅  Documentation complete in {elapsed:.1f}s
  📄  Open: {html_path}
{'═'*60}
""")


if __name__ == "__main__":
    main()
