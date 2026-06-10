import json
import time
import random
from typing import List, Dict

from google import genai
from google.genai import errors


# -----------------------------
# BATCHING
# -----------------------------
def chunk_list(items: List[str], chunk_size: int = 30):
    """
    Splits list into fixed-size batches.
    """
    for i in range(0, len(items), chunk_size):
        yield items[i:i + chunk_size]


# -----------------------------
# SYSTEM PROMPT (STRICT OUTPUT CONTRACT)
# -----------------------------
STAGE2_SYSTEM_PROMPT = """
You are a PPC search term classification engine.

You must classify each search term against a brand blueprint.

Return ONLY valid JSON in this format:

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
- Output MUST contain exactly one result per input term
- Preserve order exactly
- No missing or extra items
- confidence must be 0.0 to 1.0
- No markdown
- No extra keys
- Keep reasoning short (max 15 words per item)
"""


# -----------------------------
# GEMINI CALL (SINGLE BATCH)
# -----------------------------
def _classify_batch(client, batch: List[str], blueprint: dict) -> List[dict]:
    """
    Sends one batch to Gemini and returns parsed results.
    """

    user_prompt = {
        "blueprint": blueprint,
        "search_terms": batch
    }

    max_retries = 4

    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=json.dumps(user_prompt),
                config={
                    "system_instruction": STAGE2_SYSTEM_PROMPT,
                    "response_mime_type": "application/json",
                    "temperature": 0.2,
                },
            )

            data = json.loads(response.text)

            results = data.get("results", [])

            # -----------------------------
            # LINEAGE CHECK (CRITICAL)
            # -----------------------------
            if len(results) != len(batch):
                raise ValueError("Lineage mismatch: input != output length")

            # -----------------------------
            # VALIDATION SANITIZATION
            # -----------------------------
            cleaned = []
            for i, item in enumerate(results):
                cleaned.append({
                    "term": batch[i],
                    "classification": item.get("classification", "review"),
                    "confidence": float(item.get("confidence", 0.0)),
                    "reason": item.get("reason", "")[:100]
                })

            return cleaned

        except errors.APIError as e:
            code = getattr(e, "code", None)

            if code in [429, 503] and attempt < max_retries - 1:
                time.sleep((2 ** attempt) + random.uniform(0, 0.5))
                continue

            raise RuntimeError(f"Gemini API error ({code}): {e}")

        except (json.JSONDecodeError, ValueError):
            if attempt < max_retries - 1:
                time.sleep(0.5)
                continue

        except Exception as e:
            raise RuntimeError(f"Unexpected error: {e}")

    # -----------------------------
    # FALLBACK (NEVER BREAK PIPELINE)
    # -----------------------------
    return [
        {
            "term": t,
            "classification": "review",
            "confidence": 0.5,
            "reason": "fallback due to API failure"
        }
        for t in batch
    ]


# -----------------------------
# MAIN PIPELINE FUNCTION
# -----------------------------
def run_stage2_audit(
    search_terms: List[str],
    blueprint: dict,
    batch_size: int = 30
) -> List[dict]:
    """
    Full audit pipeline for search terms.
    """

    client = genai.Client()

    all_results = []

    batches = list(chunk_list(search_terms, batch_size))
    total_batches = len(batches)

    for idx, batch in enumerate(batches):

        batch_results = _classify_batch(client, batch, blueprint)
        all_results.extend(batch_results)

        # lightweight progress feedback (Streamlit friendly)
        print(f"Processed batch {idx + 1}/{total_batches}")

    return all_results
