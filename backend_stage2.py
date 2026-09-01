import re
import json
import asyncio
from collections import Counter
import google.generativeai as genai
import streamlit as st

# Global rate-limiting gatekeeper (Allows max 5 concurrent API calls)
API_SEMAPHORE = asyncio.Semaphore(5)

async def classify_terms_batch(terms: list, brand_profile: dict) -> list:
    """
    Native Asynchronous batch classification engine.
    Regulated via an internal asyncio.Semaphore to completely eliminate 429 TooManyRequests loops
    while maintaining peak concurrent parallel processing speed.
    """
    if "GEMINI_API_KEY" in st.secrets:
        genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    
    model = genai.GenerativeModel('gemini-2.5-flash')
    rules_context = json.dumps(brand_profile, indent=2)
    
    prompt = f"""
    You are a highly defensive, ultra-conservative Google Ads Negative Keyword Auditor.
    Your primary directive is to protect ad spend by aggressively weeding out low-intent, ambiguous, or borderline search terms.

    CORE AUDITING IDEOLOGY (GUILTY UNTIL PROVEN INNOCENT):
    - Every search term is considered IRRELEVANT or requires REVIEW by default.
    - A term is NEVER 'relevant' simply because it is vaguely or tangentially related to the industry.
    - A term must actively PROVE its strict commercial intent and clear alignment with core offerings to be marked 'relevant'.

    CRITICAL CLASSIFICATION BOUNDARIES:
    1. 'relevant' -> Use ONLY if the term shows explicit intent to buy, hire, or use core offerings, AND it contains zero educational, research, or casual intent signals.
    2. 'irrelevant' -> Use if it matches competitor targets, explicit exclusion flags, or falls completely outside target offerings.
    3. 'review' -> Use if you are even 1% uncertain, if it lacks a clear intent modifier, or contains mixed signals.

    Active Brand Rules Context Baseline:
    {rules_context}
    
    Terms to classify:
    {json.dumps(terms)}
    
    Respond STRICTLY with a valid JSON array of objects. Each object must have these exact keys:
    - "search_term": (string matching the input exactly)
    - "classification": (strictly choose one: "relevant", "irrelevant", or "review")
    - "confidence": (float between 0.00 and 1.00)
    - "reason": (string)
    
    CRITICAL SPEED RULE FOR THE 'reason' VALUE:
    - If confidence is 0.80 or higher, you MUST set "reason": "" (an empty string). Do not write text for obvious classifications.
    - Only if confidence is LESS than 0.80, provide a short explanation of 5 words or less.
    """
    
    async with API_SEMAPHORE:
        max_attempts = 4
        for attempt in range(max_attempts):
            try:
                response = await model.generate_content_async(
                    prompt,
                    generation_config={
                        "response_mime_type": "application/json",
                        "temperature": 0.1
                    }
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
                error_msg = str(e)
                if "503" in error_msg or "429" in error_msg or "Quota" in error_msg or "Unavailable" in error_msg:
                    if attempt < max_attempts - 1:
                        await asyncio.sleep(2.0 * (attempt + 1))
                        continue
                
                return [{"search_term": t, "classification": "review", "confidence": 0.5, "reason": f"Err: {repr(e)[:40]}"} for t in terms]
        
        return [{"search_term": t, "classification": "review", "confidence": 0.5, "reason": "Err: Server Capacity Exceeded"} for t in terms]

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
    clean_term = term.strip().lower().strip("[]\"'")
    if is_exact:
        return f"[{clean_term}]"
    else:
        return f'"{clean_term}"'

def is_foreign_script(text: str) -> bool:
    return bool(re.search(r'[\u0E00-\u0E7F\u0400-\u04FF\u0600-\u06FF\u0590-\u05FF]', text))
