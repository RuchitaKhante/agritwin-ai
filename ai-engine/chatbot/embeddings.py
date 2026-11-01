"""
Wraps the sentence-transformers embedding model.
Loaded once at import time and reused everywhere else.
"""

from sentence_transformers import SentenceTransformer
from chatbot.config import EMBEDDING_MODEL_NAME

# This downloads the model the first time (~80MB) and caches it locally after.
_model = SentenceTransformer(EMBEDDING_MODEL_NAME)


def embed_text(text: str):
    """Turn a single string into a vector (list of floats)."""
    return _model.encode(text, convert_to_numpy=True)


def embed_texts(texts: list[str]):
    """Turn a list of strings into a list of vectors. Faster than calling embed_text in a loop."""
    return _model.encode(texts, convert_to_numpy=True)