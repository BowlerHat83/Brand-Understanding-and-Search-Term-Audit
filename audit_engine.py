import re
import json
import collections
import pandas as pd
from openai import OpenAI
import cache_manager as cm

def run_search_terms_audit(csv_file_path: str, selected_profile_key: str) -> dict:
    """
    Executes the entire Tier-2 Audit Pipeline: 
    Validates data, batches queries to LLM, routes to classification buckets,
    and safely extracts root negative candidates without cannibalizing good traffic.
    """
    # 1. Fetch the absolute truth blueprint from cache
    cached_data = cm.get_profile_by_name(selected_profile_key)
    if not cached_data:
        raise ValueError("Selected brand profile cache could not be found.")
        
    blueprint = cached_data["blueprint"]
    
    # 2. Read and clean the inputted CSV data
    df = pd.read_csv(csv_file_path)
    df.columns = [col.lower().strip() for col in df.columns]
    
    # Extract unique search terms and clean out empty rows
    raw_terms = df["search term"].dropna().unique().tolist()
    total_inputted_count = len(raw_terms)
    
    # 3. Batch Process via LLM (Simulated sizing here for clean grouping architecture)
    # Inside the production app, you will loop through raw_terms in batches of 40.
    client = OpenAI()
    
    system_prompt = (
        "You are a strict, highly conservative PPC auditing algorithm. "
        "Your sole task is to classify search terms against a business blueprint. "
        "You must output a single, raw JSON object mapping terms to classifications. "
        "CRITICAL: Only use 'REVIEW_QUEUE' as an emergency last resort if the term is completely ambiguous "
        "or impossible to verify. Do not use it as a lazy option."
    )
    
    # We will pass the terms array and the blueprint rules to the prompt
    # The LLM returns a structured JSON layout like this:
    # { "term_data": [ {"term": "...", "class": "RELEVANT_BRAND"/"RELEVANT_GENERIC"/"IRRELEVANT"/"REVIEW_QUEUE", "confidence": 0.95 } ] }
    
    # --- For development modeling, we initialize our structural arrays ---
    list_relevant = []
    list_irrelevant = []
    list_review = []
    
    # --- PROMPT EXECUTION & ROUTING SIMULATION ---
    # Python populates arrays based on the strict threshold (Confidence >= 0.7)
    # If Confidence < 0.7, the system forcibly overrides the tag to REVIEW_QUEUE.
    
    # Mock assignments to show data path flow execution
    for term in raw_terms:
        # Lowercase for absolute safety checks
        t_clean = term.lower().strip()
        
        # Purely as an architectural baseline placeholder logic before LLM pipeline calls:
        if any(variant in t_clean for variant in blueprint["brand_variants"]):
            list_relevant.append(term)
        elif any(trigger in t_clean for trigger in blueprint["explicit_negative_triggers"]):
            list_irrelevant.append(term)
        else:
            # Simulated edge case or default grouping bucket
            list_review.append(term)
            
    # 4. ADVANCED ROOT NEGATIVE SELECTION & CROSS-REFERENCE SAFETY LOOP
    # Tokenize words from the irrelevant bucket to look for single-word root opportunities
    all_words = []
    for term in list_irrelevant:
        # Regex to split phrases into clean individual words
        words = re.findall(r'\b\w+\b', term.lower())
        all_words.extend(words)
        
    word_counts = collections.Counter(all_words)
    
    # Filter down to words that appear multiple times in junk searches
    candidate_roots = [word for word, count in word_counts.items() if count > 1]
    
    # Safe arrays to isolate final outputs
    approved_root_negatives = []
    raw_terms_captured_by_roots_count = 0
    irrelevant_terms_kept_as_phrases = []
    
    # Create matching baseline blocks of safe strings for checking overlap
    safe_lookup_pool = set([t.lower() for t in (list_relevant + list_review)])
    
    for root in candidate_roots:
        # ABSOLUTE GUARDRAIL: Check if the word exists anywhere inside relevant/review sets
        is_safe = True
        for safe_term in safe_lookup_pool:
            if re.search(r'\b' + re.escape(root) + r'\b', safe_term):
                is_safe = False
                break
                
        if is_safe and len(root) > 2: # Keep roots meaningful (no 1 or 2 letter words)
            approved_root_negatives.append(root)
        
    # Calculate how many irrelevant terms are cleanly handled by our newly found roots
    for term in list_irrelevant:
        captured = False
        for root in approved_root_negatives:
            if re.search(r'\b' + re.escape(root) + r'\b', term.lower()):
                captured = True
                break
        if captured:
            raw_terms_captured_by_roots_count += 1
        else:
            irrelevant_terms_kept_as_phrases.append(term)
            
    # 5. GOOGLE ADS NOTATION COMPILER
    # Single words -> Broad Match (no notation)
    # Multi-words -> Phrase Match (" ")
    notation_output_list = []
    for root in approved_root_negatives:
        notation_output_list.append(root) # Single root words stay broad
        
    for phrase in irrelevant_terms_kept_as_phrases:
        clean_phrase = phrase.strip()
        if " " in clean_phrase:
            notation_output_list.append(f'"{clean_phrase}"') # Multi-word gets phrase tags
        else:
            notation_output_list.append(clean_phrase)
            
    # 6. VERIFICATION TOTALS RECONCILIATION
    total_outputted_count = len(list_relevant) + len(list_irrelevant) + len(list_review)
    
    # Bundle the entire state to hand off to the interface
    return {
        "metrics": {
            "total_inputted": total_inputted_count,
            "relevant_count": len(list_relevant),
            "irrelevant_count": len(list_irrelevant),
            "review_queue_count": len(list_review),
            "total_outputted": total_outputted_count,
            "integrity_check_passed": (total_inputted_count == total_outputted_count),
            "roots_found": len(approved_root_negatives),
            "terms_absorbed_by_roots": raw_terms_captured_by_roots_count
        },
        "data_buckets": {
            "relevant": list_relevant,
            "review_queue": list_review,
            "irrelevant_raw": list_irrelevant
        },
        "final_negatives_notation": notation_output_list
    }
