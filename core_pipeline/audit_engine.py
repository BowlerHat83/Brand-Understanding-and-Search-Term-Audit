import json
import collections
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed

from google import genai
from . import cache_manager as cm


# -----------------------------
# SYSTEM PROMPT
# -----------------------------
BATCH_AUDIT_SYSTEM_PROMPT = """
Classify each term independently.

Return ONLY valid JSON:

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
- cls must be exactly one of the allowed values
- conf must be 0–1 float
- no extra keys
- no text outside JSON
"""


# -----------------------------
# PROCESS BATCH (NO WRAPPER)
# -----------------------------
def _process_batch(client, batch, profile_key, blueprint):
    payload = {
        "brand": profile_key.split("|")[0].strip(),
        "bp": blueprint,
        "terms": batch
    }

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=json.dumps(payload),
        config={
            "system_instruction": BATCH_AUDIT_SYSTEM_PROMPT,
            "response_mime_type": "application/json",
            "temperature": 0.1,
        },
    )

    raw = response.text.strip()

    data = json.loads(raw)

    if "term_data" not in data or not isinstance(data["term_data"], list):
        raise ValueError("Invalid schema from Gemini")

    return data


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
        raise KeyError("Missing 'search term' column")

    raw_terms = df["search term"].dropna().astype(str).str.strip().unique().tolist()

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

                for item in payload["term_data"]:
                    if not isinstance(item, dict):
                        continue

                    term = str(item.get("term", "")).strip()
                    cls = str(item.get("cls", "")).strip()
                    conf = float(item.get("conf", 0) or 0)

                    if not term:
                        continue

                    results.append({
                        "Search Term": term,
                        "cls": cls,
                        "Confidence Score": conf,
                        "Reasoning": item.get("why", "")
                    })

            except Exception:
                failed_batches.append(batch)

            if progress_bar_ui:
                progress_bar_ui.progress((i + 1) / len(batches))

    # -----------------------------
    # RETRY FAILED BATCHES
    # -----------------------------
    for batch in failed_batches:
        try:
            payload = _process_batch(client, batch, selected_profile_key, blueprint)

            for item in payload["term_data"]:
                results.append({
                    "Search Term": str(item.get("term", "")).strip(),
                    "cls": str(item.get("cls", "")).strip(),
                    "Confidence Score": float(item.get("conf", 0) or 0),
                    "Reasoning": item.get("why", "")
                })

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
    # SIMPLE CLASSIFICATION (NO FUZZY LOGIC)
    # -----------------------------
    relevant, irrelevant, review = [], [], []

    for item in results:
        cls = item.get("cls", "REVIEW")

        record = {
            "Search Term": item["Search Term"],
            "Reasoning": item["Reasoning"],
            "Confidence Score": item["Confidence Score"]
        }

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

    def is_covered(term):
        return any(r in tokenize(term) for r in roots)

    leftover = [t for t in raw_irrelevant if not is_covered(t)]

    negative_export = "\n".join(sorted(roots) + leftover)

    # -----------------------------
    # RETURN
    # -----------------------------
    return {
        "metrics": {
            "total_inputted": len(raw_terms),
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
