from collections import Counter
import re


# -----------------------------
# BASIC STOPWORDS (lightweight, PPC-focused)
# -----------------------------
STOPWORDS = {
    "the", "and", "or", "for", "with", "a", "an", "to", "in", "of",
    "is", "on", "by", "this", "that", "it", "as", "at", "from"
}


# -----------------------------
# TOKEN CLEANING
# -----------------------------
def _tokenize(text: str):
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    tokens = text.split()
    return [t for t in tokens if t not in STOPWORDS and len(t) > 1]


# -----------------------------
# MAIN FUNCTION
# -----------------------------
def extract_root_negatives(stage2_results: list, top_k: int = 50) -> list:
    """
    Extracts high-frequency root negative terms from Stage 2 output.
    """

    all_terms = []

    for item in stage2_results:
        # focus only on irrelevant + low-confidence noise
        if (
            item.get("classification") == "irrelevant"
            or item.get("confidence", 1.0) < 0.5
        ):
            term = item.get("term", "")
            all_terms.extend(_tokenize(term))

    if not all_terms:
        return []

    counts = Counter(all_terms)

    # return most common roots
    most_common = counts.most_common(top_k)

    return [word for word, _ in most_common]
