import re
import json
from pydantic import BaseModel, Field
from typing import List, Literal
from google import genai
from google.genai import types

# 1. Define the strict data validation structure for Gemini's output
class SingleTermClassification(BaseModel):
    search_term: str = Field(description="The exact search term being evaluated from the input array.")
    classification: Literal["relevant", "irrelevant", "review"] = Field(description="Must pick exactly one category.")
    confidence: float = Field(description="Confidence decimal between 0.00 and 1.00.")
    reason: str = Field(description="Strictly 5 words or less explaining the logical match choice.")

# 2. Define the multi-row batch container array
class BatchClassificationResponse(BaseModel):
    results: List[SingleTermClassification] = Field(description="Array matching every single input query.")

def classify_terms_batch(terms_batch: List[str], locked_rules: dict) -> List[dict]:
    """
    Evaluates a batch group of 50 search terms simultaneously in a single API container request.
    Staying completely within free-tier RPM quotas.
    """
    # Initializes client utilizing your secure cloud-stored GEMINI_API_KEY environment token
    client = genai.Client()
    
    prompt = f"""
    Evaluate the following array list of PPC search queries:
    {json.dumps(terms_batch)}
    
    Against these absolute campaign match guidelines:
    - Allowed Brand Variants/Misspellings: {locked_rules.get('brand_variants', [])}
    - Competitor Target Brand Names (Red Flags): {locked_rules.get('competitors', [])}
    - Protected Core Offering Terms: {locked_rules.get('protected_terms', [])}
    - Clear Irrelevant Elements/Concepts: {locked_rules.get('irrelevant_terms', [])}
    """
    
    system_prompt = (
        "You are an elite, deterministic Google Ads keyword filtering machine. "
        "Process every search term query inside the input array accurately against the guidelines. "
        "Classify as 'relevant', 'irrelevant', or 'review'. "
        "You must generate an evaluation line for EVERY single query in the input array. Do not miss any. "
        "Keep your reason values strictly below a 5-word micro-readout description."
    )
    
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                response_mime_type="application/json",
                response_schema=BatchClassificationResponse,
                temperature=0.0  # Keeps logic completely locked and non-creative
            )
        )
        
        # Validates and maps the raw response string straight to Python types dictionary format
        parsed_data = BatchClassificationResponse.model_validate_json(response.text).model_dump()
        return parsed_data["results"]
        
    except Exception as e:
        raise RuntimeError(f"Cloud Batch Matrix Engine failed on execution: {str(e)}")

def extract_root_negatives(irrelevant_terms: List[str], saved_terms: List[str]) -> dict:
    """ Isolated pure Python string set extraction math (100% accurate, no API overhead) """
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
    """ Correctly wraps strings into strict broad or phrase match layout parameters for Google Ads """
    cleaned = str(term).strip()
    if not cleaned: 
        return ""
    return cleaned.lower() if len(cleaned.split()) == 1 else f'"{cleaned.lower()}"'
