"""
rag/generator.py

Full documentation generator using RAG + Groq LLM.
For each module, retrieves relevant context from ChromaDB,
then generates structured Markdown documentation.

Also exposes an interactive Q&A method for natural-language design queries.
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional, Callable

from groq import Groq

from parser.rtl_parser import ModuleInfo
from rag.embedder import RTLEmbedder


# ──────────────────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────────────────

DEFAULT_MODEL   = "llama-3.3-70b-versatile"
DOC_MAX_TOKENS  = 2048
QA_MAX_TOKENS   = 1024
TEMPERATURE     = 0.2
CODE_CHAR_LIMIT = 3000


# ──────────────────────────────────────────────────────────────────────────────
# Prompt builders
# ──────────────────────────────────────────────────────────────────────────────

def _doc_prompt(
    mod: ModuleInfo,
    child_summaries: Dict[str, str],
    rag_context: str,
    bottom_up_summary: str,
) -> str:
    ports_table = "| Port | Direction | Width | Type |\n|------|-----------|-------|------|\n"
    for p in mod.ports:
        ports_table += f"| `{p.name}` | {p.direction} | {p.width} | {p.data_type} |\n"

    params_block = "\n".join(
        f"- `{p.name}` = `{p.value}`" for p in mod.parameters
    ) or "_(none)_"

    fsm_block = ""
    if mod.fsm_states:
        fsm_block = "### Detected FSM States\n"
        for s in mod.fsm_states:
            trans = ", ".join(s.transitions) if s.transitions else "terminal"
            fsm_block += f"- **{s.name}** → `{trans}`\n"

    child_block = ""
    if child_summaries:
        child_block = "### Child Module Summaries\n"
        for cname, csummary in child_summaries.items():
            child_block += f"\n**{cname}**: {csummary}\n"

    rag_section = ""
    if rag_context.strip() and "No relevant" not in rag_context:
        rag_section = f"### Retrieved Design Context\n```\n{rag_context[:2000]}\n```"

    pre_summary = f"\n### Pre-computed Summary\n{bottom_up_summary}\n" if bottom_up_summary else ""

    code_snippet = mod.raw_code[:CODE_CHAR_LIMIT]
    if len(mod.raw_code) > CODE_CHAR_LIMIT:
        code_snippet += "\n... [truncated]"

    return f"""You are a senior RTL/VLSI design engineer writing professional reference documentation.

Generate complete Markdown documentation for the Verilog module below.
Use the retrieved context and child summaries to make the docs accurate and cross-module-aware.

---

## Module: `{mod.module_name}`
**File:** `{mod.file_path}`
**Parse method:** {mod.parse_method}
**Always blocks:** {mod.always_blocks}  |  **Assign statements:** {mod.assign_count}

### Parameters
{params_block}

### Port List
{ports_table}
{fsm_block}
{child_block}
{pre_summary}
{rag_section}

### RTL Source
```verilog
{code_snippet}
```

---

Generate documentation with EXACTLY these sections (include all, omit none):

## Overview
One clear paragraph: what this module does, its role in the design.

## Port Description
Markdown table: Port | Direction | Width | Type | Description
Fill in accurate, inferred descriptions for every port.

## Functional Behaviour
2–5 paragraphs: clock/reset strategy, data path, control logic, timing.

## Parameters & Configuration
Explain each parameter and its effect on the design.

## FSM / State Machine
Describe states and transitions. _(Omit section entirely if no FSM detected.)_

## Sub-module Integration
Explain child modules and signal handshakes. _(Omit if no instantiations.)_

## Design Notes
Timing assumptions, synthesis guidance, known limitations, usage examples.

Be precise, technical, and concise. No padding or generic filler.
"""


def _qa_prompt(question: str, context: str) -> str:
    return f"""You are a hardware design expert with deep RTL/Verilog knowledge.

Answer the question below using ONLY the retrieved RTL design context.
If the context doesn't contain enough information, say so explicitly.

## Retrieved Context
{context}

## Question
{question}

Provide a precise, technical answer grounded in the context above.
Reference specific module names, signal names, and port connections where relevant.
"""


# ──────────────────────────────────────────────────────────────────────────────
# Generator
# ──────────────────────────────────────────────────────────────────────────────

class DocGenerator:
    """
    Generates per-module Markdown documentation via RAG + Groq LLM.
    Also supports natural-language Q&A over the design.
    """

    def __init__(
        self,
        embedder: RTLEmbedder,
        model: str = DEFAULT_MODEL,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
    ):
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise EnvironmentError(
                "GROQ_API_KEY not set. Add it to your .env file.\n"
                "Get a free key at https://console.groq.com"
            )
        self.client    = Groq(api_key=api_key)
        self.embedder  = embedder
        self.model     = model
        self.progress_callback = progress_callback
        self.docs: Dict[str, str] = {}   # module_name → markdown

    # ── Public API ────────────────────────────────────────────────────────────

    def generate_all(
        self,
        modules_by_name: Dict[str, ModuleInfo],
        bottom_up_order: List[str],
        summaries: Dict[str, str],
        graph,
    ) -> Dict[str, str]:
        """
        Generate full documentation for every module in bottom-up order.
        Returns dict  module_name → markdown string.
        """
        total = len(bottom_up_order)
        for idx, name in enumerate(bottom_up_order, start=1):
            if name not in modules_by_name:
                continue

            if self.progress_callback:
                self.progress_callback(idx, total, name)

            mod = modules_by_name[name]

            # Child summaries (already in summaries dict)
            child_summaries = {
                child: summaries[child]
                for child in graph.children_of(name)
                if child in summaries
            }

            # RAG retrieval
            query      = f"documentation ports behaviour FSM hierarchy {name}"
            rag_ctx    = self.embedder.query(query, top_k=5)
            pre_summary = summaries.get(name, "")

            prompt = _doc_prompt(mod, child_summaries, rag_ctx, pre_summary)
            self.docs[name] = self._call_llm(prompt, DOC_MAX_TOKENS)

        return self.docs

    def answer_question(self, question: str, top_k: int = 6) -> str:
        """Answer a natural-language question about the design using RAG."""
        context = self.embedder.query(question, top_k=top_k)
        prompt  = _qa_prompt(question, context)
        return self._call_llm(prompt, QA_MAX_TOKENS)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _call_llm(self, prompt: str, max_tokens: int) -> str:
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
                temperature=TEMPERATURE,
            )
            return resp.choices[0].message.content.strip()
        except Exception as exc:
            return f"[Documentation generation failed: {exc}]"
