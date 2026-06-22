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
    irrelevant_terms: List[str] = Field(description="Concepts, search angles, target intents, or specific bulk negative themes to discard.")
    target_languages: List[str] = Field(description="The explicit language(s) allowed for targeting (e.g., ['English']).")

def run_brand_audit(brand_name: str, core_offering: str, landing_page: str, target_language: str = "English") -> dict:
    """
    Analyzes initial brand positioning and returns a structured profile ruleset.
    Hardened against Streamlit network drops using text-clipping.
    """
    api_key = st.secrets.get("GEMINI_API_KEY")
    
    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(timeout=30000) # Hard 30-second gateway guard
    )
    
    # Text clipping to strip heavy DOM/HTML tracking scripts and keep calls under 5 seconds
    cleaned_landing_page = str(landing_page)[:12000].strip()
    
    prompt = f"""
    Analyze the following brand context for a Google Ads account:
    - Brand Name: {brand_name}
    - Core Offering: {core_offering}
    - Target Landing Page context: {cleaned_landing_page}
    - Primary Target Language: {target_language}
    
    Identify brand variants, competitor brands, core protected terms, and completely irrelevant angles/themes.
    """
    
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=(
                    "You are a meticulous PPC Strategy architect. Extract definitive brand guidelines.\n"
                    f"CRITICAL CONSTRAINT: The target market exclusively uses {target_language}. "
                    f"Any search phrases or terms in languages other than {target_language} "
                    "MUST be aggressively classified as completely irrelevant."
                ),
                response_mime_type="application/json",
                response_schema=BrandProfile,
                temperature=0.1
            )
        )
        
        if not response or not response.text:
            raise ValueError("The Gemini API returned an empty response string.")

        clean_text = response.text.strip()
        if clean_text.startswith("```"):
            clean_text = re.sub(r"^```json\s*|\s*```$", "", clean_text, flags=re.MULTILINE).strip()
            
        return BrandProfile.model_validate_json(clean_text).model_dump()
        
    except Exception as e:
        raise RuntimeError(f"Gemini processing failure: {str(e)}")


def route_bulk_keywords(bulk_text: str, current_profile: dict, target_language: str = "English") -> dict:
    """
    Takes a raw bulk list of historical negative terms and automatically routes each 
    one into the correct BrandProfile bucket based on the existing audit context.
    """
    api_key = st.secrets.get("GEMINI_API_KEY")
    client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=20000))
    
    # Strip match type notation dynamically to extract root intent
    terms_list = [
        t.strip().replace("[", "").replace("]", "").replace('"', '') 
        for t in bulk_text.split("\n") if t.strip()
    ]
    
    prompt = f"""
    You are a PPC data sorting engine. Look at this current Brand Profile strategy context:
    {current_profile}
    
    Now, look at this list of raw keywords/negatives:
    {terms_list}
    
    Categorize EVERY single keyword from the list into exactly one of these 5 categories based on the strategy context:
    - brand_variants (Misspellings, abbreviations, or variations of the brand name)
    - competitors (Competitor names, alternative companies, or competitor products)
    - protected_terms (High-intent commercial terms essential to target/save)
    - irrelevant_terms (Irrelevant concepts, foreign languages, themes, junk phrases)
    - target_languages (Explicit target language identifiers only)
    
    Return the result strictly adhering to the original BrandProfile JSON structure.
    """
    
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=(
                    f"You are an automated categorization router. Target language is {target_language}. "
                    "Sort terms strictly based on intent mapping context provided."
                ),
                response_mime_type="application/json",
                response_schema=BrandProfile,
                temperature=0.0 # Force deterministic sorting execution
            )
        )
        return BrandProfile.model_validate_json(response.text.strip()).model_dump()
    except Exception as e:
        raise RuntimeError(f"Bulk routing failure: {str(e)}")
