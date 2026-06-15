import re
import json
import time  # 🚀 Added for the backoff pause mechanism
import collections
import streamlit as st
from pydantic import BaseModel, Field
from typing import List, Literal
from google import genai
from google.genai import types

# 1. Define the strict data validation structure for Gemini's output
class SingleTermClassification(BaseModel):
    search_term: str = Field(description="The exact search term being evaluated from the input array.")
    classification: Literal["relevant", "irrelevant", "review"] = Field(description="Must pick exactly one category.")
    confidence: float = Field(description="Confidence decimal between 0.00 and 1.00.")
    reason: str = Field(description="Strictly 5 words or less explaining the logical match choice.")

# 2. Define the multi-row batch container array
class BatchClassificationResponse(BaseModel):
    results: List[SingleTermClassification] = Field(description="Array matching every single input query.")

def classify_terms_batch(terms_batch: List[str], locked_rules: dict) -> List[dict]:
    """
    Evaluates a batch group of search terms with built-in resilience.
    Uses exponential backoff to handle 503 errors gracefully without crashing.
    """
    api_key = st.secrets.get("GEMINI_API_KEY")
    client = genai.Client(api_key=api_key)
    
    prompt = f"""
    Evaluate the following array list of PPC search queries:
    {json.dumps(terms_batch)}
    
    Against these absolute campaign match guidelines:
    - Allowed Brand Variants/Misspellings: {locked_rules.get('brand_variants', [])}
    - Competitor Target Brand Names (Red Flags): {locked_rules.get('competitors', [])}
    - Protected Core Offering Terms: {locked_rules.get('protected_terms', [])}
    - Clear Irrelevant Elements/Concepts: {locked_rules.get('irrelevant_terms', [])}
    """
    
    system_prompt = (
        "You are an elite, deterministic Google Ads keyword filtering machine. "
        "Process every search term query inside the input array accurately against the guidelines. "
        "Classify as 'relevant', 'irrelevant', or 'review'. "
        "You must generate an evaluation line for EVERY single query in the input array. Do not miss any. "
        "Keep your reason values strictly below a 5-word micro-readout description."
    )
    
    # 🎯 START RESILIENT RETRY CONFIGURATION
    max_retries = 4
    initial_delay = 2.0  # Seconds to wait before the first retry
    
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    response_mime_type="application/json",
                    response_schema=BatchClassificationResponse,
                    temperature=0.0
                )
            )
            
            # Strip potential markdown blocks
            clean_text = response.text.strip()
            if clean_text.startswith("```"):
                clean_text = re.sub(r"^```json\s*|\s*```$", "", clean_text, flags=re.MULTILINE).strip()
                
            parsed_data = BatchClassificationResponse.model_validate_json(clean_text).model_dump()
            return parsed_data["results"]
            
        except Exception as e:
            err_str = str(e).lower()
            # If it's a server capacity or throttling issue, wait and retry
            if "503" in err_str or "unavailable" in err_str or "429" in err_str:
                if attempt < max_retries - 1:
                    # Double the delay each time (e.g., wait 2s, then 4s, then 8s)
                    sleep_time = initial_delay * (2 ** attempt)
                    time.sleep(sleep_time)
                    continue  # Jump to the next loop iteration to retry
            
            # If it's a different error or we've run out of retries, throw the error to the UI
            raise RuntimeError(f"Cloud Batch Matrix Engine failed on execution: {str(e)}")


def extract_root_negatives(irrelevant_terms: List[str], saved_terms: List[str], protected_terms: List[str] = None) -> dict:
    """ 
    Pure Python string compression math.
    Extracts root negatives ONLY if they appear across multiple irrelevant search terms (count >= 2).
    """
    word_counts = {}
    protected_tokens = set()
    
    for term in saved_terms:
        for word in re.findall(r'\b\w+\b', str(term).lower()):
            protected_tokens.add(word)
            
    if protected_terms:
        for term in protected_terms:
            for word in re.findall(r'\b\w+\b', str(term).lower()):
                protected_tokens.add(word)
                
    for term in irrelevant_terms:
        words_in_phrase = set(re.findall(r'\b\w+\b', str(term).lower()))
        for word in words_in_phrase:
            if word not in protected_tokens and not word.isdigit() and len(word) > 2:
                word_counts[word] = word_counts.get(word, 0) + 1
                
    root_negatives = {word: count for word, count in word_counts.items() if count >= 2}
    return dict(sorted(root_negatives.items(), key=lambda item: item[1], reverse=True))


def apply_ads_notation(term: str, is_exact: bool = False) -> str:
    """ 
    Correctly wraps strings into strict parameter formats for Google Ads.
    Safely handles phrase match vs exact match downgrades.
    """
    cleaned = str(term).strip().lower()
    if not cleaned: 
        return ""
        
    if is_exact:
        return f"[{cleaned}]"
    return cleaned if len(cleaned.split()) == 1 else f'"{cleaned}"'
