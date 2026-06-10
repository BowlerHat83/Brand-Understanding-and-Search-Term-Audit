import json
import time
import random
from google import genai
from google.genai import errors


# -----------------------------
# SYSTEM PROMPT
# -----------------------------
BRAND_BLUEPRINT_SYSTEM_PROMPT = """
You are an expert PPC Core Strategist.

Your task is to create a strict semantic blueprint for search term filtering.

Return ONLY valid JSON with exactly these keys:

{
  "brand_variants": [],
  "explicit_negative_triggers": [],
  "predicted_competitors": [],
  "strict_relevance_rule": ""
}

Rules:
- No markdown
- No explanation
- No extra keys
- Keep outputs concise and realistic
"""


# -----------------------------
# MAIN GENERATOR
# -----------------------------
def generate_brand_profile(brand_name: str, core_offering: str, landing_page: str) -> dict:
    """
    Generates a PPC semantic blueprint using Gemini with safe retry logic.
    """

    client = genai.Client()

    user_prompt = f"""
Brand: {brand_name}
Core Offering: {core_offering}
Landing Page: {landing_page}

Return strict JSON blueprint.
"""

    max_retries = 5

    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=user_prompt,
                config={
                    "system_instruction": BRAND_BLUEPRINT_SYSTEM_PROMPT,
                    "response_mime_type": "application/json",
                    "temperature": 0.2,
                },
            )

            return json.loads(response.text)

        except errors.APIError as e:
            code = getattr(e, "code", None)

            if code in [429, 503] and attempt < max_retries - 1:
                time.sleep((2 ** attempt) + random.uniform(0, 0.5))
                continue

            raise RuntimeError(f"Gemini API error ({code}): {e}")

        except json.JSONDecodeError:
            # retry once before fallback
            if attempt < max_retries - 1:
                continue

            break

        except Exception as e:
            raise RuntimeError(f"Unexpected error: {e}")

    # -----------------------------
    # SAFE FALLBACK (prevents pipeline break)
    # -----------------------------
    return {
        "brand_variants": [brand_name.strip()],
        "explicit_negative_triggers": [
            "jobs", "salary", "free", "diy", "download", "cheap"
        ],
        "predicted_competitors": [],
        "strict_relevance_rule": (
            f"Must show clear intent related to {core_offering}"
        )
    }
