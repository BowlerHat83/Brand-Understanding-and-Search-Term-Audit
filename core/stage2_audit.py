import json
import time
import random
from typing import List

import streamlit as st
from google import genai
from google.genai import errors


# =========================================================
# BATCHING
# =========================================================
def chunk_list(items: List[str], size: int = 30):
    for i in range(0, len(items), size):
        yield items[i:i + size]


# =========================================================
# SYSTEM PROMPT
# =========================================================
SYSTEM_PROMPT = """
You are a PPC search term classifier.

Return ONLY JSON:

{
  "results": [
    {
      "term": "",
      "classification": "relevant | irrelevant | review",
      "confidence": 0.0,
      "reason": ""
    }
  ]
}

Rules:
- One result per input term
- Preserve order exactly
- confidence 0–1
- no extra keys
"""


# =========================================================
# CLIENT
# =========================================================
def _get_client():
    api_key = st.secrets.get("GEMINI_API_KEY")

    if not api_key:
        raise RuntimeError("Missing GEMINI_API_KEY in secrets")

    return genai.Client(api_key=api_key)


# =========================================================
# SINGLE BATCH (HARDENED)
# =========================================================
def _classify_batch(client, batch, blueprint):
    payload = {
        "blueprint": blueprint,
        "search_terms": batch
    }

    max_retries = 2  # small + fast fail

    for attempt in range(max_retries):
        try:
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

            # -----------------------------
            # SAFE LENGTH HANDLING (NO CRASH)
            # -----------------------------
            if not isinstance(results, list):
                raise ValueError("Invalid results format")

            cleaned = []

            for i, term in enumerate(batch):
                item = results[i] if i < len(results) else {}

                cleaned.append({
                    "term": term,
                    "classification": item.get("classification", "review"),
                    "confidence": float(item.get("confidence", 0.0) or 0.0),
                    "reason": (item.get("reason", "") or "")[:120]
                })

            return cleaned

        except (json.JSONDecodeError, ValueError):
            # bad output → retry once quickly
            continue

        except errors.APIError as e:
            code = getattr(e, "code", None)

            # NO LONG BACKOFF (prevents multi-minute stalls)
            if code in [429, 503]:
                time.sleep(1.0)
                continue

            return _fallback_batch(batch)

        except Exception:
            return _fallback_batch(batch)

    return _fallback_batch(batch)


# =========================================================
# FALLBACK (NEVER FAIL PIPELINE)
# =========================================================
def _fallback_batch(batch):
    return [
        {
            "term": t,
            "classification": "review",
            "confidence": 0.5,
            "reason": "fallback"
        }
        for t in batch
    ]


# =========================================================
# MAIN PIPELINE
# =========================================================
def run_stage2_audit(search_terms, blueprint, batch_size=30, progress_hook=None):

    client = _get_client()

    results = []
    batches = list(chunk_list(search_terms, batch_size))

    total = len(batches)

    for i, batch in enumerate(batches, start=1):

        batch_results = _classify_batch(client, batch, blueprint)
        results.extend(batch_results)

        # -----------------------------
        # UI PROGRESS SAFE UPDATE
        # -----------------------------
        if progress_hook:
            try:
                progress_hook(i, total)
            except Exception:
                pass

        # small throttle (prevents API spikes, not stalls)
        time.sleep(0.1)

    return results
