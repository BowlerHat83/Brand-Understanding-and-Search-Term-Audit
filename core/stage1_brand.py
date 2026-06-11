import json
import hashlib
from pathlib import Path

import streamlit as st
from google import genai


# =========================================================
# CACHE
# =========================================================
CACHE_DIR = Path("cache/stage1")
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _cache_key(company, offering):
    raw = f"{company.strip().lower()}|{offering.strip().lower()}"
    return hashlib.md5(raw.encode()).hexdigest()


def _cache_path(key):
    return CACHE_DIR / f"{key}.json"


def load_brand_truth(company, offering):
    path = _cache_path(_cache_key(company, offering))
    if path.exists():
        return json.loads(path.read_text())
    return None


def save_brand_truth(company, offering, data):
    path = _cache_path(_cache_key(company, offering))
    path.write_text(json.dumps(data, indent=2))


# =========================================================
# GEMINI CLIENT
# =========================================================
def _client():
    key = st.secrets.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("Missing GEMINI_API_KEY")
    return genai.Client(api_key=key)


# =========================================================
# SYSTEM PROMPT (DRAFT ONLY)
# =========================================================
SYSTEM_PROMPT = """
You are generating a PPC brand analysis DRAFT.

Return ONLY valid JSON:

{
  "company_name": "",
  "core_offering": "",
  "brand_variants": [],
  "explicit_junk_triggers": [],
  "direct_competitors": []
}

Rules:
- No explanation
- No markdown
- No extra keys
- Keep lists concise (max 12 items)
- This is a draft for human review
"""


# =========================================================
# GENERATE DRAFT
# =========================================================
def generate_brand_draft(company_name: str, core_offering: str, landing_page: str):

    client = _client()

    prompt = {
        "company_name": company_name,
        "core_offering": core_offering,
        "landing_page": landing_page
    }

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=json.dumps(prompt),
        config={
            "system_instruction": SYSTEM_PROMPT,
            "response_mime_type": "application/json",
            "temperature": 0.3,
        },
    )

    data = json.loads(response.text)

    # enforce structure
    data["company_name"] = company_name
    data["core_offering"] = core_offering

    return data
