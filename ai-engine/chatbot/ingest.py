"""
One-time (or re-run-when-docs-change) script that:
1. Loads all .txt files from knowledge_base/raw/
2. Cleans and chunks them
3. Embeds each chunk
4. Saves a FAISS index + metadata to knowledge_base/vector_store/

Run this manually: python -m chatbot.ingest   (from the project root)
Re-run it any time you add/edit a document in knowledge_base/raw/.
"""

import os
import json
import faiss
import numpy as np

from chatbot.config import (
    RAW_DOCS_DIR,
    VECTOR_STORE_DIR,
    CHUNK_SIZE,
    CHUNK_OVERLAP,
)
from chatbot.chunking import clean_text, chunk_text, chunk_document  # noqa: F401
from chatbot.embeddings import embed_texts


def load_documents(folder_path: str) -> list[dict]:
    """Read every .txt file in the folder. Returns a list of {source, text}."""
    documents = []
    for filename in sorted(os.listdir(folder_path)):
        if filename.endswith(".txt"):
            file_path = os.path.join(folder_path, filename)
            with open(file_path, "r", encoding="utf-8") as f:
                text = f.read()
            documents.append({"source": filename, "text": text})
    return documents


def build_index():
    print("Loading documents...")
    documents = load_documents(RAW_DOCS_DIR)
    print(f"Loaded {len(documents)} documents.")

    all_chunks = []       # the actual chunk text
    all_metadata = []      # {source, chunk_id} for each chunk, same order as all_chunks

    for doc in documents:
        chunks = chunk_document(doc["text"])
        for i, chunk in enumerate(chunks):
            all_chunks.append(chunk)
            all_metadata.append({"source": doc["source"], "chunk_id": i})

    print(f"Created {len(all_chunks)} chunks total.")

    print("Embedding chunks...")
    embeddings = embed_texts(all_chunks)  # shape: (num_chunks, 384)
    embeddings = np.array(embeddings).astype("float32")

    print("Building FAISS index...")
    dimension = embeddings.shape[1]
    index = faiss.IndexFlatL2(dimension)  # simple, exact search — fine for small doc sets
    index.add(embeddings)

    os.makedirs(VECTOR_STORE_DIR, exist_ok=True)
    faiss.write_index(index, os.path.join(VECTOR_STORE_DIR, "index.faiss"))

    # Save chunk text + metadata alongside the index, so we can map
    # a FAISS result (just a number) back to readable text + source.
    with open(os.path.join(VECTOR_STORE_DIR, "chunks.json"), "w", encoding="utf-8") as f:
        json.dump({"chunks": all_chunks, "metadata": all_metadata}, f, ensure_ascii=False, indent=2)

    print(f"Done. Index saved to {VECTOR_STORE_DIR}/")


if __name__ == "__main__":
    build_index()