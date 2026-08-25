"""
tests/test_pipeline.py

Unit tests for the RTL Documentation Generator pipeline.
Run with:  pytest tests/ -v
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

# Allow imports from project root
sys.path.insert(0, str(Path(__file__).parent.parent))

from parser.rtl_parser import RTLParser, ModuleInfo, Port
from graph.hierarchy import HierarchyGraph


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────

SIMPLE_MODULE = """\
module adder #(
    parameter WIDTH = 8
)(
    input  wire [WIDTH-1:0] a,
    input  wire [WIDTH-1:0] b,
    output wire [WIDTH-1:0] sum,
    output wire             carry_out
);
    assign {carry_out, sum} = a + b;
endmodule
"""

FSM_MODULE = """\
module traffic_light (
    input  wire clk,
    input  wire rst_n,
    output reg [1:0] light
);
    localparam RED    = 2'b00;
    localparam GREEN  = 2'b01;
    localparam YELLOW = 2'b10;

    reg [1:0] state, next_state;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) state <= RED;
        else        state <= next_state;
    end

    always @(*) begin
        case (state)
            RED:    next_state = GREEN;
            GREEN:  next_state = YELLOW;
            YELLOW: next_state = RED;
            default: next_state = RED;
        endcase
    end

    assign light = state;
endmodule
"""

HIER_TOP = """\
module top (
    input  wire clk,
    input  wire rst_n,
    input  wire [7:0] data_in,
    output wire [7:0] data_out
);
    wire [7:0] mid;

    adder u_adder (
        .a(data_in),
        .b(8'h01),
        .sum(mid)
    );

    adder u_adder2 (
        .a(mid),
        .b(8'hFF),
        .sum(data_out)
    );
endmodule
"""


@pytest.fixture
def parser():
    return RTLParser()


@pytest.fixture
def tmp_rtl(tmp_path):
    """Write sample RTL files and return directory."""
    (tmp_path / "adder.v").write_text(SIMPLE_MODULE)
    (tmp_path / "traffic_light.v").write_text(FSM_MODULE)
    (tmp_path / "top.v").write_text(HIER_TOP)
    return tmp_path


# ──────────────────────────────────────────────────────────────────────────────
# Parser tests
# ──────────────────────────────────────────────────────────────────────────────

class TestRTLParser:

    def test_parse_simple_module(self, parser, tmp_path):
        f = tmp_path / "adder.v"
        f.write_text(SIMPLE_MODULE)
        modules = parser.parse_file(str(f))
        assert len(modules) == 1
        mod = modules[0]
        assert mod.module_name == "adder"

    def test_port_extraction(self, parser, tmp_path):
        f = tmp_path / "adder.v"
        f.write_text(SIMPLE_MODULE)
        mod = parser.parse_file(str(f))[0]
        port_names = [p.name for p in mod.ports]
        assert "a" in port_names
        assert "b" in port_names
        assert "sum" in port_names
        assert "carry_out" in port_names

    def test_port_directions(self, parser, tmp_path):
        f = tmp_path / "adder.v"
        f.write_text(SIMPLE_MODULE)
        mod = parser.parse_file(str(f))[0]
        dirs = {p.name: p.direction for p in mod.ports}
        assert dirs.get("a") == "input"
        assert dirs.get("b") == "input"
        assert dirs.get("sum") == "output"
        assert dirs.get("carry_out") == "output"

    def test_parameter_extraction(self, parser, tmp_path):
        f = tmp_path / "adder.v"
        f.write_text(SIMPLE_MODULE)
        mod = parser.parse_file(str(f))[0]
        param_names = [p.name for p in mod.parameters]
        assert "WIDTH" in param_names

    def test_assign_count(self, parser, tmp_path):
        f = tmp_path / "adder.v"
        f.write_text(SIMPLE_MODULE)
        mod = parser.parse_file(str(f))[0]
        assert mod.assign_count >= 1

    def test_fsm_detection(self, parser, tmp_path):
        f = tmp_path / "traffic.v"
        f.write_text(FSM_MODULE)
        mod = parser.parse_file(str(f))[0]
        assert len(mod.fsm_states) > 0
        state_names = [s.name for s in mod.fsm_states]
        # At least one of RED, GREEN, YELLOW should be detected
        assert any(s in state_names for s in ("RED", "GREEN", "YELLOW"))

    def test_always_blocks(self, parser, tmp_path):
        f = tmp_path / "traffic.v"
        f.write_text(FSM_MODULE)
        mod = parser.parse_file(str(f))[0]
        assert mod.always_blocks >= 2

    def test_parse_directory(self, parser, tmp_rtl):
        modules = parser.parse_directory(str(tmp_rtl))
        names = [m.module_name for m in modules]
        assert "adder" in names
        assert "traffic_light" in names
        assert "top" in names

    def test_instantiation_extraction(self, parser, tmp_path):
        f = tmp_path / "top.v"
        f.write_text(HIER_TOP)
        mod = parser.parse_file(str(f))[0]
        inst_mods = [i.module_name for i in mod.instantiations]
        assert "adder" in inst_mods

    def test_file_not_found(self, parser):
        with pytest.raises(FileNotFoundError):
            parser.parse_file("/nonexistent/path/module.v")

    def test_raw_code_preserved(self, parser, tmp_path):
        f = tmp_path / "adder.v"
        f.write_text(SIMPLE_MODULE)
        mod = parser.parse_file(str(f))[0]
        assert "adder" in mod.raw_code
        assert "assign" in mod.raw_code


# ──────────────────────────────────────────────────────────────────────────────
# Hierarchy graph tests
# ──────────────────────────────────────────────────────────────────────────────

class TestHierarchyGraph:

    def _make_modules(self, parser, tmp_rtl) -> list:
        return parser.parse_directory(str(tmp_rtl))

    def test_graph_construction(self, parser, tmp_rtl):
        modules = self._make_modules(parser, tmp_rtl)
        graph   = HierarchyGraph(modules)
        assert "adder" in graph.modules
        assert "top"   in graph.modules

    def test_leaf_modules(self, parser, tmp_rtl):
        modules = self._make_modules(parser, tmp_rtl)
        graph   = HierarchyGraph(modules)
        leaves  = graph.leaf_modules()
        # adder has no sub-instantiations → leaf
        assert "adder" in leaves

    def test_top_level(self, parser, tmp_rtl):
        modules = self._make_modules(parser, tmp_rtl)
        graph   = HierarchyGraph(modules)
        tops    = graph.top_level_modules()
        assert "top" in tops

    def test_bottom_up_order(self, parser, tmp_rtl):
        modules = self._make_modules(parser, tmp_rtl)
        graph   = HierarchyGraph(modules)
        order   = graph.bottom_up_order()
        # adder must come before top
        assert order.index("adder") < order.index("top")

    def test_children_of(self, parser, tmp_rtl):
        modules = self._make_modules(parser, tmp_rtl)
        graph   = HierarchyGraph(modules)
        children = graph.children_of("top")
        assert "adder" in children

    def test_ascii_tree(self, parser, tmp_rtl):
        modules = self._make_modules(parser, tmp_rtl)
        graph   = HierarchyGraph(modules)
        tree    = graph.ascii_tree()
        assert "top"   in tree
        assert "adder" in tree

    def test_summary(self, parser, tmp_rtl):
        modules = self._make_modules(parser, tmp_rtl)
        graph   = HierarchyGraph(modules)
        s = graph.summary()
        assert "total_modules" in s
        assert s["total_modules"] == 3

    def test_empty_graph(self):
        graph = HierarchyGraph([])
        assert graph.bottom_up_order() == []
        assert graph.leaf_modules()    == []
        assert graph.top_level_modules() == []


# ──────────────────────────────────────────────────────────────────────────────
# ModuleInfo helpers
# ──────────────────────────────────────────────────────────────────────────────

class TestModuleInfo:

    def test_port_names(self):
        mod = ModuleInfo(
            file_path="test.v",
            module_name="test",
            ports=[
                Port("clk",  "input",  "1-bit", "wire"),
                Port("rst_n","input",  "1-bit", "wire"),
                Port("out",  "output", "[7:0]", "reg"),
            ]
        )
        assert mod.port_names() == ["clk", "rst_n", "out"]

    def test_child_module_names(self):
        from parser.rtl_parser import Instantiation
        mod = ModuleInfo(
            file_path="top.v",
            module_name="top",
            instantiations=[
                Instantiation("alu", "u_alu"),
                Instantiation("fifo", "u_fifo"),
            ]
        )
        assert set(mod.child_module_names()) == {"alu", "fifo"}
