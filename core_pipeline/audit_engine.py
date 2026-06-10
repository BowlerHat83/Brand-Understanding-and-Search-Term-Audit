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

Return JSON:
{
  term_data:[
    {
      term:"",
      cls:"RELEVANT_BRAND|RELEVANT_GENERIC|IRRELEVANT|REVIEW",
      conf:0-1,
      why:"max 5 words"
    }
  ]
}
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
# MAIN PIPELINE
# -----------------------------
def run_search_terms_audit(csv_file, selected_profile_key: str,
                           progress_bar_ui=None, status_text_ui=None) -> dict:

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
                results.extend(payload.get("term_data", []))

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
                results.extend(payload.get("term_data", []))
            except Exception:
                results.extend([
                    {"term": t, "cls": "REVIEW", "conf": 0, "why": "batch_failed"}
                    for t in batch
                ])

    # -----------------------------
    # CLASSIFICATION
    # -----------------------------
    relevant, irrelevant, review = [], [], []

    for item in results:
        term = str(item.get("term", "")).strip()
        if not term:
            continue

        cls = item.get("cls", "REVIEW")
        conf = float(item.get("conf", 0) or 0)

        record = {
            "Search Term": term,
            "Reasoning": item.get("why", ""),
            "Confidence Score": conf,
        }

        if conf < 0.7 or cls == "REVIEW":
            review.append(record)
        elif cls in ["RELEVANT_BRAND", "RELEVANT_GENERIC"]:
            relevant.append(record)
        elif cls == "IRRELEVANT":
            irrelevant.append(record)
        else:
            review.append(record)

    # -----------------------------
    # ROOT EXTRACTION
    # -----------------------------
    raw_irrelevant = [x["Search Term"] for x in irrelevant]

    def stem(w):
        w = w.lower()
        if w.endswith("ies"):
            return w[:-3] + "i"
        if w.endswith("es"):
            return w[:-2]
        if w.endswith("s") and len(w) > 3:
            return w[:-1]
        return w

    words = []
    for t in raw_irrelevant:
        words.extend(t.lower().split())

    freq = collections.Counter(words)
    roots = [w for w, c in freq.items() if c > 1 and len(w) > 2]

    root_set = set(roots)

    # -----------------------------
    # 🚨 KEY FIX: preserve ALL irrelevants
    # -----------------------------
    irrelevants_raw = [
        x for x in raw_irrelevant
        if not any(root in x.lower() for root in root_set)
    ]

    # -----------------------------
    # FINAL OUTPUT STRING (ROOTS + NON-ROOT IRRELEVANTS)
    # -----------------------------
    negative_export = "\n".join(
        roots + irrelevants_raw
    )

    # -----------------------------
    # METRICS
    # -----------------------------
    total_output = len(relevant) + len(irrelevant) + len(review)

    return {
        "metrics": {
            "total_inputted": total_input,
            "total_outputted": total_output,
            "relevant_count": len(relevant),
            "irrelevant_count": len(irrelevant),
            "review_queue_count": len(review),
            "roots_found": len(roots),
        },

        "review_queue_data": [x["Search Term"] for x in review],

        # ✅ FIXED: now includes BOTH roots + leftover irrelevants
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
