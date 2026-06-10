import re
import json
import time
import random
import collections
import pandas as pd
import os

from concurrent.futures import ThreadPoolExecutor, as_completed

from google import genai
from google.genai import errors
from google.genai.types import GenerateContentConfig
from .gemini_utils import gemini_json
from . import cache_manager as cm


BATCH_AUDIT_SYSTEM_PROMPT = (
    "You are a conservative PPC Auditing Engine.\n\n"
    "Classify each term independently:\n"
    "- RELEVANT_BRAND\n"
    "- RELEVANT_GENERIC\n"
    "- IRRELEVANT\n"
    "- REVIEW_QUEUE\n\n"
    "Return strict JSON only.\n"
)


# -----------------------------
# GEMINI WRAPPER (FAST + SAFE)
# -----------------------------
def _call_gemini(client, prompt, retries=3):
    for attempt in range(retries):
        try:
            return client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=GenerateContentConfig(
                    system_instruction=BATCH_AUDIT_SYSTEM_PROMPT,
                    response_mime_type="application/json",
                    temperature=0.1,
                ),
            )

        except errors.APIError as e:
            code = getattr(e, "code", None) or 0
            msg = str(e)

            if code in [429, 503] and attempt < retries - 1:
                time.sleep(1.5 + random.uniform(0, 0.8))
                continue

            raise RuntimeError(f"Gemini error ({code}): {msg}")

    raise RuntimeError("Gemini failed after retries")


# -----------------------------
# BATCH PROCESSOR
# -----------------------------
def _process_batch(client, batch, profile_key, blueprint):
    prompt = {
        "brand": profile_key.split("|")[0].strip(),
        "blueprint": blueprint,
        "search_terms": batch,
    }

    response = _call_gemini(client, json.dumps(prompt))

    try:
        return json.loads(response.text)
    except json.JSONDecodeError:
        return {"term_data": []}


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
    # OPTIMIZED BATCH SIZE
    # -----------------------------
    BATCH_SIZE = 20

    batches = [
        raw_terms[i:i + BATCH_SIZE]
        for i in range(0, len(raw_terms), BATCH_SIZE)
    ]

    client = genai.Client()

    results = []

    # -----------------------------
    # PARALLEL EXECUTION (KEY SPEED WIN)
    # -----------------------------
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(_process_batch, client, batch, selected_profile_key, blueprint): batch
            for batch in batches
        }

        for i, future in enumerate(as_completed(futures)):
            if progress_bar_ui:
                progress_bar_ui.progress((i + 1) / len(batches))

            try:
                payload = future.result()
                results.extend(payload.get("term_data", []))
            except Exception:
                continue

    # -----------------------------
    # CLASSIFICATION (UNCHANGED LOGIC)
    # -----------------------------
    relevant, irrelevant, review = [], [], []

    for item in results:
        term = str(item.get("term", "")).strip()
        cls = item.get("classification", "REVIEW_QUEUE")
        conf = float(item.get("confidence", 0) or 0)

        record = {
            "Search Term": term,
            "Reasoning": item.get("reasoning", ""),
            "Confidence Score": conf,
        }

        if conf < 0.7:
            review.append(record)
        elif cls in ["RELEVANT_BRAND", "RELEVANT_GENERIC"]:
            relevant.append(record)
        elif cls == "IRRELEVANT":
            irrelevant.append(record)
        else:
            review.append(record)

    # -----------------------------
    # ROOT LOGIC (UNCHANGED)
    # -----------------------------
    raw_irrelevant = [x["Search Term"] for x in irrelevant]
    safe_terms = set(x["Search Term"].lower().strip() for x in (relevant + review))

    def stem(w):
        w = w.lower()
        if w.endswith("ies"):
            return w[:-3] + "i"
        if w.endswith("es"):
            return w[:-2]
        if w.endswith("s") and len(w) > 3:
            return w[:-1]
        return w

    protected = set(re.findall(r"\b\w+\b", selected_profile_key.lower()))
    protected_stems = {stem(x) for x in protected}

    safe_stems = {stem(w) for t in safe_terms for w in re.findall(r"\b\w+\b", t)}

    words = []
    for t in raw_irrelevant:
        words.extend(re.findall(r"\b\w+\b", t.lower()))

    freq = collections.Counter(words)
    candidates = [w for w, c in freq.items() if c > 1 and len(w) > 2]

    roots = []

    for r in candidates:
        rs = stem(r)
        if rs in protected_stems or rs in safe_stems:
            continue
        roots.append(r)

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
        },
        "review_queue_data": [x["Search Term"] for x in review],
        "copy_paste_notation": "\n".join(roots),
        "raw_classified_records": {
            "relevant": relevant,
            "review": review,
            "irrelevant": irrelevant,
            "roots_summary": [{"Isolated Root Word": r, "Frequency Count": freq[r]} for r in roots],
        }
    }
