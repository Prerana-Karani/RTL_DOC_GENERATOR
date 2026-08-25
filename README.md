# RTL Documentation Generator

Automated design documentation using **RAG + LLM** — inspired by RTLExplain (IBM / DAC 2025).

Reads Verilog/SystemVerilog RTL, understands module hierarchy, and generates accurate, structured documentation without manual effort.

---

## Architecture

```
rtl-doc-gen/
├── main.py                # Entry point — runs full pipeline
│
├── parser/
│   └── rtl_parser.py      # PyVerilog AST parsing + regex fallback
│
├── graph/
│   └── hierarchy.py       # NetworkX dependency graph + topological sort
│
├── summariser/
│   └── bottom_up.py       # Leaf-first LLM summarisation (Groq)
│
├── rag/
│   ├── embedder.py        # Sentence-transformers + ChromaDB indexing
│   └── generator.py       # RAG retrieval + full doc generation (Groq)
│
├── output/
│   └── writer.py          # Markdown + HTML report (Jinja2)
│
├── rtl/                   # ← Put your .v / .sv files here
├── docs/                  # ← Generated documentation appears here
├── chroma_store/          # ChromaDB persisted vectors
├── tests/
│   └── test_pipeline.py   # pytest unit tests
│
├── requirements.txt
└── .env                   # GROQ_API_KEY goes here
```

---

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Get a free Groq API key

Visit [console.groq.com](https://console.groq.com) — no credit card required.

### 3. Configure API key

```bash
# .env
GROQ_API_KEY=your_key_here
```

Or export directly:
```bash
export GROQ_API_KEY=your_key_here
```

### 4. Add your RTL files

```bash
cp your_design/*.v rtl/
cp your_design/*.sv rtl/
```

Three sample files are included (`alu.v`, `fifo.v`, `soc_top.v`).

### 5. Run the pipeline

```bash
python main.py
```

Open `docs/index.html` in your browser.

---

## Pipeline Stages

| Stage | What happens |
|-------|-------------|
| **1. Parse** | PyVerilog (+ regex fallback) extracts module names, ports, parameters, FSM states, instantiations |
| **2. Hierarchy** | NetworkX builds a DAG of module dependencies; topological sort gives bottom-up processing order |
| **3. Summarise** | Groq LLM summarises leaf modules first; summaries propagate up to parent modules |
| **4. Embed** | `sentence-transformers/all-MiniLM-L6-v2` encodes chunks; ChromaDB stores them persistently |
| **5. Generate** | RAG retrieves relevant chunks; Groq LLM generates full structured Markdown docs per module |
| **6. Write** | Individual `.md` files + unified `index.html` report with sidebar navigation |

---

## CLI Options

```bash
# Document a specific RTL directory
python main.py --rtl path/to/rtl/ --project "My SoC"

# Parse + hierarchy only (no LLM calls)
python main.py --parse-only

# Interactive Q&A over the indexed design
python main.py --qa

# Custom output directory
python main.py --output ./my_docs --chroma ./my_vectors
```

---

## Run Tests

```bash
pytest tests/ -v
```

Tests cover parser, hierarchy graph, and data model — no API key required.

---

## Key Design Choices

**Bottom-up summarisation** — Leaf modules are summarised first. Their summaries are injected into parent module prompts, giving the LLM accurate cross-module context without exceeding the context window. This is the core technique from RTLExplain (IBM / DAC 2025), which achieved a 37% Q&A accuracy improvement over naïve prompting.

**RAG over direct prompting** — Instead of feeding the full codebase into the LLM, ChromaDB retrieves the 5 most relevant chunks per query. This scales to thousands of modules.

**No fine-tuning** — Off-the-shelf Groq LLMs guided by structured RTL knowledge produce accurate documentation.

---

## Output

- `docs/<module>.md` — Markdown file per module
- `docs/index.html` — Unified HTML report with:
  - Module hierarchy tree
  - Port quick-view cards (colour-coded by direction)
  - Full structured documentation (Overview, Ports, Behaviour, FSM, Hierarchy, Notes)
  - Sidebar navigation

---

## References

1. RTLExplain: *A Structured Approach to RTL Code Summarization and Q&A Using LLMs* — IBM Research, DAC 2025
2. *Better Automatic Generation of Documentation from RTL Code* — AMIQ EDA / SemiWiki
3. *LLMs for RTL Design Tasks* — arXiv 2506.13905, 2025
