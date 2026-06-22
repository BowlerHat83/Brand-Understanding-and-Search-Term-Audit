import json
import re
from collections import Counter
import streamlit as st
from google import genai
from google.genai import types

def classify_terms_batch(search_terms, brand_profile):
    """
    Evaluates a batch of search terms using the exact original logic setup.
    """
    
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
        # Secure the API Key from Streamlit Secrets
        api_key = st.secrets.get("GEMINI_API_KEY") or st.secrets.get("google", {}).get("api_key")
        
        if api_key:
            client = genai.Client(api_key=api_key)
        else:
            client = genai.Client()
            
        # CORRECT METHOD CALL: client.models.generate_content
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt_payload,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.7,
                response_mime_type="application/json"
            )
        )
        
        cleaned_response = response.text.strip().strip("`").replace("json\n", "")
        results = json.loads(cleaned_response)
        return results

    except Exception as e:
        # Keep the safety net intact but output the exact live error text for transparency
        fallback_results = []
        for term in search_terms:
            fallback_results.append({
                "search_term": term,
                "classification": "review",
                "confidence": 0.50,
                "reason": f"Live connection trace: {str(e)}"
            })
        return fallback_results


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
