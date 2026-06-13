import re
import json
from pydantic import BaseModel, Field
from typing import List, Literal
from google import genai
from google.genai import types

# 1. Define the schema for a single term's output
class SingleTermClassification(BaseModel):
    search_term: str = Field(description="The exact search term being evaluated.")
    classification: Literal["relevant", "irrelevant", "review"] = Field(description="Must select exactly one.")
    confidence: float = Field(description="Confidence score between 0.00 and 1.00.")
    reason: str = Field(description="Max 5 words explaining the decision.")

# 2. Define the schema for the batch wrapper
class BatchClassificationResponse(BaseModel):
    results: List[SingleTermClassification] = Field(description="Array containing the classification data for every single input term.")

def classify_terms_batch(terms_batch: List[str], locked_rules: dict) -> List[dict]:
    """
    Evaluates a batch of search terms simultaneously in a single API call.
    """
    client = genai.Client()
    
    prompt = f"""
    Evaluate the following list of search term queries:
    {json.dumps(terms_batch)}
    
    Against these absolute brand guidelines:
    - Allowed Brand Variants: {locked_rules.get('brand_variants', [])}
    - Competitor Red Flags: {locked_rules.get('competitors', [])}
    - Protected Core Phrases: {locked_rules.get('protected_terms', [])}
    - Clear Irrelevant Elements: {locked_rules.get('irrelevant_terms', [])}
    """
    
    system_prompt = (
        "You are an expert Google Ads optimization algorithm. Process the array of search terms accurately. "
        "For each term, determine if it is 'relevant', 'irrelevant', or needs 'review'. "
        "Do not default to 'review' unless there is an absolute tie or severe semantic contradiction. "
        "You must output a result for EVERY single term provided in the input list. Do not drop any terms. "
        "Keep your reason strictly under 5 words."
    )
    
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                response_mime_type="application/json",
                response_schema=BatchClassificationResponse,
                temperature=0.0  # Kept at 0.0 for deterministic precision
            )
        )
        
        # Parse and validate the response
        parsed_data = BatchClassificationResponse.model_validate_json(response.text).model_dump()
        return parsed_data["results"]
        
    except Exception as e:
        raise RuntimeError(f"Batch processing error: {str(e)}")

def extract_root_negatives(irrelevant_terms: List[str], saved_terms: List[str]) -> dict:
    """ Pure Python math engine to isolate broad match negative candidates (unchanged) """
    word_counts = {}
    protected_tokens = set()
    for term in saved_terms:
        for word in re.findall(r'\b\w+\b', str(term).lower()):
            protected_tokens.add(word)
            
    for term in irrelevant_terms:
        words_in_phrase = set(re.findall(r'\b\w+\b', str(term).lower()))
        for word in words_in_phrase:
            if word not in protected_tokens and not word.isdigit():
                word_counts[word] = word_counts.get(word, 0) + 1
                
    root_negatives = {word: count for word, count in word_counts.items() if count > 1}
    return dict(sorted(root_negatives.items(), key=lambda item: item[1], reverse=True))

def apply_ads_notation(term: str) -> str:
    """ Formats strings for Google Ads syntax """
    cleaned = str(term).strip()
    if not cleaned: return ""
    return cleaned.lower() if len(cleaned.split()) == 1 else f'"{cleaned.lower()}"'
