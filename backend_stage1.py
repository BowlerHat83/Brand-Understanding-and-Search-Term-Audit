import os
import re
import json
import streamlit as st
import google.genai as genai
from google.genai import types

def run_brand_audit(brand_name: str, core_offering: str, landing_page: str) -> dict:
    """
    Analyzes brand positioning and returns a structured profile ruleset.
    Optimized for high-speed raw JSON decoding.
    """
    # Securely retrieve the upgraded token directly from Streamlit secrets
    api_key = st.secrets.get("GEMINI_API_KEY")
    
    try:
        # Pass timeout cleanly in milliseconds (90 seconds)
        client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=90000)
        )
        
        # We instruct the model to return a strict, minimal JSON map directly.
        # This reduces processing overhead.
        prompt = f"""
        You are a meticulous PPC Strategy architect. Extract definitive brand guidelines.
        Analyze the following brand context for a Google Ads account and return a JSON object matching this exact format:
        {{
            "brand_variants": ["Variations, misspellings, abbreviations of the brand name"],
            "competitors": ["Known competitor brand names or companies matching this space"],
            "protected_terms": ["High-intent commercial terms essential to save like service buy words"],
            "irrelevant_terms": ["Concepts, search angles, or target intents completely disconnected from the offering"]
        }}

        Context Data:
        - Brand Name: {brand_name}
        - Core Offering: {core_offering}
        - Target Landing Page context: {landing_page}

        Be highly specific; do not use vague categories. Return ONLY the JSON object.
        """
        
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.1
            )
        )
        
        if not response or not response.text:
            raise ValueError("Empty network response string returned from cloud node.")

        clean_text = response.text.strip()
        if clean_text.startswith("```"):
            clean_text = re.sub(r"^```json\s*|\s*```$", "", clean_text, flags=re.MULTILINE).strip()
            
        # High-speed native parsing
        parsed_json = json.loads(clean_text)
        
        # Ensure all key structural lists exist to avoid upstream errors
        return {
            "brand_variants": parsed_json.get("brand_variants", [brand_name]),
            "competitors": parsed_json.get("competitors", []),
            "protected_terms": parsed_json.get("protected_terms", [core_offering]),
            "irrelevant_terms": parsed_json.get("irrelevant_terms", [])
        }
        
    except Exception as e:
        # Fallback template with contextual data populated if the network stalls
        fallback_profile = {
            "brand_variants": [brand_name, brand_name.lower().replace(" ", ""), f"{brand_name} PPC"],
            "competitors": ["Add Competitor A", "Add Competitor B"],
            "protected_terms": [core_offering if core_offering else "Core Services"],
            "irrelevant_terms": ["jobs", "salary", "cheap", "free", "diy", "course", "training"]
        }
        return fallback_profile
