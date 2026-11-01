"""
Central place for constants used across the chatbot module.
Keeping these here means no magic numbers/strings scattered in other files.
"""

import os
from dotenv import load_dotenv

load_dotenv()  # reads .env file into environment variables

# --- LLM ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
LLM_MODEL = "openai/gpt-oss-20b"

# --- Embeddings ---
EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"

# --- Chunking (used Day 2) ---
CHUNK_SIZE = 300       # characters per chunk, roughly
CHUNK_OVERLAP = 50

# --- Retrieval (used Day 2-3) ---
TOP_K = 4

# --- Paths ---
RAW_DOCS_DIR = "knowledge_base/raw"
PROCESSED_DOCS_DIR = "knowledge_base/processed"
VECTOR_STORE_DIR = "knowledge_base/vector_store"