import re
import json
import asyncio
from collections import Counter
import google.generativeai as genai
import streamlit as st

# Regulate concurrency to avoid 429 rate limit locks (3 parallel requests max)
API_SEMAPHORE = asyncio.Semaphore(3)

async def classify_terms_batch(terms: list, brand_profile: dict) -> list:
    """
    Asynchronous batch classification engine.
    Applies API retries and strict JSON formatting safeguards.
    """
    api_key = st.secrets.get("GEMINI_API_KEY") or st.secrets.get("default", {}).get("GEMINI_API_KEY")
    if api_key:
        genai.configure(api_key=api_key)
    
    # Updated to latest stable Flash model
    model = genai.GenerativeModel('gemini-1.5-flash')
    rules_context = json.dumps(brand_profile, indent=2)
    
    prompt = f"""
    You are a defensive Google Ads Negative Keyword Auditor.
    Categorize each search term using the following strict brand context rules:
    {rules_context}

    Terms to classify:
    {json.dumps(terms)}
    
    Respond ONLY with a valid JSON array of objects containing these keys:
    - "search_term": (string matching the input exactly)
    - "classification": ("relevant", "irrelevant", or "review")
    - "confidence": (float between 0.00 and 1.00)
    - "reason": (string, 5 words max if confidence < 0.80, otherwise empty string "")
    """
    
    async with API_SEMAPHORE:
        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                # Direct API call with forced timeout guard
                response = await asyncio.wait_for(
                    model.generate_content_async(
                        prompt,
                        generation_config={
                            "response_mime_type": "application/json",
                            "temperature": 0.1
                        }
                    ),
                    timeout=30.0
                )
                
                clean_text = response.text.strip()
                if clean_text.startswith("```"):
                    lines = clean_text.splitlines()
                    if lines[0].startswith("```"):
                        lines = lines[1:]
                    if lines and lines[-1].startswith("```"):
                        lines = lines[:-1]
                    clean_text = "\n".join(lines).strip()
                    
                return json.loads(clean_text)
                
            except Exception as e:
                if attempt < max_attempts - 1:
                    await asyncio.sleep(2.0 * (attempt + 1))
                    continue
                
                # Graceful fallback so the UI never hangs indefinitely
                return [{"search_term": t, "classification": "review", "confidence": 0.0, "reason": f"Timeout/Err: {str(e)[:30]}"} for t in terms]

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

def is_foreign_script(text: str) -> bool:
    return bool(re.search(r'[\u0E00-\u0E7F\u0400-\u04FF\u0600-\u06FF\u0590-\u05FF]', str(text)))
