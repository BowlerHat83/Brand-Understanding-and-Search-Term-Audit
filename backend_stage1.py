import os
import re
import streamlit as st
from pydantic import BaseModel, Field
from typing import List
import google.genai as genai
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
    # Securely retrieve the upgraded token directly from Streamlit secrets
    api_key = st.secrets.get("GEMINI_API_KEY")
    
    # Restored to the clean global client with the working milliseconds timeout fix
    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(timeout=90000)
    )
    
    prompt = f"""
    Analyze the following brand context for a Google Ads account:
    - Brand Name: {brand_name}
    - Core Offering: {core_offering}
    - Target Landing Page context: {landing_page}
    
    Identify brand variants, competitor brands, core protected terms, and completely irrelevant angles/themes.
    """
    
    try:
        # Restored your original high-quality Pydantic schema generation configuration
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
        
        if not response or not response.text:
            raise ValueError("The Gemini API returned an empty response string.")

        # Strip potential markdown blocks (```json ... ```) to prevent Pydantic parsing crashes
        clean_text = response.text.strip()
        if clean_text.startswith("```"):
            clean_text = re.sub(r"^```json\s*|\s*```$", "", clean_text, flags=re.MULTILINE).strip()
            
        # Parse output safely via validation schema
        return BrandProfile.model_validate_json(clean_text).model_dump()
        
    except Exception as e:
        # Removed the silent fallback. If it breaks, we want to see the exact error message text.
        raise RuntimeError(f"Gemini processing failure: {str(e)}")
