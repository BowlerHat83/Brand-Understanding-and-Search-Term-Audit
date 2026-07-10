import re
from collections import Counter
import google.generativeai as genai
import streamlit as st
import json
from typing import List
from pydantic import BaseModel, Field

# 1. Define the exact structural schema using Pydantic
class ClassifiedSearchTerm(BaseModel):
    search_term: str = Field(description="The exact search term from the input list.")
    classification: str = Field(description="Must be exactly 'relevant', 'irrelevant', or 'review'")
    confidence: float = Field(description="Confidence score between 0.00 and 1.00")
    reason: str = Field(description="Reasoning for classification, 5 words or less")

def classify_terms_batch(terms: list, brand_profile: dict) -> list:
    """
    Slices execution time by enforcing an explicit Pydantic response schema.
    This eliminates the AI's layout overhead without altering the rules core.
    """
    if "GEMINI_API_KEY" in st.secrets:
        genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    
    model = genai.GenerativeModel('gemini-2.5-flash')
    rules_context = json.dumps(brand_profile, indent=2)
    
    # Your exact original rules and defensive ideology completely untouched
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
    3. 'review' -> Use if you are even 1% uncertain, if it lacks a clear intent modifier, or contains mixed signals (e.g., educational context mixed with target terms). Uncertainty equals lack of proof for relevance.

    Active Brand Rules Context Baseline:
    {rules_context}
    
    Terms to classify:
    {json.dumps(terms)}
    
    CRITICAL SPEED RULE: Keep the 'reason' ultra-concise. Do not exceed 5 words under any circumstance.
    """
    
    try:
        # Enforce the strict schema response natively at the API tier
        response = model.generate_content(
            prompt,
            generation_config={
                "response_mime_type": "application/json",
                "response_schema": List[ClassifiedSearchTerm], # <-- Instructs Gemini's framework directly
                "temperature": 0.1
            }
        )
        
        # Clean markdown if present
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
        return [{"search_term": t, "classification": "review", "confidence": 0.5, "reason": f"Fallback: {str(e)[:15]}"} for t in terms]

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
