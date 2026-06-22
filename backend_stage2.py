import json
import re
from collections import Counter
import streamlit as st
# Modern, unified Google GenAI SDK imports
from google import genai
from google.genai import types

def classify_terms_batch(search_terms, brand_profile):
    """
    Evaluates a batch of search terms against the Stage 1 ruleset using the standard 
    relevancy logic from your original working deployment.
    """
    
    # Restored to your original default classification prompt layout
    system_instruction = (
        "You are an automated Google Ads helper tool. Classify the provided search terms into "
        "one of three buckets based on the brand profile:\n"
        "1. 'relevant' - if the term matches or is highly related to the core business offerings.\n"
        "2. 'irrelevant' - if the term is completely unrelated or matches known competitor names.\n"
        "3. 'review' - if you are unsure or the term is borderline.\n\n"
        "Return a valid JSON array of objects matching the input perfectly. Each object must contain "
        "EXACTLY these keys:\n"
        '{"search_term": "string", "classification": "relevant"|"irrelevant"|"review", "confidence": float, "reason": "string"}'
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
        # Standard Client Initialization using the modern SDK environment variable
        client = genai.Client()
        
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt_payload,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.7,  # Reverted back to standard fluid creativity settings
                response_mime_type="application/json"
            )
        )
        
        # Parse and return output
        cleaned_response = response.text.strip().strip("`").replace("json\n", "")
        results = json.loads(cleaned_response)
        return results

    except Exception as e:
        # Reverted back to the silent safety net matrix that prevents your script loop from breaking
        fallback_results = []
        for term in search_terms:
            fallback_results.append({
                "search_term": term,
                "classification": "review",
                "confidence": 0.50,
                "reason": f"System backend recovery path wrapper logging: {str(e)}"
            })
        return fallback_results


def extract_root_negatives(irrelevant_phrases, saved_phrases, protected_terms):
    """
    Identifies high-frequency root words from junk search terms that do not leak into 
    saved or protected target parameters.
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
