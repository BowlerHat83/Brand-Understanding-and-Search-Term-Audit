import json
import re
from collections import Counter
from typing import List, Dict

import streamlit as st
from google import genai


# =========================================================
# CLIENT
# =========================================================
def _client():
    key = st.secrets.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("Missing GEMINI_API_KEY")
    return genai.Client(api_key=key)


# =========================================================
# SYSTEM PROMPT (DECISION-FIRST MODEL)
# =========================================================
SYSTEM_PROMPT = """
You are a PPC decision engine.

You must classify every search term using the brand context.

Allowed classifications:
- relevant
- irrelevant
- review (ONLY if truly ambiguous AND confidence < 0.6)

Rules:
- NEVER default to review
- Prefer relevant or irrelevant whenever possible
- Review is a last resort (<5% of cases)
- Be strict and consistent

Return ONLY valid JSON:

{
  "results": [
    {
      "term": "",
      "classification": "relevant | irrelevant | review",
      "confidence": 0.0,
      "reason": "max 10 words"
    }
  ]
}
"""


# =========================================================
# ROOT NEGATIVE EXTRACTION (DERIVED ONLY)
# =========================================================
def extract_root_negatives(irrelevant_terms: List[str], stage1: dict) -> List[str]:

    text = " ".join(irrelevant_terms).lower()
    tokens = re.findall(r"[a-z0-9]+", text)

    stopwords = {
        "the", "and", "for", "with", "this", "that", "from",
        "jobs", "free", "cheap", "download", "best"
    }

    tokens = [t for t in tokens if t not in stopwords and len(t) > 2]

    counts = Counter(tokens)

    # protect brand meaning (never block these)
    protected = set()

    protected.update(stage1.get("brand_variants", []))
    protected.update(stage1.get("direct_competitors", []))

    core = stage1.get("core_offering", "")
    if isinstance(core, str):
        protected.update(core.lower().split())

    roots = [
        word for word, _ in counts.most_common(50)
        if word not in protected
    ]

    return roots


# =========================================================
# BATCH CLASSIFICATION
# =========================================================
def _classify_batch(client, batch: List[str], stage1: dict):

    payload = {
        "brand_context": stage1,
        "search_terms": batch
    }

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=json.dumps(payload),
        config={
            "system_instruction": SYSTEM_PROMPT,
            "response_mime_type": "application/json",
            "temperature": 0.2,
        },
    )

    data = json.loads(response.text)
    results = data.get("results", [])

    cleaned = []

    for i, term in enumerate(batch):
        item = results[i] if i < len(results) else {}

        cleaned.append({
            "term": term,
            "classification": item.get("classification", "review"),
            "confidence": float(item.get("confidence", 0.0) or 0.0),
            "reason": item.get("reason", "")
        })

    return cleaned


# =========================================================
# MAIN PIPELINE
# =========================================================
def run_stage2_audit(search_terms: List[str], stage1: dict, batch_size: int = 30):

    client = _client()

    results = []

    # -----------------------------
    # BATCH PROCESSING
    # -----------------------------
    for i in range(0, len(search_terms), batch_size):
        batch = search_terms[i:i + batch_size]
        results.extend(_classify_batch(client, batch, stage1))

    # -----------------------------
    # ERROR 001: INTEGRITY CHECK
    # -----------------------------
    if len(results) != len(search_terms):
        raise RuntimeError("ERROR 001 — Term count mismatch")

    # -----------------------------
    # SPLIT OUTPUTS
    # -----------------------------
    relevant = [r for r in results if r["classification"] == "relevant"]
    irrelevant = [r for r in results if r["classification"] == "irrelevant"]
    review = [r for r in results if r["classification"] == "review"]

    # -----------------------------
    # ROOT NEGATIVES (DERIVED ONLY)
    # -----------------------------
    root_negatives = extract_root_negatives(
        [r["term"] for r in irrelevant],
        stage1
    )

    # -----------------------------
    # FINAL OUTPUT STRUCTURE
    # -----------------------------
    return {
        "results": results,
        "relevant": relevant,
        "irrelevant": irrelevant,
        "review": review,
        "root_negatives": root_negatives
    }
