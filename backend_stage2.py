import re
import json
import asyncio
from collections import Counter
import google.generativeai as genai
import streamlit as st

# Parallel call threshold
API_SEMAPHORE = asyncio.Semaphore(5)

async def classify_terms_batch(terms: list, brand_profile: dict) -> list:
    """
    Asynchronous classification engine using Gemini 2.5 Flash.
    Enforces strict structural JSON schemas for classification.
    """
    api_key = st.secrets.get("GEMINI_API_KEY") or st.secrets.get("default", {}).get("GEMINI_API_KEY")
    if api_key:
        genai.configure(api_key=api_key)
    
    # Restored working Gemini 2.5 Flash model
    model = genai.GenerativeModel('gemini-2.5-flash')
    rules_context = json.dumps(brand_profile, indent=2)
    
    prompt = f"""
    You are a defensive Google Ads Negative Keyword Auditor.
    Evaluate the following search terms against this brand profile context:
    {rules_context}

    CRITICAL CLASSIFICATION INSTRUCTIONS:
    - Return "relevant" if the query directly matches or shows clear intent to purchase core offerings.
    - Return "irrelevant" if the query matches competitors, excluded intent, or unrelated products.
    - Return "review" ONLY if there is genuine ambiguity. Do not dump clear terms into review.

    Terms to evaluate:
    {json.dumps(terms)}
    
    Respond ONLY with a raw JSON array of objects. Do not use markdown wrappers.
    Each object must contain:
    - "search_term": string (exact match from input)
    - "classification": string (strictly "relevant", "irrelevant", or "review")
    - "confidence": float (0.0 to 1.0)
    - "reason": string (5 words max if confidence < 0.80, else "")
    """
    
    async with API_SEMAPHORE:
        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                response = await model.generate_content_async(
                    prompt,
                    generation_config={
                        "response_mime_type": "application/json",
                        "temperature": 0.1
                    }
                )
                
                raw_text = response.text.strip()
                
                # Strip code fence blocks if present
                if raw_text.startswith("```"):
                    raw_text = re.sub(r"^```[a-zA-Z]*\n?", "", raw_text)
                    raw_text = re.sub(r"\n?```$", "", raw_text).strip()
                    
                parsed_json = json.loads(raw_text)
                if isinstance(parsed_json, list):
                    return parsed_json
                    
            except Exception as e:
                if attempt < max_attempts - 1:
                    await asyncio.sleep(1.5 * (attempt + 1))
                    continue
                
                return [{"search_term": t, "classification": "review", "confidence": 0.5, "reason": f"Parse Err: {str(e)[:25]}"} for t in terms]

def extract_root_negatives(irrelevant_phrases: list, saved_phrases: list, protected_list: list) -> dict:
    irr_words = []
    for phrase in irrelevant_phrases:
        irr_words.extend(re.findall(r'\b\w+\b', phrase.lower()))
        
    saved_words = set()
    for phrase in saved_phrases:
        saved_words.update(re.findall(r'\b\w+\b', phrase.lower()))
        
    for phrase in protected_list:
        saved_words.update(re.findall(r'\b\w+\b', phrase.lower()))
        
    counts = Counter([w for w in irr_words if w not in saved_words and len(w) > 2])
    return {word: count for word, count in counts.items() if count >= 2}

def apply_ads_notation(term: str, is_exact: bool = False) -> str:
    clean_term = str(term).strip().lower().strip("[]\"'")
    if is_exact:
        return f"[{clean_term}]"
    return f'"{clean_term}"'

def is_foreign_script(text: str) -> str:
    # Detect Non-Latin alphabets (Cyrillic, Han, Arabic, Thai, Hebrew)
    return bool(re.search(r'[\u0E00-\u0E7F\u0400-\u04FF\u0600-\u06FF\u0590-\u05FF\u4E00-\u9FFF]', str(text)))
