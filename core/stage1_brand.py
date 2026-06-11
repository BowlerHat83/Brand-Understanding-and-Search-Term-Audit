import json
import time
import random
import hashlib
from pathlib import Path

import streamlit as st
from google import genai
from google.genai import errors


# =========================================================
# CACHE
# =========================================================
CACHE_DIR = Path("cache")
CACHE_DIR.mkdir(exist_ok=True)


def _cache_key(brand, offering, landing):
    raw = f"{brand.strip().lower()}|{offering.strip().lower()}|{landing.strip().lower()}"
    return hashlib.md5(raw.encode()).hexdigest()


def _cache_path(key):
    return CACHE_DIR / f"{key}.json"


def list_cached_blueprints():
    try:
        return [f.stem for f in CACHE_DIR.glob("*.json")]
    except Exception:
        return []


def load_cached_blueprint(key: str):
    path = _cache_path(key)
    if not path.exists():
        return None

    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _save_cache(key, data):
    try:
        _cache_path(key).write_text(json.dumps(data, indent=2))
    except Exception:
        pass


# =========================================================
# GEMINI CLIENT (SAFE + LAZY)
# =========================================================
def _get_client():
    api_key = st.secrets.get("GEMINI_API_KEY")

    if not api_key:
        raise RuntimeError("Missing GEMINI_API_KEY in Streamlit secrets")

    return genai.Client(api_key=api_key)


# =========================================================
# SYSTEM PROMPT
# =========================================================
SYSTEM_PROMPT = """
You are a PPC strategist.

Return ONLY valid JSON:

{
  "brand_variants": [],
  "explicit_negative_triggers": [],
  "predicted_competitors": [],
  "strict_relevance_rule": ""
}

Rules:
- No markdown
- No explanation
- Max 12 items per list
- No empty strings
"""


# =========================================================
# MAIN FUNCTION (HARDENED)
# =========================================================
def generate_brand_profile(brand_name: str, core_offering: str, landing_page: str) -> dict:

    key = _cache_key(brand_name, core_offering, landing_page)

    # -----------------------------
    # CACHE HIT
    # -----------------------------
    cached = load_cached_blueprint(key)
    if cached:
        return cached

    client = _get_client()

    prompt = {
        "brand": brand_name,
        "offering": core_offering,
        "landing": landing_page
    }

    max_retries = 3

    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=json.dumps(prompt),
                config={
                    "system_instruction": SYSTEM_PROMPT,
                    "response_mime_type": "application/json",
                    "temperature": 0.2,
                },
            )

            data = json.loads(response.text)

            # -----------------------------
            # VALIDATION
            # -----------------------------
            required = [
                "brand_variants",
                "explicit_negative_triggers",
                "predicted_competitors",
                "strict_relevance_rule",
            ]

            for r in required:
                if r not in data:
                    raise ValueError(f"Missing key: {r}")

            _save_cache(key, data)
            return data

        except (json.JSONDecodeError, ValueError):
            # bad model output → retry fast
            continue

        except errors.APIError as e:
            code = getattr(e, "code", None)

            # IMPORTANT: NO LONG BACKOFF (prevents 10-min stalls)
            if code in [429, 503]:
                time.sleep(1.5)
                continue

            raise RuntimeError(f"Gemini API error: {e}")

        except Exception as e:
            raise RuntimeError(f"Unexpected error: {e}")

    # -----------------------------
    # FALLBACK (NEVER BLOCK UX)
    # -----------------------------
    return {
        "brand_variants": [brand_name],
        "explicit_negative_triggers": ["jobs", "free", "cheap"],
        "predicted_competitors": [],
        "strict_relevance_rule": f"Must relate to {core_offering}"
    }
