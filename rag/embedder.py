"""
rag/embedder.py

Indexes RTL module knowledge into ChromaDB using sentence-transformers embeddings.
Each module is chunked into logical units (overview, ports, hierarchy, FSM, summary)
so retrieval returns focused, relevant context rather than dumping entire files.
"""

from __future__ import annotations

import os
import json
from typing import List, Dict, Optional

import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer

from parser.rtl_parser import ModuleInfo


# ──────────────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────────────

DEFAULT_EMBED_MODEL  = "all-MiniLM-L6-v2"   # fast, good quality, ~80 MB
COLLECTION_NAME      = "rtl_modules"
DEFAULT_PERSIST_DIR  = "./chroma_store"


# ──────────────────────────────────────────────────────────────────────────────
# Embedder
# ──────────────────────────────────────────────────────────────────────────────

class RTLEmbedder:
    """
    Chunks module info + LLM summaries into text documents,
    embeds them with sentence-transformers, and stores in ChromaDB.
    """

    def __init__(
        self,
        persist_dir: str = DEFAULT_PERSIST_DIR,
        embed_model: str = DEFAULT_EMBED_MODEL,
    ):
        self.persist_dir = persist_dir
        os.makedirs(persist_dir, exist_ok=True)

        print(f"  Loading embedding model: {embed_model}")
        self.embedder = SentenceTransformer(embed_model)

        self.chroma = chromadb.PersistentClient(
            path=persist_dir,
            settings=Settings(anonymized_telemetry=False),
        )
        self.collection = self.chroma.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def index_modules(
        self,
        modules: List[ModuleInfo],
        summaries: Dict[str, str],
    ):
        """Add all modules (with their summaries) to the vector store."""
        for mod in modules:
            summary = summaries.get(mod.module_name, "")
            chunks  = self._chunk_module(mod, summary)
            self._upsert_chunks(chunks)
        print(f"  Indexed {len(modules)} modules into ChromaDB.")

    def query(
        self,
        question: str,
        top_k: int = 5,
        module_filter: Optional[str] = None,
    ) -> str:
        """
        Retrieve the most relevant context chunks for a question.
        Returns a formatted string ready to inject into an LLM prompt.
        """
        where = {"module": module_filter} if module_filter else None
        query_vec = self._embed([question])[0]

        results = self.collection.query(
            query_embeddings=[query_vec],
            n_results=min(top_k, self.collection.count() or 1),
            where=where,
        )

        if not results["documents"] or not results["documents"][0]:
            return "No relevant design context found."

        parts = []
        for doc, meta, distance in zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        ):
            relevance = round(1 - distance, 3)
            parts.append(
                f"[{meta.get('module','?')} / {meta.get('chunk_type','?')}]"
                f"  relevance={relevance}\n{doc}"
            )

        return "\n\n---\n\n".join(parts)

    def collection_size(self) -> int:
        return self.collection.count()

    # ── Chunking ──────────────────────────────────────────────────────────────

    def _chunk_module(
        self,
        mod: ModuleInfo,
        summary: str,
    ) -> List[Dict]:
        chunks = []
        name   = mod.module_name

        # 1) Overview + summary
        overview = (
            f"Module: {name}\n"
            f"File: {mod.file_path}\n"
            f"Parse method: {mod.parse_method}\n"
            f"Always blocks: {mod.always_blocks}, Assign stmts: {mod.assign_count}\n"
        )
        if summary:
            overview += f"\nSummary:\n{summary}"
        chunks.append(self._make_chunk(f"{name}:overview", overview, name, "overview"))

        # 2) Ports
        if mod.ports:
            port_text = f"Ports of module {name}:\n"
            for p in mod.ports:
                port_text += f"  {p.direction:8} {p.width:12} {p.name}  ({p.data_type})\n"
            chunks.append(self._make_chunk(f"{name}:ports", port_text, name, "ports"))

        # 3) Parameters / localparams
        if mod.parameters or mod.localparams:
            param_text = f"Parameters of module {name}:\n"
            for p in mod.parameters:
                param_text += f"  parameter {p.name} = {p.value}\n"
            for k, v in mod.localparams.items():
                param_text += f"  localparam {k} = {v}\n"
            chunks.append(self._make_chunk(f"{name}:params", param_text, name, "params"))

        # 4) Hierarchy / instantiations
        if mod.instantiations:
            hier_text = f"Module {name} instantiates:\n"
            for inst in mod.instantiations:
                hier_text += f"  {inst.module_name}  as  {inst.instance_name}\n"
                for port, sig in list(inst.port_connections.items())[:6]:
                    hier_text += f"    .{port}({sig})\n"
            chunks.append(self._make_chunk(f"{name}:hierarchy", hier_text, name, "hierarchy"))

        # 5) FSM
        if mod.fsm_states:
            fsm_text = f"FSM states in module {name}:\n"
            for s in mod.fsm_states:
                fsm_text += f"  {s.name}  →  {', '.join(s.transitions) or 'terminal'}\n"
            chunks.append(self._make_chunk(f"{name}:fsm", fsm_text, name, "fsm"))

        return chunks

    @staticmethod
    def _make_chunk(
        doc_id: str,
        content: str,
        module: str,
        chunk_type: str,
    ) -> Dict:
        return {
            "id":       doc_id,
            "content":  content,
            "metadata": {"module": module, "chunk_type": chunk_type},
        }

    def _upsert_chunks(self, chunks: List[Dict]):
        if not chunks:
            return
        texts = [c["content"]  for c in chunks]
        ids   = [c["id"]       for c in chunks]
        metas = [c["metadata"] for c in chunks]
        vecs  = self._embed(texts)
        self.collection.upsert(
            ids=ids,
            embeddings=vecs,
            documents=texts,
            metadatas=metas,
        )

    def _embed(self, texts: List[str]) -> List[List[float]]:
        return self.embedder.encode(texts, show_progress_bar=False).tolist()
