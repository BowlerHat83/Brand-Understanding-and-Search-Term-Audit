import json
import re
from collections import Counter
from typing import List, Literal
from pydantic import BaseModel, Field
import streamlit as st
from google import genai
from google.genai import types

# --- FORCE STRUCTURAL SCHEMA VALIDATION AT CORES ---
class KeywordClassification(BaseModel):
    search_term: str = Field(description="The exact raw search term provided in the input batch.")
    classification: Literal["relevant", "irrelevant", "review"] = Field(description="Strict classification value choice.")
    confidence: float = Field(description="Confidence rating between 0.0 and 1.0.")
    reason: str = Field(description="Clear, concise operational reasoning for this bucket placement.")

class BatchClassificationResponse(BaseModel):
    results: List[KeywordClassification]


def classify_terms_batch(search_terms, brand_profile):
    """
    Evaluates a batch of search terms using structural schemas to prevent 503/JSON parsing failures.
    """
    
    system_instruction = (
        "You are an automated Google Ads helper tool. Classify the provided search terms into "
        "one of three buckets based on the brand profile:\n"
        "1. 'relevant' - if the term matches or is highly related to the core business offerings.\n"
        "2. 'irrelevant' - if the term is completely unrelated or matches known competitor names.\n"
        "3. 'review' - if you are unsure or the term is borderline.\n\n"
        "You must return data strictly conforming to the requested schema layout structure."
    )

    prompt_payload = f"""
    Brand Profile Info:
    - Core Terms: {", ".join(brand_profile.get("protected_terms", []))}
    - Competitors: {", ".join(brand_profile.get("competitors", []))}
    - Exclusions: {", ".join(brand_profile.get("irrelevant_terms", []))}

    Terms to evaluate:
    {json.dumps(search_terms)}
    """

    try:
        # Pull API key from Streamlit's native secrets environmental wrapper
        api_key = st.secrets.get("GEMINI_API_KEY") or st.secrets.get("google", {}).get("api_key")
        
        if api_key:
            client = genai.Client(api_key=api_key)
        else:
            client = genai.Client()
            
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt_payload,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.1,  # Rigid, analytical configuration posture
                response_mime_type="application/json",
                response_schema=BatchClassificationResponse,  # Direct structural enforcement link
            )
        )
        
        # Parse output safely using the structural schema validation layer
        raw_text = response.text.strip()
        parsed_response = json.loads(raw_text)
        
        # Extract the results array to match what app.py expects natively
        if "results" in parsed_response:
            return parsed_response["results"]
        return parsed_response

    except Exception as e:
        # Forcibly crash the application and print the exact system exception error trace to the UI
        raise e


def extract_root_negatives(irrelevant_phrases, saved_phrases, protected_terms):
    """
    Identifies high-frequency root words from junk search terms.
    """
    protected_tokens = set()
    for phrase in (saved_phrases + protected_terms):
        words = re.findall(r'\b\w+\b', str(phrase).lower())
        protected_tokens.update(words)

    junk_word_counter = Counter()
    for phrase in irrelevant_phrases:
        words = re.findall(r'\b\w+\b', str(phrase).lower())
        clean_words = [w for w in words if len(w) > 2 and not w.isdigit()]
        junk_word_counter.update(clean_words)

    extracted_roots = {}
    for word, count in junk_word_counter.items():
        if word not in protected_tokens and count >= 2:
            extracted_roots[word] = count

    return dict(sorted(extracted_roots.items(), key=lambda item: item[1], reverse=True))


def apply_ads_notation(keyword, is_exact=False):
    """
    Transforms raw text phrases into valid Google Ads Keyword Syntax styles.
    """
    clean_keyword = str(keyword).strip().lower().strip("[]\"'")
    if is_exact:
        return f"[{clean_keyword}]"
    else:
        return f'"{clean_keyword}"'
