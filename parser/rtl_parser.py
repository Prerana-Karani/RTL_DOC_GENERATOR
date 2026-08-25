"""
parser/rtl_parser.py

Parses Verilog / SystemVerilog files using PyVerilog (AST) with a
regex-based fallback for constructs PyVerilog can't handle.

Returns a list of ModuleInfo dataclasses — one per module found.
"""

from __future__ import annotations

import re
import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Optional


# ──────────────────────────────────────────────────────────────────────────────
# Data models
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class Port:
    name: str
    direction: str          # "input" | "output" | "inout"
    width: str              # e.g. "[31:0]" or "1-bit"
    data_type: str          # "wire" | "reg" | "logic"


@dataclass
class Parameter:
    name: str
    value: str


@dataclass
class Instantiation:
    module_name: str
    instance_name: str
    port_connections: Dict[str, str] = field(default_factory=dict)


@dataclass
class FSMState:
    name: str
    transitions: List[str] = field(default_factory=list)


@dataclass
class ModuleInfo:
    file_path: str
    module_name: str
    parameters: List[Parameter]       = field(default_factory=list)
    ports: List[Port]                 = field(default_factory=list)
    instantiations: List[Instantiation] = field(default_factory=list)
    fsm_states: List[FSMState]        = field(default_factory=list)
    localparams: Dict[str, str]       = field(default_factory=dict)
    always_blocks: int                = 0
    assign_count: int                 = 0
    raw_code: str                     = ""
    parse_method: str                 = "regex"

    # Convenience helpers
    def port_names(self) -> List[str]:
        return [p.name for p in self.ports]

    def child_module_names(self) -> List[str]:
        return [i.module_name for i in self.instantiations]


# ──────────────────────────────────────────────────────────────────────────────
# Parser class
# ──────────────────────────────────────────────────────────────────────────────

_VERILOG_KEYWORDS = {
    "module", "endmodule", "input", "output", "inout", "wire", "reg", "logic",
    "always", "assign", "begin", "end", "if", "else", "case", "casez", "casex",
    "endcase", "for", "while", "posedge", "negedge", "parameter", "localparam",
    "integer", "genvar", "generate", "endgenerate", "function", "endfunction",
    "task", "endtask", "initial", "fork", "join", "repeat", "forever",
}


class RTLParser:
    """Parse RTL source files and return structured module information."""

    # ── Public API ────────────────────────────────────────────────────────────

    def parse_file(self, file_path: str) -> List[ModuleInfo]:
        """Parse a single .v / .sv file.  Returns one ModuleInfo per module."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"RTL file not found: {file_path}")

        code = path.read_text(encoding="utf-8", errors="replace")

        result = self._try_pyverilog(file_path, code)
        if result:
            return result

        return self._regex_parse(file_path, code)

    def parse_directory(self, dir_path: str) -> List[ModuleInfo]:
        """Recursively parse all .v / .sv files under dir_path."""
        results: List[ModuleInfo] = []
        for ext in ("*.v", "*.sv"):
            for fp in sorted(Path(dir_path).rglob(ext)):
                try:
                    results.extend(self.parse_file(str(fp)))
                except Exception as exc:
                    print(f"  [warn] Could not parse {fp}: {exc}")
        return results

    # ── PyVerilog path ────────────────────────────────────────────────────────

    def _try_pyverilog(self, file_path: str, code: str) -> Optional[List[ModuleInfo]]:
        try:
            from pyverilog.vparser.parser import VerilogParser
            import pyverilog.vparser.ast as ast

            parser = VerilogParser()
            tree, _ = parser.parse([file_path],
                                   preprocess_include=[],
                                   preprocess_define=[])

            modules: List[ModuleInfo] = []
            self._walk_ast(tree, ast, modules, file_path, code)
            return modules if modules else None

        except Exception:
            return None

    def _walk_ast(self, node, ast, results, file_path, code):
        if isinstance(node, ast.ModuleDef):
            results.append(self._extract_pyverilog_module(node, ast, file_path, code))
            return  # don't recurse into nested (shouldn't exist in Verilog)
        for child in node.children():
            self._walk_ast(child, ast, results, file_path, code)

    def _extract_pyverilog_module(self, node, ast, file_path: str, code: str) -> ModuleInfo:
        info = ModuleInfo(
            file_path=file_path,
            module_name=node.name,
            raw_code=code,
            parse_method="pyverilog",
        )

        # Ports from portlist
        if node.portlist:
            for p in node.portlist.ports:
                self._pv_extract_port(p, ast, info)

        # Items
        if node.items:
            for item in node.items:
                self._pv_process_item(item, ast, info)

        info.fsm_states = self._detect_fsm(code)
        return info

    def _pv_extract_port(self, node, ast, info: ModuleInfo):
        dir_map = {ast.Input: "input", ast.Output: "output", ast.Inout: "inout"}
        for cls, direction in dir_map.items():
            if isinstance(node, cls):
                width = self._pv_width(node)
                dtype = "reg" if direction == "output" else "wire"
                info.ports.append(Port(
                    name=str(node.name),
                    direction=direction,
                    width=width,
                    data_type=dtype,
                ))

    def _pv_process_item(self, item, ast, info: ModuleInfo):
        if isinstance(item, (ast.Input, ast.Output, ast.Inout)):
            self._pv_extract_port(item, ast, info)

        elif isinstance(item, ast.Decl):
            for sub in item.list:
                if isinstance(sub, ast.Parameter):
                    info.parameters.append(Parameter(
                        name=str(sub.name),
                        value=str(sub.value) if sub.value else "",
                    ))
                elif isinstance(sub, ast.Localparam):
                    info.localparams[str(sub.name)] = str(sub.value) if sub.value else ""

        elif isinstance(item, ast.InstanceList):
            for inst in item.instances:
                conns = {}
                if inst.portlist:
                    for conn in inst.portlist:
                        conns[str(conn.portname)] = str(conn.argname) if conn.argname else ""
                info.instantiations.append(Instantiation(
                    module_name=str(item.module),
                    instance_name=str(inst.name),
                    port_connections=conns,
                ))

        elif isinstance(item, ast.Always):
            info.always_blocks += 1

        elif isinstance(item, ast.Assign):
            info.assign_count += 1

    @staticmethod
    def _pv_width(node) -> str:
        try:
            w = node.width
            if w:
                return f"[{w.msb}:{w.lsb}]"
        except Exception:
            pass
        return "1-bit"

    # ── Regex fallback path ───────────────────────────────────────────────────

    def _regex_parse(self, file_path: str, code: str) -> List[ModuleInfo]:
        """Extract module(s) using regex — handles most synthesisable RTL."""
        # Strip comments
        clean = re.sub(r"/\*.*?\*/", " ", code, flags=re.DOTALL)
        clean = re.sub(r"//[^\n]*", " ", clean)

        modules: List[ModuleInfo] = []

        # Split on 'module ... endmodule' boundaries
        for mod_match in re.finditer(
            r"\bmodule\b\s+(\w+)(.*?)\bendmodule\b",
            clean,
            re.DOTALL,
        ):
            mod_name = mod_match.group(1)
            body = mod_match.group(0)

            info = ModuleInfo(
                file_path=file_path,
                module_name=mod_name,
                raw_code=code,
                parse_method="regex",
            )

            self._regex_extract_params(body, info)
            self._regex_extract_ports(body, info)
            self._regex_extract_localparams(body, info)
            self._regex_extract_instances(body, info)
            info.always_blocks = len(re.findall(r"\balways\b", body))
            info.assign_count  = len(re.findall(r"\bassign\b",  body))
            info.fsm_states    = self._detect_fsm(body)

            modules.append(info)

        return modules

    @staticmethod
    def _regex_extract_params(body: str, info: ModuleInfo):
        for m in re.finditer(
            r"\bparameter\b\s+(?:\w+\s+)?(\w+)\s*=\s*([^,;\n)]+)", body
        ):
            info.parameters.append(Parameter(
                name=m.group(1),
                value=m.group(2).strip(),
            ))

    @staticmethod
    def _regex_extract_localparams(body: str, info: ModuleInfo):
        for m in re.finditer(r"\blocalparam\b\s+(?:\w+\s+)?(\w+)\s*=\s*([^;]+)", body):
            info.localparams[m.group(1)] = m.group(2).strip()

    @staticmethod
    def _regex_extract_ports(body: str, info: ModuleInfo):
        seen = set()
        pattern = re.compile(
            r"\b(input|output|inout)\s+(?:(wire|reg|logic)\s+)?(\[\s*\S+\s*:\s*\S+\s*\]\s*)?(\w+)"
        )
        for m in pattern.finditer(body):
            direction, dtype, width, name = m.groups()
            if name in _VERILOG_KEYWORDS or name in seen:
                continue
            seen.add(name)
            info.ports.append(Port(
                name=name,
                direction=direction,
                width=(width.strip() if width else "1-bit"),
                data_type=(dtype or "wire"),
            ))

    @staticmethod
    def _regex_extract_instances(body: str, info: ModuleInfo):
        seen = set()
        # module_name  [#(...)]  instance_name  (...)
        pattern = re.compile(
            r"\b(\w+)\s+(?:#\s*\([^)]*\)\s*)?(\w+)\s*\(", re.DOTALL
        )
        for m in pattern.finditer(body):
            mod_name, inst_name = m.group(1), m.group(2)
            if mod_name in _VERILOG_KEYWORDS or inst_name in _VERILOG_KEYWORDS:
                continue
            key = (mod_name, inst_name)
            if key in seen:
                continue
            seen.add(key)
            info.instantiations.append(Instantiation(
                module_name=mod_name,
                instance_name=inst_name,
            ))

    @staticmethod
    def _detect_fsm(code: str) -> List[FSMState]:
        """Heuristic FSM state detection via localparam names + case blocks."""
        state_names: set[str] = set()

        # Localparams with 'state' in name or value looks like encoding
        for m in re.finditer(
            r"\b(?:localparam|parameter)\b[^=]*(\w*[Ss][Tt][Aa][Tt][Ee]\w*)\s*=",
            code,
        ):
            state_names.add(m.group(1))

        # case(state) blocks
        case_blocks = re.findall(
            r"case\s*\(\s*\w*[Ss]tate\w*\s*\)(.*?)endcase", code, re.DOTALL
        )
        for block in case_blocks:
            for m in re.finditer(r"(\b[A-Z_][A-Z0-9_]+\b)\s*:", block):
                name = m.group(1)
                if name != "DEFAULT":
                    state_names.add(name)

        states: List[FSMState] = []
        for name in sorted(state_names):
            transitions: List[str] = []
            for block in case_blocks:
                pattern = re.compile(
                    rf"{re.escape(name)}\s*:(.*?)(?=[A-Z_][A-Z0-9_]*\s*:|endcase)",
                    re.DOTALL,
                )
                for tm in pattern.finditer(block):
                    nxt = re.findall(
                        r"(?:next_state|n?state)\s*<=?\s*(\w+)", tm.group(1)
                    )
                    transitions.extend(nxt)
            states.append(FSMState(name=name, transitions=list(set(transitions))))

        return states
