import re
import json
import collections
import pandas as pd
from openai import OpenAI
import cache_manager as cm

# --- SYSTEM PROMPT CONSTANTS WITH ACCURACY SAFEGUARDS ---
BATCH_AUDIT_SYSTEM_PROMPT = (
    "You are a conservative, line-by-line PPC Auditing Engine. Your goal is to review a "
    "micro-batch of search terms with absolute precision against a brand blueprint.\n\n"
    "CRITICAL ACCURACY RULES:\n"
    "1. Evaluate each term completely independent of the terms around it.\n"
    "2. For each term, determine its classification:\n"
    "   - 'RELEVANT_BRAND': Contains a protected client brand name variation.\n"
    "   - 'RELEVANT_GENERIC': Aligns perfectly with the commercial intent of the Core Offering.\n"
    "   - 'IRRELEVANT': Mentions a competitor, or indicates wrong intent (DIY, jobs, info, blogs).\n"
    "   - 'REVIEW_QUEUE': Only use this if the term is completely ambiguous, a random tracking ID, or impossible to determine.\n"
    "3. Calculate an internal confidence score between 0.0 and 1.0. If your score for 'IRRELEVANT' or 'RELEVANT' is below 0.7, route the term to 'REVIEW_QUEUE'.\n"
    "4. To eliminate context laziness, you must write your analysis/reasoning FIRST inside the JSON object before selecting the decision.\n\n"
    "Output MUST be a strict JSON object containing a top-level key 'term_data' mapping to an array of objects. "
    "Do not include markdown code blocks or backticks."
)

def chunk_list(lst: list, n: int):
    """Yield successive n-sized chunks from a list."""
    for i in range(0, len(lst), n):
        yield lst[i:i + n]

def run_search_terms_audit(csv_file_path: str, selected_profile_key: str) -> dict:
    """
    Executes the Tier-2 Data Audit Pipeline. Processes Google Ads reports via 
    high-accuracy AI micro-batching, reconciles records, and safely builds root negatives.
    """
    # 1. Fetch our Absolute Truth blueprint from our Stage 1 cache
    cached_profile = cm.get_profile_by_name(selected_profile_key)
    if not cached_profile:
        raise ValueError(f"Profile cache '{selected_profile_key}' could not be located.")
        
    blueprint = cached_profile["blueprint"]
    
    # 2. Read and parse the inputted Google Ads CSV report
    df = pd.read_csv(csv_file_path)
    
    # Normalize headers to handle variable Google Ads layout exports safely
    df.columns = [col.lower().strip() for col in df.columns]
    if "search term" not in df.columns:
        raise KeyError("Could not find required 'Search term' column in the uploaded CSV.")
        
    # Extract unique, clean terms to prevent auditing duplicate strings
    raw_terms = df["search term"].dropna().astype(str).str.strip().unique().tolist()
    total_inputted_count = len(raw_terms)
    
    # 3. Establish Core Classification Storage Buckets
    list_relevant = []
    list_irrelevant = []
    list_review = []
    
    client = OpenAI()
    
    # 4. High-Accuracy Micro-Batching Loop (Slices text into blocks of 30)
    micro_batches = list(chunk_list(raw_terms, 30))
    
    for batch in micro_batches:
        user_prompt = f"""
        **Brand Blueprint Context:**
        - Brand Name: {selected_profile_key.split('|')[0].strip()}
        - Protected Brand Variants: {", ".join(blueprint["brand_variants"])}
        - Core Offering Boundary: {blueprint["strict_relevance_rule"]}
        - Explicit Junk Targets: {", ".join(blueprint["explicit_negative_triggers"])}
        
        **Micro-Batch to Audit (Process each line independently):**
        {json.dumps(batch)}
        
        Return a JSON object with this exact format:
        {{
            "term_data": [
                {{"term": "example query", "reasoning": "why it matches or fails blueprint", "classification": "IRRELEVANT", "confidence": 0.95}}
            ]
        }}
        """
        
        try:
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": BATCH_AUDIT_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.1 # Absolute minimum creativity for predictable extraction math
            )
            
            # Extract array data back out of the response payload
            payload = json.loads(response.choices[0].message.content)
            records = payload.get("term_data", [])
            
            # Route items to their proper storage tables based on rules and thresholds
            for item in records:
                term_string = item.get("term", "").strip()
                classification = item.get("classification", "REVIEW_QUEUE")
                confidence = float(item.get("confidence", 0.0))
                
                # Security Override: Low confidence pushes items to the Review Queue automatically
                if confidence < 0.7:
                    list_review.append(term_string)
                elif classification in ["RELEVANT_BRAND", "RELEVANT_GENERIC"]:
                    list_relevant.append(term_string)
                elif classification == "IRRELEVANT":
                    list_irrelevant.append(term_string)
                else:
                    list_review.append(term_string)
                    
        except Exception as e:
            # Emergency Backup Plan: If an individual batch network call breaks,
            # dump the raw terms safely into the Review Queue so no keywords disappear.
            for fallback_term in batch:
                list_review.append(fallback_term)

    # 5. ADVANCED ROOT NEGATIVE SELECTION & CANNIBALIZATION GUARDRAIL
    # Separate bad terms into separate individual components to count frequencies
    all_words = []
    for term in list_irrelevant:
        words = re.findall(r'\b\w+\b', term.lower())
        all_words.extend(words)
        
    word_frequencies = collections.Counter(all_words)
    candidate_roots = [word for word, count in word_frequencies.items() if count > 1]
    
    approved_root_negatives = []
    terms_absorbed_by_roots_count = 0
    irrelevant_terms_kept_as_phrases = []
    
    # Establish our security lookup pool from the safe arrays
    safe_lookup_pool = set([t.lower().strip() for t in (list_relevant + list_review)])
    
    for root in candidate_roots:
        is_safe_root = True
        # Hard check: Scan entire safe pool. The root word can NEVER appear inside a safe string.
        for safe_term in safe_lookup_pool:
            if re.search(r'\b' + re.escape(root) + r'\b', safe_term):
                is_safe_root = False
                break
                
        # Extra constraint: Omit common connection filler words under 3 letters long
        if is_safe_root and len(root) > 2:
            approved_root_negatives.append(root)
            
    # Audit exactly how many junk rows are safely handled by your clean roots list
    for term in list_irrelevant:
        is_absorbed = False
        for root in approved_root_negatives:
            if re.search(r'\b' + re.escape(root) + r'\b', term.lower()):
                is_absorbed = True
                break
        if is_absorbed:
            terms_absorbed_by_roots_count +=
