import json
import re
from collections import Counter
# Assuming you are using the official google-genai SDK or google-generativeai. 
# Adjust this import based on your exact backend configuration (e.g., import google.generativeai as genai)
import google.generativeai as genai
import streamlit as st

def classify_terms_batch(search_terms, brand_profile):
    """
    Evaluates a batch of search terms against the Stage 1 ruleset.
    Enforces a strict standard of proof to prevent false-positive relevancy flags.
    """
    
    # Define hyper-strict system instructions to reset the AI's cognitive bias
    system_instruction = (
        "You are an elite, hyper-conservative Google Ads search query auditor. Your job is to classify raw search terms "
        "into 'relevant', 'irrelevant', or 'review' based STRICTLY on the provided Brand Profile parameters.\n\n"
        "CRITICAL CLASSIFICATION ENGINE RULES:\n"
        "1. RELEVANT (Strict commercial fit only):\n"
        "   - The search query must show clear, unambiguous commercial intent to purchase, source, or hire the EXACT core offering.\n"
        "   - It must NOT contain any elements from competitors, foreign scripts, or irrelevant concepts.\n"
        "   - If it is merely a partial match or an industry-adjacent category, do NOT mark it relevant.\n\n"
        "2. REVIEW (Ambiguous modifiers / Educational intent):\n"
        "   - Use 'review' for terms that contain a core offering keyword but are surrounded by transactional or informational modifiers "
        "     where user intent is muddy or split (e.g., 'X framework diagram', 'how does X software work', 'free version of X').\n"
        "   - When a query is borderline or you are in doubt, default to 'review'. Do not wave it through to relevant.\n\n"
        "3. IRRELEVANT (Budget drain blocklist):\n"
        "   - Mark 'irrelevant' if the search term contains any competitor brand names or completely unrelated industry concepts.\n"
        "   - Mark 'irrelevant' if it reflects zero intent to buy (e.g., job searches, salaries, logins, portals, wikipedia lookups, DIY projects).\n\n"
        "OUTPUT FORMAT REQUIREMENT:\n"
        "You must return a valid JSON array of objects matching the input array order perfectly. Do not include markdown blocks like ```json. "
        "Each object must contain EXACTLY these keys:\n"
        '{"search_term": "string", "classification": "relevant"|"irrelevant"|"review", "confidence": float_between_0_1, "reason": "string explanation"}'
    )

    # Format the prompt payload with the dynamic Stage 1 constraints
    prompt_payload = f"""
    [BRAND PROFILE ENVIRONMENT PARAMETERS]:
    - Allowed Brand Variants: {", ".join(brand_profile.get("brand_variants", []))}
    - Protected Core Offering Terms: {", ".join(brand_profile.get("protected_terms", []))}
    - Known Competitors (Red Flags): {", ".join(brand_profile.get("competitors", []))}
    - Explicitly Irrelevant Concepts: {", ".join(brand_profile.get("irrelevant_terms", []))}
    - Target Allowed Languages: {", ".join(brand_profile.get("allowed_languages", ["English"]))}

    [INPUT ARRAY TO EVALUATE]:
    {json.dumps(search_terms)}
    """

    try:
        # Configuration setup using your active project configurations
        # using the generic gemini-2.5-flash model as the standard batch processing engine
        model = genai.GenerativeModel(
            model_name="gemini-2.5-flash",
            generation_config={
                "response_mime_type": "application/json",
                "temperature": 0.1  # Set ultra-low to keep decisions logical and deterministic
            },
            system_instruction=system_instruction
        )
        
        response = model.generate_content(prompt_payload)
        cleaned_response = response.text.strip().strip("`").replace("json\n", "")
        results = json.loads(cleaned_response)
        return results

    except Exception as e:
        # Structural fallback matrix block if the API call encounters a connection or encoding drop
        fallback_results = []
        for term in search_terms:
            fallback_results.append({
                "search_term": term,
                "classification": "review",
                "confidence": 0.00,
                "reason": f"System backend processing exception fallback routing: {str(e)}"
            })
        return fallback_results


def extract_root_negatives(irrelevant_phrases, saved_phrases, protected_terms):
    """
    Identifies high-frequency root words from junk search terms that do not leak into 
    saved or protected target parameters.
    """
    # Clean and tokenize protected phrases to prevent catastrophic brand damage
    protected_tokens = set()
    for phrase in (saved_phrases + protected_terms):
        words = re.findall(r'\b\w+\b', str(phrase).lower())
        protected_tokens.update(words)

    # Count word frequencies inside confirmed irrelevant queries
    junk_word_counter = Counter()
    for phrase in irrelevant_phrases:
        words = re.findall(r'\b\w+\b', str(phrase).lower())
        # Strip simple numbers and ultra-short connector filler terms
        clean_words = [w for w in words if len(w) > 2 and not w.isdigit()]
        junk_word_counter.update(clean_words)

    # Filter out anything matching your safety shield token list
    extracted_roots = {}
    for word, count in junk_word_counter.items():
        if word not in protected_tokens and count >= 2:  # Must appear at least twice to qualify as a trend
            extracted_roots[word] = count

    # Sort root words descending by their frequency volume weight
    return dict(sorted(extracted_roots.items(), key=lambda item: item[1], reverse=True))


def apply_ads_notation(keyword, is_exact=False):
    """
    Transforms raw text phrases into valid Google Ads Keyword Syntax styles.
    """
    clean_keyword = str(keyword).strip().lower()
    
    # Strip existing syntax wrappers if present to prevent double notation errors
    clean_keyword = clean_keyword.strip("[]\"'")
    
    if is_exact:
        return f"[{clean_keyword}]"
    else:
        # Defaults to Phrase Match formatting which maps cleanly to root-exclusion lists
        return f'"{clean_keyword}"'
