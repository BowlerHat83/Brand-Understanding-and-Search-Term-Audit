import os
import re
import streamlit as st
from pydantic import BaseModel, Field
from typing import List
import google.genai as genai
from google.genai import types
# Import the explicit synchronous HTTP transport layer to prevent gateway drops
from google.genai._http_client import HttpClient

# Define the structured output format for the brand profile
class BrandProfile(BaseModel):
    brand_variants: List[str] = Field(description="Variations, misspellings, abbreviations of the brand name.")
    competitors: List[str] = Field(description="Known competitor brand names or companies matching this space.")
    protected_terms: List[str] = Field(description="High-intent commercial terms essential to save (e.g., service buy words).")
    irrelevant_terms: List[str] = Field(description="Concepts, search angles, or target intents completely disconnected from the offering.")

def run_brand_audit(brand_name: str, core_offering: str, landing_page: str) -> dict:
    """
    Analyzes brand positioning and returns a structured profile ruleset.
    Patched with explicit synchronous HTTP client overrides to prevent Error 004 gateway drops.
    """
    # Securely retrieve the token directly from Streamlit secrets
    api_key = st.secrets.get("GEMINI_API_KEY")
    
    # HARD PATCH: Force the genai client to run over a strict, standard synchronous
    # HTTP transport mechanism rather than allowing it to pick up erratic environment-dependent loops.
    sync_http_client = HttpClient(
        api_key=api_key,
        http_options=types.HttpOptions(timeout=45000) # Dropped to 45s to cleanly clear Streamlit boundaries
    )
    
    # Pass our explicitly configured transport engine into the main client wrapper
    client = genai.Client(api_key=api_key, _http_client=sync_http_client)
    
    prompt = f"""
    Analyze the following brand context for a Google Ads account:
    - Brand Name: {brand_name}
    - Core Offering: {core_offering}
    - Target Landing Page context: {landing_page}
    
    Identify brand variants, competitor brands, core protected terms, and completely irrelevant angles/themes.
    """
    
    try:
        # High-quality structural evaluation execution using the defined Pydantic blueprint
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

        # Clean markdown wrappers out of the string context safely
        clean_text = response.text.strip()
        if clean_text.startswith("```"):
            clean_text = re.sub(r"^```json\s*|\s*```$", "", clean_text, flags=re.MULTILINE).strip()
            
        # Parse output safely via validation schema
        return BrandProfile.model_validate_json(clean_text).model_dump()
        
    except Exception as e:
        # Raising raw error text explicitly back up to the frontend UI blocks
        raise RuntimeError(f"Gemini processing failure: {str(e)}")
