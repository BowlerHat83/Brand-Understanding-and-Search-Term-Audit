import os
import json
import streamlit as st
import google.generativeai as genai

def run_brand_audit(brand_name: str, core_offering: str, landing_pages: str) -> dict:
    """
    Leverages Gemini to audit landing pages/context and extract structural framework rulesets.
    """
    # Initialize the Gemini API client using Streamlit secrets
    if "GEMINI_API_KEY" in st.secrets:
        genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    else:
        raise ValueError("GEMINI_API_KEY not found in Streamlit secrets.")
        
    model = genai.GenerativeModel('gemini-1.5-pro') # Or your preferred stable model
    
    prompt = f"""
    You are an expert Google Ads Specialist. Analyze the following business details to build a strict negative keyword safety framework.
    
    Brand Name: {brand_name}
    Core Offering: {core_offering}
    Context/Landing Pages: {landing_pages}
    
    Provide your output strictly in JSON format with the following exact keys:
    - "brand_variants": [list of close variations, common misspellings of {brand_name}]
    - "protected_terms": [list of core offering keywords that must NEVER be negated]
    - "competitors": [list of key competitor brand names identified or inferred]
    - "irrelevant_terms": [list of concepts, industries, or job-related search terms completely unrelated to this offering]
    - "allowed_languages": ["English"]
    
    Do not include markdown formatting or wrappers outside of the raw JSON object string.
    """
    
    response = model.generate_content(prompt)
    
    # Strip away any potential markdown code blocks if the model returned them
    clean_text = response.text.strip().lstrip("```json").rstrip("```")
    
    try:
        profile_data = json.loads(clean_text)
        return profile_data
    except Exception as e:
        # Fallback empty structural dictionary if parsing fails
        return {
            "brand_variants": [brand_name],
            "protected_terms": [core_offering],
            "competitors": [],
            "irrelevant_terms": [],
            "allowed_languages": ["English"]
        }
