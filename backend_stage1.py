import os
from pydantic import BaseModel, Field
from typing import List
from google import genai
from google.genai import types

# Define the structured output format for the brand profile
class BrandProfile(BaseModel):
    brand_variants: List[str] = Field(description="Variations, misspellings, abbreviations of the brand name.")
    competitors: List[str] = Field(description="Known competitor brand names or companies matching this space.")
    protected_terms: List[str] = Field(description="High-intent commercial terms essential to save (e.g., service buy words).")
    irrelevant_terms: List[str] = Field(description="Concepts, search angles, or target intents completely disconnected from the offering.")

def run_brand_audit(brand_name: str, core_offering: str, landing_page: str) -> dict:
    """
    Analyzes brand positioning and returns a structured profile ruleset.
    """
    # Initialize the official modern SDK client
    # Assumes GEMINI_API_KEY is configured in your environment variables
    client = genai.Client()
    
    prompt = f"""
    Analyze the following brand context for a Google Ads account:
    - Brand Name: {brand_name}
    - Core Offering: {core_offering}
    - Target Landing Page context: {landing_page}
    
    Identify brand variants, competitor brands, core protected terms, and completely irrelevant angles/themes.
    """
    
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=(
                    "You are a meticulous PPC Strategy architect. Extract definitive brand guidelines. "
                    "Be highly specific; do not use vague categories."
                ),
                response_mime_type="application/json",
                response_schema=BrandProfile,
                temperature=0.1
            )
        )
        # Parse output safely via validation schema
        return BrandProfile.model_validate_json(response.text).model_dump()
        
    except Exception as e:
        # Wrap up backend exceptions to re-throw clearly to the main app wrapper
        raise RuntimeError(f"Gemini processing failure: {str(e)}")
