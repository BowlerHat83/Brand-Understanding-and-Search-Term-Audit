import re
import json
import collections
import pandas as pd
import os
import time
import random

from google import genai
from google.genai import errors
from google.genai.types import GenerateContentConfig
from . import cache_manager as cm

BATCH_AUDIT_SYSTEM_PROMPT = (
    "You are a conservative, line-by-line PPC Auditing Engine. Your goal is to review a "
    "micro-batch of search terms with absolute precision against a brand blueprint.\n\n"
    "CRITICAL ACCURACY RULES:\n"
    "1. Evaluate each term completely independent of the terms around it.\n"
    "2. For each term, determine its classification:\n"
    "   - 'RELEVANT_BRAND': Contains a protected client brand name variation.\n"
    "   - 'RELEVANT_GENERIC': Aligns perfectly with the commercial intent of the Core Offering.\n"
    "   - 'IRRELEVANT': Mentions a competitor, or indicates wrong intent (DIY, jobs, info, blogs).\n"
    "   - 'REVIEW_QUEUE': Only use this if the term is completely ambiguous or tracking data.\n"
    "3. Calculate an internal confidence score between 0.0 and 1.0.\n"
    "4. Output MUST be valid JSON.\n\n"
    "Output format:\n"
    "{\n"
    '  "term_data": [\n'
    "      {\n"
    '        "term": "example",\n'
    '        "classification": "IRRELEVANT",\n'
    '        "confidence": 0.95,\n'
    '        "reasoning": "Contains DIY intent."\n'
    "      }\n"
    "  ]\n"
    "}"
)

def chunk_list(lst: list, n: int):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]

def clean_json_response(raw_text: str):
    raw_text = raw_text.strip()
    if raw_text.startswith("```json"):
        raw_text = raw_text.replace("```json", "").replace("```", "").strip()
    return raw_text

def run_search_terms_audit(csv_file, selected_profile_key: str, progress_bar_ui=None, status_text_ui=None) -> dict:
    cached_profile = cm.get_profile_by_name(selected_profile_key)
    if not cached_profile:
        raise ValueError(f"Profile cache '{selected_profile_key}' could not be located.")

    blueprint = cached_profile["blueprint"]

    try:
        df = pd.read_csv(csv_file)
    except Exception as e:
        raise RuntimeError(f"ERR_CSV_READ_FAILURE: Failed reading uploaded CSV.\n{str(e)}")

    df.columns = [col.lower().strip() for col in df.columns]
    if "search term" not in df.columns:
        raise KeyError("ERR_MISSING_COLUMN: Could not find required 'Search term' column.")

    raw_terms = df["search term"].dropna().astype(str).str.strip().unique().tolist()
    total_inputted_count = len(raw_terms)

    list_relevant, list_irrelevant, list_review = [], [], []

    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("ERR_MISSING_API_KEY: GOOGLE_API_KEY environment variable not found.")

    client = genai.Client(api_key=api_key)
    micro_batches = list(chunk_list(raw_terms, 30))
    total_batches = len(micro_batches)

    for idx, batch in enumerate(micro_batches):
        if progress_bar_ui and status_text_ui:
            progress_percent = (idx) / total_batches
            progress_bar_ui.progress(progress_percent)
            status_text_ui.text(f"Processing batch {idx + 1} of {total_batches}...")

        user_prompt = f"""
Brand Blueprint Context:
- Brand Name: {selected_profile_key.split('|')[0].strip()}
- Protected Brand Variants: {", ".join(blueprint["brand_variants"])}
- Core Offering Boundary: {blueprint["strict_relevance_rule"]}
- Explicit Junk Targets: {", ".join(blueprint["explicit_negative_triggers"])}

Search Terms:
{json.dumps(batch)}
"""
        MAX_RETRIES = 5
        response = None

        for attempt in range(MAX_RETRIES):
            try:
                response = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=user_prompt,
                    config=GenerateContentConfig(
                        system_instruction=BATCH_AUDIT_SYSTEM_PROMPT,
                        response_mime_type="application/json",
                        temperature=0.1,
                    ),
                )
                break
            except errors.APIError as api_err:
                err_code = getattr(api_err, "code", None) or "UNKNOWN"
                err_message = getattr(api_err, "message", str(api_err))

                if err_code in [429, 500, 503] or "429" in err_message or "503" in err_message:
                    if attempt < MAX_RETRIES - 1:
                        sleep_time = (2 ** attempt) + random.uniform(0.5, 1.5)
                        if status_text_ui:
                            status_text_ui.text(f"Rate limit / Traffic hiccup ({err_code}). Retrying in {sleep_time:.1f}s...")
                        time.sleep(sleep_time)
                        continue
                    else:
                        raise RuntimeError(f"ERR_GEMINI_QUOTA_EXCEEDED: Exhausted total connections ({MAX_RETRIES}) at batch {idx + 1}.")
                else:
                    raise RuntimeError(f"ERR_GEMINI_
