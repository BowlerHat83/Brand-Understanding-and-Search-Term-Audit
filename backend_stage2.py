import re
import json
import time
import streamlit as st
from google import genai
from google.genai import types
from typing import List

def classify_terms_batch(terms_batch: List[str], locked_rules: dict) -> List[dict]:
    """
    ⚡ HIGH-VOLUME ENGINE: Utilizes ultra-fast plain text CSV streaming.
    Completely immune to structural JSON parsing validation failures (Error E006).
    """
    api_key = st.secrets.get("GEMINI_API_KEY")
    client = genai.Client(api_key=api_key)
    
    # Format input array with clear index markers to ensure 1:1 mapping
    formatted_input = "\n".join([f"{idx}|{term}" for idx, term in enumerate(terms_batch)])
    
    prompt = f"""
    Evaluate these exact PPC search queries:
    {formatted_input}
    
    Against these absolute campaign match guidelines:
    - Allowed Brand Variants/Misspellings: {locked_rules.get('brand_variants', [])}
    - Competitor Target Brand Names (Red Flags): {locked_rules.get('competitors', [])}
    - Protected Core Offering Terms: {locked_rules.get('protected_terms', [])}
    - Clear Irrelevant Elements/Concepts: {locked_rules.get('irrelevant_terms', [])}
    """
    
    system_prompt = (
        "You are an elite, deterministic Google Ads keyword filtering machine.\n"
        "Process every single query inside the input list accurately.\n"
        "Classify each query into exactly one of these categories: 'relevant', 'irrelevant', or 'review'.\n\n"
        "CRITICAL OUTPUT FORMAT:\n"
        "Return your response ONLY as a plain text list using a pipe character (|) delimiter. "
        "Do not use markdown code blocks (no ```json or ```text). Do not include a header row. "
        "Format exactly like this:\n"
        "index|classification|confidence|micro_reason\n\n"
        "Rules:\n"
        "- index: must match the incoming integer index exactly\n"
        "- classification: must be exactly 'relevant', 'irrelevant', or 'review'\n"
        "- confidence: decimal score between 0.00 and 1.00\n"
        "- micro_reason: strictly 5 words or less detailing the logical rule match\n\n"
        "You must output exactly one line for every single item in the input list. Do not omit any row."
    )
    
    max_retries = 4
    initial_delay = 2.0
    
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=0.0
                )
            )
            
            raw_text = response.text.strip()
            parsed_results = []
            
            # Bulletproof custom plain text line-by-line parser
            lines = raw_text.split('\n')
            for line in lines:
                line = line.strip().replace('`', '')
                if not line or '|' not in line:
                    continue
                    
                parts = line.split('|')
                if len(parts) >= 3:
                    try:
                        idx_val = int(parts[0].strip())
                        classification = parts[1].strip().lower()
                        confidence = float(parts[2].strip())
                        reason = parts[3].strip() if len(parts) > 3 else "evaluated match context"
                        
                        # Guardrail standard categorization strings
                        if classification not in ["relevant", "irrelevant", "review"]:
                            classification = "review"
                            
                        parsed_results.append({
                            "search_term": terms_batch[idx_val] if idx_val < len(terms_batch) else parts[0],
                            "classification": classification,
                            "confidence": confidence,
                            "reason": reason[:40] # Keep reason character footprint safe
                        })
                    except:
                        continue # Skip malformed single lines safely instead of crashing the batch
            
            # Verification check: If the output completely lost rows, force a retry parameter
            if len(parsed_results) < (len(terms_batch) * 0.7):
                raise ValueError("Incomplete text matrix returned from API.")
                
            return parsed_results
            
        except Exception as e:
            err_str = str(e).lower()
            if "503" in err_str or "unavailable" in err_str or "429" in err_str or "incomplete" in err_str:
                if attempt < max_retries - 1:
                    time.sleep(initial_delay * (2 ** attempt))
                    continue  
            raise RuntimeError(f"Engine failure on parsing parameters: {str(e)}")

def extract_root_negatives(irrelevant_terms: List[str], saved_terms: List[str], protected_terms: List[str] = None) -> dict:
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
    return dict(sorted({k: v for k, v in word_counts.items() if v >= 2}.items(), key=lambda item: item[1], reverse=True))

def apply_ads_notation(term: str, is_exact: bool = False) -> str:
    cleaned = str(term).strip().lower()
    if not cleaned: 
        return ""
    if is_exact:
        return f"[{cleaned}]"
    return f'"{cleaned}"' if len(cleaned.split()) >= 2 else cleaned
