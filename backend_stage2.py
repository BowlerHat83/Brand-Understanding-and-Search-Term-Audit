import json
import re
from collections import Counter
import streamlit as st
from google import genai
from google.genai import types

def classify_terms_batch(search_terms, brand_profile):
    """
    Evaluates a batch of search terms using a defensive "guilty until proven innocent" ideology.
    Forces terms into 'irrelevant' or 'review' unless explicit commercial relevance is proven.
    """
    
    system_instruction = (
        "You are a highly defensive, ultra-conservative Google Ads Negative Keyword Auditor. "
        "Your primary directive is to protect ad spend by aggressively weeding out low-intent, "
        "ambiguous, or borderline search terms.\n\n"
        
        "CORE IDEOLOGY (GUILTY UNTIL PROVEN INNOCENT):\n"
        "- Every search term is considered IRRELEVANT or requires REVIEW by default.\n"
        "- A term is NEVER 'relevant' simply because it is vaguely related to the industry.\n"
        "- A term must actively PROVE its strict commercial relevance to be marked 'relevant'.\n\n"
        
        "CRITICAL RULES FOR CLASSIFICATION:\n\n"
        
        "1. THE 'RELEVANT' BARRIER (Strict Inclusion):\n"
        "   Classify a term as 'relevant' ONLY if it meets ALL of these conditions:\n"
        "   - It shows explicit commercial intent to buy, hire, or use the core offering.\n"
        "   - It contains words that directly align with the core target services/products.\n"
        "   - It contains absolutely zero educational, informational, or casual phrasing.\n\n"
        
        "2. THE 'IRRELEVANT' CRITERIA (Default Drop):\n"
        "   Classify a term as 'irrelevant' if it meets ANY of these conditions:\n"
        "   - It matches known competitor names or variations.\n"
        "   - It contains a word from the explicit exclusion list.\n"
        "   - It is completely outside the scope of the target business model.\n\n"
        
        "3. THE 'REVIEW' SAFETY NET (When in Doubt):\n"
        "   Classify a term as 'review' if:\n"
        "   - It is highly ambiguous, single-worded, or lacks clear user intent (e.g., just 'software' or 'tool').\n"
        "   - It is a mixed-signal term (contains a target keyword but looks like a research/educational query, e.g., 'how to use X', 'free guide for Y').\n"
        "   - You are even 1% uncertain. Treat uncertainty as a lack of proof for relevance.\n\n"
        
        "Return a valid JSON array of objects matching the input perfectly. Each object must contain "
        "EXACTLY these keys:\n"
        '{"search_term": "string", "classification": "relevant"|"irrelevant"|"review", "confidence": float, "reason": "string"}'
    )

    prompt_payload = f"""
    Brand Profile Info:
    - Core Target Terms (Must align to be relevant): {", ".join(brand_profile.get("protected_terms", []))}
    - Competitor Brand Target Red Flags: {", ".join(brand_profile.get("competitors", []))}
    - Explicit Exclusion Rules / Irrelevant Concepts: {", ".join(brand_profile.get("irrelevant_terms", []))}

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
                temperature=0.1,  # Lowered to 0.1 to make the model strictly analytical and non-creative
                response_mime_type="application/json"
            )
        )
        
        cleaned_response = response.text.strip().strip("`").replace("json\n", "")
        results = json.loads(cleaned_response)
        return results

    except Exception as e:
        # --- DEBUG MODE ACTIVE ---
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
