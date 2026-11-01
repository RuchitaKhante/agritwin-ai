"""
Text chunking used by ingest.py. Kept free of heavy imports (no embedding model) so it is easy to test.
"""

from chatbot.config import CHUNK_SIZE, CHUNK_OVERLAP


def clean_text(text: str) -> str:
    """Basic cleanup: collapse extra whitespace/blank lines."""
    lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in lines if line]  # drop empty lines
    return " ".join(lines)


def chunk_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    """Split text into overlapping chunks of roughly chunk_size characters (used for oversized paragraphs)."""
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        chunks.append(chunk.strip())
        start += chunk_size - overlap  # step forward, but overlap a bit
    return [c for c in chunks if c]  # drop any empty chunks


MAX_PARAGRAPH_CHARS = 1100   # a paragraph up to this size stays ONE chunk (e.g. one crop's guidance)
MIN_PARAGRAPH_CHARS = 120    # tiny blocks (titles) are glued to the next paragraph


def chunk_document(raw_text: str) -> list[str]:
    """
    Paragraph-aware chunking: every blank-line-separated paragraph becomes one chunk, so a crop's guidance,
    a formula or a rule is never cut in half. Very long paragraphs fall back to overlapping windows.
    """
    paragraphs = [clean_text(p) for p in raw_text.replace("\r\n", "\n").split("\n\n")]
    paragraphs = [p for p in paragraphs if p]

    glued, carry = [], ""
    for p in paragraphs:
        p = (carry + " " + p).strip() if carry else p
        carry = ""
        if len(p) < MIN_PARAGRAPH_CHARS:
            carry = p
        else:
            glued.append(p)
    if carry:
        glued.append(carry)

    chunks = []
    for p in glued:
        if len(p) <= MAX_PARAGRAPH_CHARS:
            chunks.append(p)
        else:
            chunks.extend(chunk_text(p, CHUNK_SIZE * 3, CHUNK_OVERLAP))
    return chunks