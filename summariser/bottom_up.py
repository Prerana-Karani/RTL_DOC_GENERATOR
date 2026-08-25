"""
summariser/bottom_up.py

Implements the bottom-up summarisation strategy from RTLExplain (IBM / DAC 2025).

Processing order (from HierarchyGraph.bottom_up_order()):
  1. Leaf modules are summarised first with only their own code + ports.
  2. Their summaries are injected as context into parent module prompts.
  3. Parents are summarised with full child-context awareness.

This avoids LLM context-window overflow while preserving cross-module
semantic accuracy.
"""

from __future__ import annotations

import os
from typing import Dict, List, Callable, Optional

from groq import Groq

from parser.rtl_parser import ModuleInfo
from graph.hierarchy import HierarchyGraph


# ──────────────────────────────────────────────────────────────────────────────
# Defaults
# ──────────────────────────────────────────────────────────────────────────────

DEFAULT_MODEL  = "llama-3.3-70b-versatile"
MAX_TOKENS     = 1024
TEMPERATURE    = 0.2
CODE_CHAR_LIMIT = 3500   # chars of raw RTL to include in prompt


# ──────────────────────────────────────────────────────────────────────────────
# Prompt builder
# ──────────────────────────────────────────────────────────────────────────────

def _build_summary_prompt(
    mod: ModuleInfo,
    child_summaries: Dict[str, str],
) -> str:
    """
    Produces a focused prompt asking the LLM for a concise module summary.
    Child summaries are injected verbatim so the LLM understands sub-module intent.
    """

    ports_block = "\n".join(
        f"  {p.direction:8} {p.width:12} {p.name}  ({p.data_type})"
        for p in mod.ports
    ) or "  (none extracted)"

    params_block = "\n".join(
        f"  {p.name} = {p.value}" for p in mod.parameters
    ) or "  (none)"

    fsm_block = ""
    if mod.fsm_states:
        fsm_block = "Detected FSM states:\n" + "\n".join(
            f"  {s.name}  →  {', '.join(s.transitions) or 'terminal'}"
            for s in mod.fsm_states
        )

    child_block = ""
    if child_summaries:
        child_block = "\n## Child module summaries (use for context)\n"
        for cname, csummary in child_summaries.items():
            child_block += f"\n### {cname}\n{csummary}\n"

    code_snippet = mod.raw_code[:CODE_CHAR_LIMIT]
    if len(mod.raw_code) > CODE_CHAR_LIMIT:
        code_snippet += "\n... [truncated]"

    return f"""You are a senior RTL design engineer.

Write a concise technical summary (3-6 sentences) for the Verilog module below.
Cover: what it does, key signals/ports, clocking/reset strategy, and any notable behaviour
(FSM, pipeline stages, handshake protocol). Be precise. No padding.

## Module: {mod.module_name}

### Parameters
{params_block}

### Ports
{ports_block}

### Stats
Always blocks : {mod.always_blocks}
Assign stmts  : {mod.assign_count}
Instantiations: {len(mod.instantiations)}
{fsm_block}
{child_block}

### RTL Source
```verilog
{code_snippet}
```

Reply with ONLY the summary paragraph(s). No headings, no bullet points.
"""


# ──────────────────────────────────────────────────────────────────────────────
# Summariser
# ──────────────────────────────────────────────────────────────────────────────

class BottomUpSummariser:
    """
    Orchestrates bottom-up LLM summarisation of an RTL design hierarchy.

    Usage:
        summariser = BottomUpSummariser()
        summaries  = summariser.run(modules_by_name, hierarchy_graph)
    """

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
    ):
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise EnvironmentError(
                "GROQ_API_KEY not set. Add it to your .env file.\n"
                "Get a free key at https://console.groq.com"
            )
        self.client = Groq(api_key=api_key)
        self.model  = model
        self.progress_callback = progress_callback
        self.summaries: Dict[str, str] = {}   # module_name → summary text

    # ── Public API ────────────────────────────────────────────────────────────

    def run(
        self,
        modules_by_name: Dict[str, ModuleInfo],
        graph: HierarchyGraph,
    ) -> Dict[str, str]:
        """
        Process every module in bottom-up topological order.
        Returns dict of  module_name → summary string.
        """
        order = graph.bottom_up_order()
        total = len(order)

        for idx, name in enumerate(order, start=1):
            if name not in modules_by_name:
                continue

            if self.progress_callback:
                self.progress_callback(idx, total, name)

            mod = modules_by_name[name]

            # Collect already-generated summaries for direct children
            child_summaries: Dict[str, str] = {}
            for child_name in graph.children_of(name):
                if child_name in self.summaries:
                    child_summaries[child_name] = self.summaries[child_name]

            self.summaries[name] = self._summarise(mod, child_summaries)

        return self.summaries

    def get_summary(self, module_name: str) -> str:
        return self.summaries.get(module_name, "")

    # ── Internal ──────────────────────────────────────────────────────────────

    def _summarise(
        self,
        mod: ModuleInfo,
        child_summaries: Dict[str, str],
    ) -> str:
        prompt = _build_summary_prompt(mod, child_summaries)
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=MAX_TOKENS,
                temperature=TEMPERATURE,
            )
            return response.choices[0].message.content.strip()
        except Exception as exc:
            return f"[Summary generation failed: {exc}]"
