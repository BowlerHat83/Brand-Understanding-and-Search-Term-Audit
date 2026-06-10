import re
from typing import List


# -----------------------------
# TEXT CLEANING
# -----------------------------
def clean_search_term(term: str) -> str:
    """
    Normalises a search term for consistent processing.
    """
    if not isinstance(term, str):
        return ""

    term = term.strip().lower()
    term = re.sub(r"\s+", " ", term)
    return term


# -----------------------------
# CSV SAFETY CLEANING
# -----------------------------
def clean_search_terms_list(terms: List[str]) -> List[str]:
    """
    Cleans and filters raw search term lists.
    Removes empty / invalid rows.
    """
    cleaned = []

    for t in terms:
        t_clean = clean_search_term(t)
        if t_clean:
            cleaned.append(t_clean)

    return list(dict.fromkeys(cleaned))  # deduplicate, preserve order


# -----------------------------
# BATCH SPLITTER (used in Stage 2)
# -----------------------------
def chunk_list(items: List[str], chunk_size: int = 30):
    """
    Splits list into fixed-size chunks.
    """
    for i in range(0, len(items), chunk_size):
        yield items[i:i + chunk_size]


# -----------------------------
# CONFIDENCE HELPERS
# -----------------------------
def is_low_confidence(confidence: float, threshold: float = 0.7) -> bool:
    """
    Determines whether a term should be flagged for manual review.
    """
    try:
        return float(confidence) < threshold
    except (TypeError, ValueError):
        return True


# -----------------------------
# TERM VALIDATION
# -----------------------------
def is_valid_term(term: str) -> bool:
    """
    Basic validation for search terms.
    Filters junk rows from CSV exports.
    """
    if not term:
        return False

    term = term.strip()

    if len(term) < 2:
        return False

    # remove pure numbers / symbols
    if re.fullmatch(r"[\W\d_]+", term):
        return False

    return True


# -----------------------------
# SAFE INT PARSE (Streamlit inputs etc.)
# -----------------------------
def safe_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
