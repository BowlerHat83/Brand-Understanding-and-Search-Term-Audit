import re
import json
import collections
import pandas as pd
import os
import time
import random

from google import genai
from google.genai import errors
from google.genai.types import GenerateContentConfig
from . import cache_manager as cm

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
    "3. Calculate an internal confidence score between 0.0 and 1.0.\n"
    "4. CRITICAL: Keep the 'reasoning' value incredibly concise (under 5 words). E.g., 'Competitor term', 'Exact intent match', 'Contains DIY intent'.\n"
    "5. Output MUST be valid JSON.\n\n"
    "Output format:\n"
    "{\n"
    '  "term_data": [\n'
    "      {\n"
    '        "term": "example",\n'
    '        "classification": "IRRELEVANT",\n'
    '        "confidence": 0.95,\n'
    '        "reasoning": "Contains DIY intent."\n'
    "      }\n"
    "  ]\n"
    "}"
)

def chunk_list(lst: list, n: int):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]

def clean_json_response(raw_text: str):
    raw_text = raw_text.strip()
    if raw_text.startswith("```json"):
        raw_text = raw_text.replace("```json", "").replace("```", "").strip()
    return raw_text

def run_search_terms_audit(csv_file, selected_profile_key: str, progress_bar_ui=None, status_text_ui=None) -> dict:
    cached_profile = cm.get_profile_by_name(selected_profile_key)
    if not cached_profile:
        raise ValueError(f"Profile cache '{selected_profile_key}' could not be located.")

    blueprint = cached_profile["blueprint"]

    try:
        df = pd.read_csv(csv_file)
    except Exception as e:
        raise RuntimeError(f"ERR_CSV_READ_FAILURE: Failed reading uploaded CSV.\n{str(e)}")

    df.columns = [col.lower().strip() for col in df.columns]
    if "search term" not in df.columns:
        raise KeyError("ERR_MISSING_COLUMN: Could not find required 'Search term' column.")

    raw_terms = df["search term"].dropna().astype(str).str.strip().unique().tolist()
    total_inputted_count = len(raw_terms)

    list_relevant, list_irrelevant, list_review = [], [], []

    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("ERR_MISSING_API_KEY: GOOGLE_API_KEY environment variable not found.")

    client = genai.Client(api_key=api_key)
    micro_batches = list(chunk_list(raw_terms, 30))
    total_batches = len(micro_batches)

    for idx, batch in enumerate(micro_batches):
        if progress_bar_ui and status_text_ui:
            progress_percent = (idx) / total_batches
            progress_bar_ui.progress(progress_percent)
            status_text_ui.text(f"Processing batch {idx + 1} of {total_batches}...")

        user_prompt = f"""
Brand Blueprint Context:
- Brand Name: {selected_profile_key.split('|')[0].strip()}
- Protected Brand Variants: {", ".join(blueprint["brand_variants"])}
- Core Offering Boundary: {blueprint["strict_relevance_rule"]}
- Explicit Junk Targets: {", ".join(blueprint["explicit_negative_triggers"])}

Search Terms:
{json.dumps(batch)}
"""
        MAX_RETRIES = 5
        response = None

        for attempt in range(MAX_RETRIES):
            try:
                response = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=user_prompt,
                    config=GenerateContentConfig(
                        system_instruction=BATCH_AUDIT_SYSTEM_PROMPT,
                        response_mime_type="application/json",
                        temperature=0.1,
                    ),
                )
                break
            except errors.APIError as api_err:
                err_code = getattr(api_err, "code", None) or "UNKNOWN"
                err_message = getattr(api_err, "message", str(api_err))

                if err_code in [429, 500, 503] or "429" in err_message or "503" in err_message:
                    if attempt < MAX_RETRIES - 1:
                        sleep_time = (2 ** attempt) + random.uniform(0.5, 1.5)
                        if status_text_ui:
                            status_text_ui.text(f"Rate limit / Traffic hiccup ({err_code}). Retrying in {sleep_time:.1f}s...")
                        time.sleep(sleep_time)
                        continue
                    else:
                        raise RuntimeError(f"ERR_GEMINI_QUOTA_EXCEEDED: Exhausted total connections ({MAX_RETRIES}) at batch {idx + 1}.")
                else:
                    raise RuntimeError(f"ERR_GEMINI_SERVER_BREAK ({err_code}): {err_message}")
            except Exception as inner_err:
                raise RuntimeError(f"ERR_BATCH_EXECUTION: {str(inner_err)}")

        if not response or not response.text:
            raise RuntimeError("ERR_EMPTY_RESPONSE: Gemini returned an empty response.")

        cleaned_response = clean_json_response(response.text)
        try:
            payload = json.loads(cleaned_response)
        except json.JSONDecodeError:
            raise RuntimeError(f"ERR_INVALID_JSON_RESPONSE:\n\n{cleaned_response}")

        records = payload.get("term_data", [])
        for item in records:
            term_string = str(item.get("term", "")).strip()
            classification = str(item.get("classification", "REVIEW_QUEUE")).strip()

            try:
                confidence = float(item.get("confidence", 0.0) or 0.0)
            except (TypeError, ValueError):
                confidence = 0.0

            record = {"Search Term": term_string, "Reasoning": str(item.get("reasoning", "")), "Confidence Score": confidence}

            if confidence < 0.7:
                list_review.append(record)
            elif classification in ["RELEVANT_BRAND", "RELEVANT_GENERIC"]:
                list_relevant.append(record)
            elif classification == "IRRELEVANT":
                list_irrelevant.append(record)
            else:
                list_review.append(record)

        if idx < total_batches - 1:
            time.sleep(1.0) # Free-tier safety pacer

    if progress_bar_ui:
        progress_bar_ui.progress(1.0)

    # =========================================================================
    # 🔄 UNIVERSAL, PLURAL-AWARE ROOT NEGATIVE SAFETY LAYER
    # =========================================================================
    raw_irrelevant_strings = [x["Search Term"] for x in list_irrelevant]
    raw_safe_strings = [x["Search Term"].lower().strip() for x in (list_relevant + list_review)]
    safe_lookup_pool = set(raw_safe_strings)

    # Helper function to strip common plural suffixes dynamically (NLP substitute)
    def get_stem(word: str) -> str:
        w = word.lower().strip()
        if w.endswith('ies') and len(w) > 5:
            return w[:-3] + 'i'
        if w.endswith('es') and len(w) > 4:
            return w[:-2]
        if w.endswith('s') and not w.endswith('ss') and len(w) > 3:
            return w[:-1]
        return w

    # 1. Generate Protected Seeds from Blueprint and Selected Profile Dropdown Key
    protected_seeds = set()
    if "brand_variants" in blueprint:
        for variant in blueprint["brand_variants"]:
            protected_seeds.update(re.findall(r'\b\w+\b', variant.lower()))
            
    profile_label_words = re.findall(r'\b\w+\b', selected_profile_key.lower())
    protected_seeds.update(profile_label_words)
    
    # Standardize all blueprint profile tokens into base stems
    protected_seed_stems = {get_stem(word) for word in protected_seeds}

    # 2. Extract and index all individual word stems from terms flagged as safe/review
    safe_word_stems = set()
    for safe_term in safe_lookup_pool:
        safe_words = re.findall(r'\b\w+\b', safe_term)
        for sw in safe_words:
            safe_word_stems.add(get_stem(sw))

    # 3. Tokenize and count candidate words from irrelevant phrases
    all_words = []
    for term in raw_irrelevant_strings:
        all_words.extend(re.findall(r'\b\w+\b', term.lower()))

    word_frequencies = collections.Counter(all_words)
    candidate_roots = [word for word, count in word_frequencies.items() if count > 1 and len(word) > 2]

    approved_root_negatives = []
    terms_absorbed_by_roots_count = 0
    irrelevant_terms_kept_as_phrases = []

    # 4. Filter Candidates using Linguistic Stems
    for root in candidate_roots:
        root_stem = get_stem(root)
        
        # Rule A: Cannot match the core brand, offering description, or blueprint definitions
        if root_stem in protected_seed_stems or root in protected_seeds:
            continue
            
        # Rule B: Base linguistic stem cannot exist anywhere within approved safe terms
        if root_stem in safe_word_stems:
            continue
            
        # Rule C: Traditional exact containment check as a final safety backstop
        is_safe_root = True
        for safe_term in safe_lookup_pool:
            if re.search(r'\b' + re.escape(root) + r'\b', safe_term):
                is_safe_root = False
                break
                
        if is_safe_root:
            approved_root_negatives.append(root)

    # 5. Distribute Irrelevant Terms between Root Absorption and Strict Phrase Matches
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

    # 6. Construct Clean Copy/Paste Notation Output
    notation_output_list = [root.strip() for root in approved_root_negatives]
    for phrase in irrelevant_terms_kept_as_phrases:
        clean_phrase = phrase.strip()
        notation_output_list.append(f'"{clean_phrase}"' if " " in clean_phrase else clean_phrase)

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
