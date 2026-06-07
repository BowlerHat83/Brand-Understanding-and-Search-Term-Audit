import re
import json
import collections
import pandas as pd
from google import genai
from google.genai import errors
from . import cache_manager as cm

# Precision Prompt Safeguard
BATCH_AUDIT_SYSTEM_PROMPT = (
    "You are a conservative, line-by-line PPC Auditing Engine. Your goal is to review a "
    "micro-batch of search terms with absolute precision against a brand blueprint.\n\n"
    "CRITICAL ACCURACY RULES:\n"
    "1. Evaluate each term completely independent of the terms around it.\n"
    "2. For each term, determine its classification:\n"
    "   - 'RELEVANT_BRAND': Contains a protected client brand name variation.\n"
    "   - 'RELEVANT_GENERIC': Aligns perfectly with the commercial intent of the Core Offering.\n"
    "   - 'IRRELEVANT': Mentions a competitor, or indicates wrong intent (DIY, jobs, info, blogs).\n"
    "   - 'REVIEW_QUEUE': Only use this if the term is completely ambiguous or tracking data.\n"
    "3. Calculate an internal confidence score between 0.0 and 1.0. If your score for 'IRRELEVANT' or 'RELEVANT' is below 0.7, route the term to 'REVIEW_QUEUE'.\n"
    "4. Write your analysis/reasoning FIRST inside the JSON object before selecting the decision.\n\n"
    "Output MUST be a strict JSON object containing a top-level key 'term_data' mapping to an array of objects."
)

def chunk_list(lst: list, n: int):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]

def run_search_terms_audit(csv_file_path: str, selected_profile_key: str, progress_bar_ui=None, status_text_ui=None) -> dict:
    cached_profile = cm.get_profile_by_name(selected_profile_key)
    if not cached_profile:
        raise ValueError(f"Profile cache '{selected_profile_key}' could not be located.")
        
    blueprint = cached_profile["blueprint"]
    df = pd.read_csv(csv_file_path)
    df.columns = [col.lower().strip() for col in df.columns]
    
    if "search term" not in df.columns:
        raise KeyError("ERR_MISSING_COLUMN: Could not find required 'Search term' column in the uploaded CSV.")
        
    raw_terms = df["search term"].dropna().astype(str).str.strip().unique().tolist()
    total_inputted_count = len(raw_terms)
    
    list_relevant = []
    list_irrelevant = []
    list_review = []
    
    # Initialize the official Gemini Client
    client = genai.Client()
    
    micro_batches = list(chunk_list(raw_terms, 50))
    total_batches = len(micro_batches)
    
    # Process batches
    for idx, batch in enumerate(micro_batches):
        # UI COSMETIC: Update progress bar if passed from app.py
        if progress_bar_ui and status_text_ui:
            progress_percent = (idx) / total_batches
            progress_bar_ui.progress(progress_percent)
            status_text_ui.text(f"Processing micro-batch {idx + 1} of {total_batches} ({len(batch)} terms)...")

        user_prompt = f"""
        **Brand Blueprint Context:**
        - Brand Name: {selected_profile_key.split('|')[0].strip()}
        - Protected Brand Variants: {", ".join(blueprint["brand_variants"])}
        - Core Offering Boundary: {blueprint["strict_relevance_rule"]}
        - Explicit Junk Targets: {", ".join(blueprint["explicit_negative_triggers"])}
        
        **Micro-Batch to Audit:**
        {json.dumps(batch)}
        """
        
        try:
            # Native Gemini Structural JSON Request
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=user_prompt,
                config=genai.types.GenerateContentConfig(
                    system_instruction=BATCH_AUDIT_SYSTEM_PROMPT,
                    response_mime_type="application/json",
                    temperature=0.1
                ),
            )
            
            payload = json.loads(response.text)
            records = payload.get("term_data", [])
            
            for item in records:
                term_string = item.get("term", "").strip()
                classification = item.get("classification", "REVIEW_QUEUE")
                confidence = float(item.get("confidence", 0.0))
                
                if confidence < 0.7:
                    list_review.append({"Search Term": term_string, "Reasoning": item.get("reasoning", "Low confidence override."), "Confidence Score": confidence})
                elif classification in ["RELEVANT_BRAND", "RELEVANT_GENERIC"]:
                    list_relevant.append({"Search Term": term_string, "Reasoning": item.get("reasoning", ""), "Confidence Score": confidence})
                elif classification == "IRRELEVANT":
                    list_irrelevant.append({"Search Term": term_string, "Reasoning": item.get("reasoning", ""), "Confidence Score": confidence})
                else:
                    list_review.append({"Search Term": term_string, "Reasoning": item.get("reasoning", "Unrecognized classification tag."), "Confidence Score": confidence})
                    
        # --- SPECIFIC GEMINI ERROR HANDLING BLOCKS ---
        except errors.APIError as api_err:
            if api_err.code == 429:
                raise RuntimeError(
                    "ERR_GEMINI_QUOTA_EXCEEDED: Your Gemini API Rate Limits or Token Quotas have been exceeded. "
                    "Please wait 60 seconds before retrying or upgrade your Google AI Studio tier plan."
                )
            else:
                raise RuntimeError(f"ERR_GEMINI_SERVER_BREAK ({api_err.code}): Google API encountered an internal glitch. Details: {str(api_err)}")
        except Exception as e:
            raise RuntimeError(f"ERR_PIPELINE_UNKNOWN: The audit engine processing sequence broke unexpectedly. Technical details: {str(e)}")

    # Ensure progress finishes visually at 100%
    if progress_bar_ui:
        progress_bar_ui.progress(1.0)

    # --- ROOT NEGATIVE SELECTION & CANNIBALIZATION GUARDRAIL ---
    # Extract just the raw strings for our internal cross-reference matching
    raw_irrelevant_strings = [x["Search Term"] for x in list_irrelevant]
    raw_safe_strings = [x["Search Term"].lower().strip() for x in (list_relevant + list_review)]
    safe_lookup_pool = set(raw_safe_strings)

    all_words = []
    for term in raw_irrelevant_strings:
        words = re.findall(r'\b\w+\b', term.lower())
        all_words.extend(words)
        
    word_frequencies = collections.Counter(all_words)
    candidate_roots = [word for word, count in word_frequencies.items() if count > 1]
    
    approved_root_negatives = []
    terms_absorbed_by_roots_count = 0
    irrelevant_terms_kept_as_phrases = []
    
    for root in candidate_roots:
        is_safe_root = True
        for safe_term in safe_lookup_pool:
            if re.search(r'\b' + re.escape(root) + r'\b', safe_term):
                is_safe_root = False
                break
        if is_safe_root and len(root) > 2:
            approved_root_negatives.append(root)
            
    for item in list_irrelevant:
        term = item["Search Term"]
        is_absorbed = False
        for root in approved_root_negatives:
            if re.search(r'\b' + re.escape(root) + r'\b', term.lower()):
                is_absorbed = True
                break
        if is_absorbed:
            terms_absorbed_by_roots_count += 1
        else:
            irrelevant_terms_kept_as_phrases.append(term)
            
    notation_output_list = []
    for root in approved_root_negatives:
        notation_output_list.append(root.strip())
    for phrase in irrelevant_terms_kept_as_phrases:
        clean_phrase = phrase.strip()
        if " " in clean_phrase:
            notation_output_list.append(f'"{clean_phrase}"')
        else:
            notation_output_list.append(clean_phrase)
            
    # Compile root summaries for Stage 3 Tab 4
    roots_summary_data = [{"Isolated Root Word": root, "Frequency Count": word_frequencies[root]} for root in approved_root_negatives]

    total_outputted_count = len(list_relevant) + len(list_irrelevant) + len(list_review)
    
    return {
        "metrics": {
            "total_inputted": total_inputted_count,
            "relevant_count": len(list_relevant),
            "irrelevant_count": len(list_irrelevant),
            "review_queue_count": len(list_review),
            "total_outputted": total_outputted_count,
            "integrity_check_passed": (total_inputted_count == total_outputted_count),
            "roots_found": len(approved_root_negatives),
            "terms_absorbed_by_roots": terms_absorbed_by_roots_count
        },
        "review_queue_data": [x["Search Term"] for x in list_review],
        "copy_paste_notation": "\n".join(notation_output_list),
        "raw_classified_records": {
            "relevant": list_relevant,
            "review": list_review,
            "irrelevant": list_irrelevant,
            "roots_summary": roots_summary_data
        }
    }
