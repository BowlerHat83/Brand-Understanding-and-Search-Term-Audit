import re
import json
import collections
import pandas as pd
import google.generativeai as genai
import google.api_core.exceptions as google_exceptions
from backend_config import initialize_gemini

def classify_search_terms_batch(terms_list, brand_truth):
    """Batches search terms to optimize speed and drop costs drastically."""
    initialize_gemini()
    try:
        model = genai.GenerativeModel(
            model_name='gemini-1.5-flash',
            generation_config={"response_mime_type": "application/json"}
        )
        
        prompt = f"""
        You are an elite automated Google Ads script. Categorize the list of Search Terms based on the absolute Truth Profile provided below.
        
        Truth Profile: {json.dumps(brand_truth)}
        Search Terms to Analyze: {json.dumps(terms_list)}
        
        CLASSIFICATION MANDATE:
        - "relevant": Explicitly relates to the brand, core offering or variations.
        - "irrelevant": Belongs to a competitor brand, mismatching intent, or irrelevant niches.
        - "review": ONLY use as a last resort if context is genuinely missing.
        
        Return a strict JSON array matching this exact pattern:
        {{
          "results": [
             {{ "term": "example query", "classification": "relevant/irrelevant/review", "confidence_score": 0.95, "reasoning": "Max 5 word logic" }}
          ]
        }}
        """
        response = model.generate_content(prompt)
        return json.loads(response.text).get("results", [])
        
    except google_exceptions.ResourceExhausted:
        return [{"term": t, "classification": "review", "confidence_score": 0.0, "reasoning": "ERR_GEMINI_QUOTA_EXCEEDED"} for t in terms_list]
    except Exception:
        return [{"term": t, "classification": "review", "confidence_score": 0.0, "reasoning": "ERR_GEMINI_SYSTEM_ERROR"} for t in terms_list]

def calculate_root_negatives(df_classified):
    """Extracts high-impact single-word root negatives that don't cross-contaminate positive lists."""
    irrelevant_terms = df_classified[df_classified['classification'] == 'irrelevant']['term'].tolist()
    protected_terms = df_classified[df_classified['classification'].isin(['relevant', 'review'])]['term'].tolist()
    
    protected_words = set()
    for term in protected_terms:
        protected_words.update(re.findall(r'\b\w+\b', str(term).lower()))
    
    irrelevant_word_counts = collections.Counter()
    word_to_terms_map = collections.defaultdict(set)
    
    for term in irrelevant_terms:
        words = set(re.findall(r'\b\w+\b', str(term).lower()))
        for word in words:
            if word not in protected_words and not word.isdigit() and len(word) > 2:
                irrelevant_word_counts[word] += 1
                word_to_terms_map[word].add(term)
                
    root_negatives = []
    for word, count in irrelevant_word_counts.items():
        if count >= 2:
            root_negatives.append({
                "root_negative": word,
                "blocked_count": count,
                "terms_blocked": list(word_to_terms_map[word])
            })
            
    return sorted(root_negatives, key=lambda x: x['blocked_count'], reverse=True)

def generate_google_ads_notation(df_classified, root_negatives_list):
    """Formats keywords with broad/phrase match punctuation rules while omitting redundant rows."""
    notation_list = []
    root_words = {root['root_negative'] for root in root_negatives_list}
    
    for root in root_negatives_list:
        notation_list.append(root['root_negative'])
        
    irrelevant_df = df_classified[df_classified['classification'] == 'irrelevant']
    for _, row in irrelevant_df.iterrows():
        term = str(row['term']).lower()
        term_words = set(re.findall(r'\b\w+\b', term))
        
        if any(rw in term_words for rw in root_words):
            continue # Already safely blocked by root word shortcut
            
        if len(term.split()) == 1:
            notation_list.append(term)
        else:
            notation_list.append(f'"{term}"')
            
    return list(set(notation_list))
