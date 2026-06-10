import json
import collections
import pandas as pd

from concurrent.futures import ThreadPoolExecutor, as_completed
from google import genai

from .gemini_utils import gemini_json
from . import cache_manager as cm


# -----------------------------
# SYSTEM PROMPT (LIGHTWEIGHT)
# -----------------------------
BATCH_AUDIT_SYSTEM_PROMPT = """
Classify each search term independently.

Return STRICT JSON only:

{
  "term_data": [
    {
      "term": "",
      "cls": "RELEVANT_BRAND | RELEVANT_GENERIC | IRRELEVANT | REVIEW",
      "conf": 0.0,
      "why": "max 5 words"
    }
  ]
}

No commentary. No markdown.
"""


# -----------------------------
# GEMINI PROCESSOR
# -----------------------------
def _process_batch(client, batch, profile_key, blueprint):
    payload = {
        "brand": profile_key.split("|")[0].strip(),
        "blueprint": blueprint,
        "terms": batch
    }

    return gemini_json(
        client=client,
        model="gemini-2.5-flash",
        system_prompt=BATCH_AUDIT_SYSTEM_PROMPT,
        payload=json.dumps(payload),
        temperature=0.1,
        retries=3
    )


# -----------------------------
# BLUEPRINT SCORING (NEW CORE ADDITION)
# -----------------------------
def _score_term(term: str, blueprint: dict) -> float:
    t = term.lower()

    score = 0.0

    # Brand match
    for v in blueprint.get("brand_variants", []):
        if v.lower() in t:
            score += 0.6

    # Negative triggers (business-specific, not universal)
    for n in blueprint.get("explicit_negative_triggers", []):
        if n.lower() in t:
            score -= 0.5

    # Competitors
    for c in blueprint.get("predicted_competitors", []):
        if c.lower() in t:
            score -= 0.4

    return score


# -----------------------------
# ROUTING LOGIC
# -----------------------------
def _route_terms(terms, blueprint):
    auto_relevant = []
    auto_irrelevant = []
    ambiguous = []

    for t in terms:
        score = _score_term(t, blueprint)

        if score >= 0.7:
            auto_relevant.append(t)
        elif score <= -0.6:
            auto_irrelevant.append(t)
        else:
            ambiguous.append(t)

    return auto_relevant, auto_irrelevant, ambiguous


# -----------------------------
# MAIN PIPELINE
# -----------------------------
def run_search_terms_audit(
    csv_file,
    selected_profile_key: str,
    progress_bar_ui=None,
    status_text_ui=None
):

    cached_profile = cm.get_profile_by_name(selected_profile_key)
    if not cached_profile:
        raise ValueError("Profile not found")

    blueprint = cached_profile["blueprint"]

    df = pd.read_csv(csv_file)
    df.columns = [c.lower().strip() for c in df.columns]

    if "search term" not in df.columns:
        raise KeyError("Missing 'Search term' column")

    raw_terms = (
        df["search term"]
        .dropna()
        .astype(str)
        .str.strip()
        .unique()
        .tolist()
    )

    total_input = len(raw_terms)

    # -----------------------------
    # STEP 1: LOCAL ROUTING (NEW)
    # -----------------------------
    auto_rel, auto_irrel, ambiguous = _route_terms(raw_terms, blueprint)

    # -----------------------------
    # STEP 2: BATCH AMBIGUOUS ONLY
    # -----------------------------
    BATCH_SIZE = 40
    batches = [
        ambiguous[i:i + BATCH_SIZE]
        for i in range(0, len(ambiguous), BATCH_SIZE)
    ]

    client = genai.Client()

    results = []

    # -----------------------------
    # PARALLEL GEMINI EXECUTION
    # -----------------------------
    if batches:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(
                    _process_batch,
                    client,
                    batch,
                    selected_profile_key,
                    blueprint
                )
                for batch in batches
            ]

            for i, future in enumerate(as_completed(futures)):
                if progress_bar_ui:
                    progress_bar_ui.progress((i + 1) / len(batches))

                try:
                    payload = future.result()
                    results.extend(payload.get("term_data", []))
                except Exception as e:
                    # no silent failure
                    results.append({
                        "term": "BATCH_ERROR",
                        "cls": "REVIEW",
                        "conf": 0.0,
                        "why": str(e)
                    })

    # -----------------------------
    # MERGE AUTO + GEMINI RESULTS
    # -----------------------------
    relevant, irrelevant, review = [], [], []

    def add_record(term, cls, conf=1.0, why="auto"):
        record = {
            "Search Term": term,
            "Reasoning": why,
            "Confidence Score": conf
        }

        if cls in ["RELEVANT_BRAND", "RELEVANT_GENERIC"]:
            relevant.append(record)
        elif cls == "IRRELEVANT":
            irrelevant.append(record)
        else:
            review.append(record)

    # Auto-classified results
    for t in auto_rel:
        add_record(t, "RELEVANT_GENERIC", 1.0, "blueprint_match")

    for t in auto_irrel:
        add_record(t, "IRRELEVANT", 1.0, "negative_match")

    # Gemini results
    for item in results:
        add_record(
            item.get("term", ""),
            item.get("cls", "REVIEW"),
            float(item.get("conf", 0) or 0),
            item.get("why", "")
        )

    # -----------------------------
    # ROOT EXTRACTION (light cleanup of your original logic)
    # -----------------------------
    raw_irrelevant = [x["Search Term"] for x in irrelevant]
    safe_terms = set(
        x["Search Term"].lower().strip()
        for x in (relevant + review)
    )

    def stem(w):
        w = w.lower()
        if w.endswith("ies"):
            return w[:-3] + "i"
        if w.endswith("es"):
            return w[:-2]
        if w.endswith("s") and len(w) > 3:
            return w[:-1]
        return w

    protected = set(selected_profile_key.lower().split())
    protected_stems = {stem(x) for x in protected}

    safe_stems = {
        stem(w)
        for t in safe_terms
        for w in t.split()
    }

    words = []
    for t in raw_irrelevant:
        words.extend(t.lower().split())

    freq = collections.Counter(words)
    candidates = [w for w, c in freq.items() if c > 1 and len(w) > 2]

    roots = [
        r for r in candidates
        if stem(r) not in protected_stems
        and stem(r) not in safe_stems
    ]

    # -----------------------------
    # OUTPUT
    # -----------------------------
    return {
        "metrics": {
            "total_inputted": total_input,
            "relevant_count": len(relevant),
            "irrelevant_count": len(irrelevant),
            "review_queue_count": len(review),
            "total_outputted": len(relevant + irrelevant + review),
            "roots_found": len(roots),

            # NEW visibility metric (important for debugging speed gains)
            "auto_classified": len(auto_rel) + len(auto_irrel),
            "llm_classified": len(results),
        },
        "review_queue_data": [x["Search Term"] for x in review],
        "copy_paste_notation": "\n".join(roots),
        "raw_classified_records": {
            "relevant": relevant,
            "review": review,
            "irrelevant": irrelevant,
            "roots_summary": [
                {"Isolated Root Word": r, "Frequency Count": freq[r]}
                for r in roots
            ],
        }
    }
