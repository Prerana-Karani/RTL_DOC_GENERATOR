"""
graph/hierarchy.py

Builds a directed acyclic graph of RTL module dependencies using NetworkX.
Provides topological sort (bottom-up order: leaves first, top-level last)
for the LLM summarisation pass.
"""

from __future__ import annotations

from typing import List, Dict, Set, Tuple
import networkx as nx

from parser.rtl_parser import ModuleInfo


class HierarchyGraph:
    """
    Nodes  = module names
    Edges  = parent → child  (parent instantiates child)
    """

    def __init__(self, modules: List[ModuleInfo]):
        self.modules: Dict[str, ModuleInfo] = {m.module_name: m for m in modules}
        self.graph: nx.DiGraph = nx.DiGraph()
        self._build()

    # ── Construction ──────────────────────────────────────────────────────────

    def _build(self):
        # Add all known modules as nodes
        for name in self.modules:
            self.graph.add_node(name)

        # Add edges for instantiations that resolve to a known module
        for name, mod in self.modules.items():
            for inst in mod.instantiations:
                child = inst.module_name
                if child in self.modules and child != name:
                    self.graph.add_edge(name, child)

    # ── Queries ───────────────────────────────────────────────────────────────

    def bottom_up_order(self) -> List[str]:
        """
        Returns module names in bottom-up topological order.
        Leaf modules (no children) come first; top-level comes last.
        Handles cycles gracefully by breaking them with a warning.
        """
        g = self.graph.copy()

        # Break any cycles so we can still produce an order
        while True:
            try:
                cycle = nx.find_cycle(g, orientation="original")
                # Remove the last edge in the cycle
                u, v, _ = cycle[-1]
                print(f"  [warn] Cycle detected: {u} → {v}. Breaking edge.")
                g.remove_edge(u, v)
            except nx.NetworkXNoCycle:
                break

        # Reverse topological order gives us leaves-first
        topo = list(nx.topological_sort(g))
        return list(reversed(topo))

    def top_level_modules(self) -> List[str]:
        """Modules with no parents (in-degree == 0)."""
        return [n for n in self.graph.nodes if self.graph.in_degree(n) == 0]

    def leaf_modules(self) -> List[str]:
        """Modules with no children (out-degree == 0)."""
        return [n for n in self.graph.nodes if self.graph.out_degree(n) == 0]

    def children_of(self, module_name: str) -> List[str]:
        return list(self.graph.successors(module_name))

    def parents_of(self, module_name: str) -> List[str]:
        return list(self.graph.predecessors(module_name))

    # ── Reporting ─────────────────────────────────────────────────────────────

    def summary(self) -> Dict:
        return {
            "total_modules":  len(self.modules),
            "total_edges":    self.graph.number_of_edges(),
            "top_level":      self.top_level_modules(),
            "leaf_modules":   self.leaf_modules(),
            "hierarchy": {
                name: self.children_of(name)
                for name in self.graph.nodes
                if self.children_of(name)
            },
        }

    def ascii_tree(self, root: str = None, indent: int = 0) -> str:
        """Render an ASCII hierarchy tree for display."""
        lines: List[str] = []
        visited: Set[str] = set()

        def _render(node: str, depth: int):
            if node in visited:
                lines.append("  " * depth + f"↩ {node}  [already shown]")
                return
            visited.add(node)
            prefix = "  " * depth + ("└─ " if depth > 0 else "")
            lines.append(prefix + node)
            for child in sorted(self.children_of(node)):
                _render(child, depth + 1)

        roots = [root] if root else self.top_level_modules()
        if not roots:
            roots = sorted(self.modules.keys())

        for r in roots:
            _render(r, 0)

        return "\n".join(lines)
