import json
import collections
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed

from google import genai
from .gemini_utils import gemini_json
from . import cache_manager as cm


# -----------------------------
# SYSTEM PROMPT
# -----------------------------
BATCH_AUDIT_SYSTEM_PROMPT = """
Classify each term independently.

Return ONLY valid JSON in this format:

{
  "term_data": [
    {
      "term": "",
      "cls": "RELEVANT_BRAND|RELEVANT_GENERIC|IRRELEVANT|REVIEW",
      "conf": 0.0,
      "why": ""
    }
  ]
}

Rules:
- cls MUST be one of the allowed values
- conf MUST be between 0 and 1
- No extra keys
- No explanation outside JSON
"""


# -----------------------------
# BATCH PROCESSOR
# -----------------------------
def _process_batch(client, batch, profile_key, blueprint):
    payload = json.dumps({
        "brand": profile_key.split("|")[0].strip(),
        "bp": blueprint,
        "terms": batch
    })

    return gemini_json(
        client=client,
        model="gemini-2.5-flash",
        system_prompt=BATCH_AUDIT_SYSTEM_PROMPT,
        payload=payload,
        temperature=0.1,
        retries=3
    )


# -----------------------------
# VALIDATION (NEW CRITICAL LAYER)
# -----------------------------
VALID_CLS = {
    "RELEVANT_BRAND",
    "RELEVANT_GENERIC",
    "IRRELEVANT",
    "REVIEW"
}


def _validate_item(item):
    """Hard schema gate — prevents silent corruption."""
    if not isinstance(item, dict):
        return None

    term = str(item.get("term", "")).strip()
    if not term:
        return None

    cls = item.get("cls")
    conf = item.get("conf")

    # enforce class validity
    if cls not in VALID_CLS:
        cls = "REVIEW"

    # enforce confidence validity
    try:
        conf = float(conf)
    except:
        conf = 0.0

    conf = max(0.0, min(1.0, conf))

    return {
        "Search Term": term,
        "cls": cls,
        "Confidence Score": conf,
        "Reasoning": item.get("why", "")
    }


# -----------------------------
# MAIN PIPELINE
# -----------------------------
def run_search_terms_audit(csv_file, selected_profile_key: str,
                           progress_bar_ui=None, status_text_ui=None):

    cached_profile = cm.get_profile_by_name(selected_profile_key)
    if not cached_profile:
        raise ValueError("Profile not found")

    blueprint = cached_profile["blueprint"]

    df = pd.read_csv(csv_file)
    df.columns = [c.lower().strip() for c in df.columns]

    if "search term" not in df.columns:
        raise KeyError("Missing 'Search term' column")

    raw_terms = df["search term"].dropna().astype(str).str.strip().unique().tolist()
    total_input = len(raw_terms)

    # -----------------------------
    # BATCHING
    # -----------------------------
    BATCH_SIZE = 20
    batches = [raw_terms[i:i + BATCH_SIZE] for i in range(0, len(raw_terms), BATCH_SIZE)]

    client = genai.Client()

    results = []
    failed_batches = []

    # -----------------------------
    # PARALLEL EXECUTION
    # -----------------------------
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(_process_batch, client, batch, selected_profile_key, blueprint): batch
            for batch in batches
        }

        for i, future in enumerate(as_completed(futures)):
            batch = futures[future]

            try:
                payload = future.result()

                # ❗ HARD FIX: validate structure BEFORE trusting it
                term_data = payload.get("term_data", None)

                if not isinstance(term_data, list):
                    raise ValueError("Invalid term_data format")

                for item in term_data:
                    validated = _validate_item(item)
                    if validated:
                        results.append(validated)

            except Exception:
                failed_batches.append(batch)

            if progress_bar_ui:
                progress_bar_ui.progress((i + 1) / len(batches))

    # -----------------------------
    # RETRY FAILED BATCHES
    # -----------------------------
    if failed_batches:
        for batch in failed_batches:
            try:
                payload = _process_batch(client, batch, selected_profile_key, blueprint)

                term_data = payload.get("term_data", [])
                for item in term_data:
                    validated = _validate_item(item)
                    if validated:
                        results.append(validated)

            except Exception:
                results.extend([
                    {
                        "Search Term": t,
                        "cls": "REVIEW",
                        "Confidence Score": 0.0,
                        "Reasoning": "batch_failed"
                    }
                    for t in batch
                ])

    # -----------------------------
    # CLASSIFICATION (SIMPLIFIED)
    # -----------------------------
    relevant, irrelevant, review = [], [], []

    for item in results:
        cls = item["cls"]

        record = {
            "Search Term": item["Search Term"],
            "Reasoning": item["Reasoning"],
            "Confidence Score": item["Confidence Score"]
        }

        # ONLY cls determines routing
        if cls in ["RELEVANT_BRAND", "RELEVANT_GENERIC"]:
            relevant.append(record)

        elif cls == "IRRELEVANT":
            irrelevant.append(record)

        else:
            review.append(record)

    # -----------------------------
    # ROOT EXTRACTION (UNCHANGED)
    # -----------------------------
    raw_irrelevant = [x["Search Term"] for x in irrelevant]

    words = []
    for t in raw_irrelevant:
        words.extend(t.lower().split())

    freq = collections.Counter(words)

    roots = {
        w for w, c in freq.items()
        if c > 1 and len(w) > 2
    }

    def tokenize(text):
        return set(text.lower().split())

    def is_covered(term: str) -> bool:
        return any(root in tokenize(term) for root in roots)

    leftover_irrelevants = [
        t for t in raw_irrelevant if not is_covered(t)
    ]

    negative_export = "\n".join(
        sorted(roots) + leftover_irrelevants
    )

    # -----------------------------
    # METRICS
    # -----------------------------
    return {
        "metrics": {
            "total_inputted": total_input,
            "total_outputted": len(relevant) + len(irrelevant) + len(review),
            "relevant_count": len(relevant),
            "irrelevant_count": len(irrelevant),
            "review_queue_count": len(review),
            "roots_found": len(roots),
        },

        "review_queue_data": [x["Search Term"] for x in review],

        "copy_paste_notation": negative_export,

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
