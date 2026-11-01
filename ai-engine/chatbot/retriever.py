"""
Loads the saved FAISS index + chunk metadata, and exposes a search function.
This is what rag_pipeline.py will call for every farmer question.
"""

import os
import json
import faiss
import numpy as np

from chatbot.config import VECTOR_STORE_DIR, TOP_K
from chatbot.embeddings import embed_text

_index = None
_chunks = None
_metadata = None


def _load_index():
    """Load the FAISS index and chunk data into memory once."""
    global _index, _chunks, _metadata
    if _index is None:
        _index = faiss.read_index(os.path.join(VECTOR_STORE_DIR, "index.faiss"))
        with open(os.path.join(VECTOR_STORE_DIR, "chunks.json"), "r", encoding="utf-8") as f:
            data = json.load(f)
        _chunks = data["chunks"]
        _metadata = data["metadata"]


def search(query: str, top_k: int = TOP_K) -> list[dict]:
    """
    Given a farmer's question, return the top_k most relevant chunks.
    Each result: {"text": ..., "source": ..., "score": ...}
    """
    _load_index()

    query_vector = embed_text(query).astype("float32").reshape(1, -1)
    distances, indices = _index.search(query_vector, top_k)

    results = []
    for rank, idx in enumerate(indices[0]):
        if idx == -1:
            continue  # FAISS returns -1 if there aren't enough results
        results.append({
            "text": _chunks[idx],
            "source": _metadata[idx]["source"],
            "score": float(distances[0][rank]),  # lower = more similar, for L2 distance
        })
    return results