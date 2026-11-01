"""
Corrects common agricultural/project-term typos using fuzzy matching
against a fixed domain dictionary. Deliberately conservative:
only replaces a word if it's a close-but-not-exact match to a known
term, so correctly-spelled words and unrelated words (crop names,
farmer names, numbers) are never touched.
"""

from rapidfuzz import process, fuzz

# Core domain vocabulary - extend this list as you notice more real typos.
DOMAIN_TERMS = [
    "irrigation", "irrigate", "moisture", "temperature", "humidity",
    "soil", "crop", "water", "fertilizer", "drought", "rainfall",
    "forecast", "sensor", "advisory", "schedule", "drip", "sprinkler",
    "waterlogging", "wilting", "nutrient", "yield", "harvest",
]

SIMILARITY_THRESHOLD = 85  # 0-100, higher = stricter matching
MIN_WORD_LENGTH = 5        # short words are never "corrected" (too many false positives)

# Real words that look close to a domain term but must NEVER be rewritten
# (e.g. "field" -> "yield", "later" -> "water", "oil" -> "soil" broke questions before).
PROTECTED_WORDS = {
    "field", "fields", "later", "water", "waters", "soils", "crops", "oil", "yields", "wheat",
    "rain", "rainy", "dry", "wet", "much", "when", "should", "which", "after", "before",
    "today", "tomorrow", "week", "days", "plant", "plants", "paddy", "maize", "cotton",
}


def correct_typos(text: str) -> str:
    """
    Scans each word in the input text. If a word is NOT already a
    real word (in our dictionary) but is a close fuzzy match to one,
    replace it. Otherwise leave the word untouched.
    """
    words = text.split()
    corrected_words = []

    for word in words:
        # Strip trailing punctuation for matching, but keep it for output
        stripped = word.strip(".,?!")
        trailing_punct = word[len(stripped):]

        lower_word = stripped.lower()

        # If it's already an exact match to a known term, don't touch it.
        if lower_word in DOMAIN_TERMS:
            corrected_words.append(word)
            continue

        # Too short or a known ordinary word -> leave it alone.
        if len(lower_word) < MIN_WORD_LENGTH or lower_word in PROTECTED_WORDS:
            corrected_words.append(word)
            continue

        # Find the closest domain term by fuzzy similarity.
        match = process.extractOne(lower_word, DOMAIN_TERMS, scorer=fuzz.ratio)

        if match and match[1] >= SIMILARITY_THRESHOLD:
            corrected_words.append(match[0] + trailing_punct)
        else:
            # Not a close match to anything - leave it exactly as typed.
            # This protects crop names, farmer names, numbers, etc.
            corrected_words.append(word)

    return " ".join(corrected_words)