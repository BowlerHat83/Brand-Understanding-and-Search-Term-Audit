import re
from pydantic import BaseModel, Field
from typing import List, Literal
from google import genai
from google.genai import types

class ClassificationResult(BaseModel):
    classification: Literal["relevant", "irrelevant", "review"] = Field(description="Must select exactly one.")
    confidence: float = Field(description="Confidence decimal score between 0.00 and 1.00.")
    reason: str = Field(description="Short reason explaining why it was classified this way. STRICT MAX 5 WORDS.")

def classify_single_term(search_term: str, locked_rules: dict) -> dict:
    """
    Classifies an individual search term using the approved ruleset rules matrix.
    """
    client = genai.Client()
    
    prompt = f"""
    Evaluate this search term query: "{search_term}"
    
    Against these absolute rulesets criteria:
    - Allowed Brand Variants: {locked_rules.get('brand_variants', [])}
    - Competitor Red Flags: {locked_rules.get('competitors', [])}
    - Protected Core Phrases: {locked_rules.get('protected_terms', [])}
    - Clear Irrelevant Elements: {locked_rules.get('irrelevant_terms', [])}
    """
    
    system_prompt = (
        "You are an aggressive but highly accurate Google Ads Negative Keyword filter agent. "
        "Classify the term as 'relevant', 'irrelevant', or 'review'. "
        "Only lean into 'review' if a phrase directly contradicts itself or overlaps equally "
        "between relevant and irrelevant patterns. Keep reasoning at a maximum of 5 words."
    )
    
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                response_mime_type="application/json",
                response_schema=ClassificationResult,
                temperature=0.0
            )
        )
        parsed = ClassificationResult.model_validate_json(response.text).model_dump()
        # Enforce max 5 word ceiling constraint programmatically
        words = parsed['reason'].split()
        if len(words) > 5:
            parsed['reason'] = " ".join(words[:5])
        return parsed
    except Exception as e:
        raise RuntimeError(f"Audit failure during search term classification: {str(e)}")

def extract_root_negatives(irrelevant_terms: List[str], saved_terms: List[str]) -> dict:
    """
    Pure Python math matrix processing engine to extract broad match candidates.
    Isolates single terms appearing uniquely in the irrelevant bucket.
    """
    word_counts = {}
    # Build a tokenized set of any word that is safely kept in relevant or review arrays
    protected_tokens = set()
    for term in saved_terms:
        for word in re.findall(r'\b\w+\b', str(term).lower()):
            protected_tokens.add(word)
            
    # Parse individual single tokens from the bad search queries
    for term in irrelevant_terms:
        words_in_phrase = set(re.findall(r'\b\w+\b', str(term).lower()))
        for word in words_in_phrase:
            if word not in protected_tokens and not word.isdigit():
                word_counts[word] = word_counts.get(word, 0) + 1
                
    # Filter only tokens appearing multiple times
    root_negatives = {word: count for word, count in word_counts.items() if count > 1}
    # Sort descending by impact strength
    return dict(sorted(root_negatives.items(), key=lambda item: item[1], reverse=True))

def apply_ads_notation(term: str) -> str:
    """
    Applies Google Ads syntax formatting structure rules cleanly.
    """
    cleaned = str(term).strip()
    if not cleaned:
        return ""
    if len(cleaned.split()) == 1:
        return cleaned.lower()  # Broad match
    else:
        return f'"{cleaned.lower()}"'  # Phrase match
