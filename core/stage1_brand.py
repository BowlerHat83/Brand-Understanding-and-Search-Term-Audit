import json
import time
import random
import hashlib
from pathlib import Path

from google import genai
from google.genai import errors


# -----------------------------
# CACHE CONFIG
# -----------------------------
CACHE_DIR = Path("cache")
CACHE_DIR.mkdir(exist_ok=True)


def _make_cache_key(brand_name: str, core_offering: str, landing_page: str) -> str:
    """
    Stable deterministic cache key (prevents duplicates).
    """
    raw = f"{brand_name.lower().strip()}|{core_offering.lower().strip()}|{landing_page.lower().strip()}"
    return hashlib.md5(raw.encode()).hexdigest()


def _cache_path(cache_key: str) -> Path:
    return CACHE_DIR / f"{cache_key}.json"


def _load_cache(cache_key: str):
    path = _cache_path(cache_key)

    if not path.exists():
        return None

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _save_cache(cache_key: str, data: dict):
    path = _cache_path(cache_key)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


# -----------------------------
# CACHE UI HELPERS
# -----------------------------
def list_cached_blueprints() -> list:
    """
    Returns all cached blueprint keys (file-based).
    """
    if not CACHE_DIR.exists():
        return []

    return [f.stem for f in CACHE_DIR.glob("*.json")]


def load_cached_blueprint(cache_key: str):
    """
    Loads a cached blueprint safely.
    """
    path = _cache_path(cache_key)

    if not path.exists():
        return None

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


# -----------------------------
# SYSTEM PROMPT
# -----------------------------
BRAND_BLUEPRINT_SYSTEM_PROMPT = """
You are an expert PPC Core Strategist.

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
- No extra keys
- Arrays: 1–12 items max
- No empty strings
- Keep outputs concise and realistic
"""


# -----------------------------
# MAIN FUNCTION
# -----------------------------
def generate_brand_profile(
    brand_name: str,
    core_offering: str,
    landing_page: str
) -> dict:
    """
    Generates or retrieves cached PPC brand blueprint using Gemini.
    """

    cache_key = _make_cache_key(brand_name, core_offering, landing_page)

    # -----------------------------
    # CACHE HIT
    # -----------------------------
    cached = _load_cache(cache_key)
    if cached:
        return cached

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

            data = json.loads(response.text)

            # -----------------------------
            # VALIDATION
            # -----------------------------
            required_keys = [
                "brand_variants",
                "explicit_negative_triggers",
                "predicted_competitors",
                "strict_relevance_rule",
            ]

            for key in required_keys:
                if key not in data:
                    raise ValueError(f"Missing key: {key}")

            # -----------------------------
            # SAVE CACHE
            # -----------------------------
            _save_cache(cache_key, data)

            return data

        except errors.APIError as e:
            code = getattr(e, "code", None)

            if code in [429, 503] and attempt < max_retries - 1:
                time.sleep((2 ** attempt) + random.uniform(0, 0.5))
                continue

            raise RuntimeError(f"Gemini API error ({code}): {e}")

        except (json.JSONDecodeError, ValueError):
            if attempt < max_retries - 1:
                continue

        except Exception as e:
            raise RuntimeError(f"Unexpected error: {e}")

    # -----------------------------
    # FALLBACK
    # -----------------------------
    fallback = {
        "brand_variants": [brand_name.strip()],
        "explicit_negative_triggers": [
            "jobs", "salary", "free", "diy", "download", "cheap"
        ],
        "predicted_competitors": [],
        "strict_relevance_rule": f"Must show clear intent related to {core_offering}"
    }

    _save_cache(cache_key, fallback)
    return fallback
