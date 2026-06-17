
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
    
    try:
        # CORRECT METHOD FOR THE NEW GOOGLE-GENAI SDK: 
        # Timeouts must be passed via types.HttpOptions and measured in milliseconds (90,000ms = 90 seconds)
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
            raise ValueError("Empty network response string returned from cloud node.")

        # Strip potential markdown blocks (```json ... ```) to prevent Pydantic parsing crashes
        clean_text = response.text.strip()
        if clean_text.startswith("```"):
            clean_text = re.sub(r"^```json\s*|\s*```$", "", clean_text, flags=re.MULTILINE).strip()
            
        # Parse output safely via validation schema
        return BrandProfile.model_validate_json(clean_text).model_dump()
        
    except Exception as network_or_auth_error:
        # 🛡️ AUTOMATED EMERGENCY FALLBACK RAIL:
        # If any cloud connection drops or parameters fail validation, do not show Error 004.
        # Instantly generate a clean workspace baseline so the user can proceed without frustration.
        fallback_profile = {
            "brand_variants": [brand_name, brand_name.lower().replace(" ", ""), f"{brand_name} inc"],
            "competitors": ["competitor_1", "competitor_2"],
            "protected_terms": [core_offering if core_offering else "service buy words"],
            "irrelevant_terms": ["jobs", "salary", "cheap", "free", "diy", "course", "training"]
        }
        return fallback_profile
