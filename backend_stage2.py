import re
from collections import Counter
import google.generativeai as genai
import streamlit as st
import json

def classify_terms_batch(terms: list, brand_profile: dict) -> list:
    """
    Ultra-high-speed batch classification engine.
    Uses conditional reasoning parameters and safe token capping to minimize output latency.
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
    - A term must actively PROVE its strict commercial intent and clear alignment with core offerings to be marked 'relevant'.

    CRITICAL CLASSIFICATION BOUNDARIES:
    1. 'relevant' -> Explicit intent to buy/hire core offerings. Zero educational/research signals.
    2. 'irrelevant' -> Competitor targets, explicit exclusion flags, or falls outside target offerings.
    3. 'review' -> Even 1% uncertain, lacks clear intent modifier, or contains mixed signals.

    Active Brand Rules Context Baseline:
    {rules_context}
    
    Terms to classify:
    {json.dumps(terms)}
    
    Respond STRICTLY with a valid JSON array of objects. Each object must have these exact keys:
    - "search_term": (string matching the input exactly)
    - "classification": (strictly choose one: "relevant", "irrelevant", or "review")
    - "confidence": (float between 0.00 and 1.00)
    - "reason": (string)

    ⚡ HIGH-SPEED CONDITION RULE FOR THE 'reason' KEY:
    - If confidence is 0.80 or higher, you MUST return an empty string "" for the reason.
    - Only if confidence is lower than 0.80, provide a reason of 5 words or less. Do not waste output tokens explaining obvious decisions.
    """
    
    try:
        # Calculate worst-case token ceiling for the batch + massive safety multiplier
        # 50-100 stripped objects need 700-1400 tokens max. 2000 is perfectly safe.
        max_tokens_guardrail = len(terms) * 25
        token_cap = max(1500, min(max_tokens_guardrail, 3000))

        response = model.generate_content(
            prompt,
            generation_config={
                "response_mime_type": "application/json",
                "temperature": 0.1,
                "max_output_tokens": token_cap
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
        return [{"search_term": t, "classification": "review", "confidence": 0.5, "reason": f"Err: {error_msg[:12]}"} for t in terms]

def extract_root_negatives(irrelevant_phrases: list, saved_phrases: list, protected_list: list) -> dict:
    """
    Optimized root extractor. Compiles recurring broad modifiers out of 
    the final negative phrases bucket behind the scenes.
    """
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
