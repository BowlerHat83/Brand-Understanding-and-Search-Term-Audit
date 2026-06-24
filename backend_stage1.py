import os
import json
import streamlit as st
import google.generativeai as genai

def run_brand_audit(brand_name: str, core_offering: str, landing_pages: str) -> dict:
    """
    Leverages Gemini 2.5 Pro to audit landing pages/context and extract structural framework rulesets.
    """
    # Initialize the Gemini API client using Streamlit secrets
    if "GEMINI_API_KEY" in st.secrets:
        genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    else:
        raise ValueError("GEMINI_API_KEY not found in Streamlit secrets.")
        
    # Upgrade to the fully supported production-grade reasoning model
    model = genai.GenerativeModel('gemini-2.5-pro')
    
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
    
    try:
        # Enforce structured JSON generation configurations for seamless parsing
        response = model.generate_content(
            prompt,
            generation_config={"response_mime_type": "application/json"}
        )
        
        clean_text = response.text.strip()
        
        # Safe clean-up for code block wrappers if generated
        if clean_text.startswith("```"):
            lines = clean_text.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            clean_text = "\n".join(lines).strip()
            
        return json.loads(clean_text)
        
    except Exception as e:
        # Fallback empty structural dictionary if parsing or API call fails
        return {
            "brand_variants": [brand_name],
            "protected_terms": [core_offering],
            "competitors": [],
            "irrelevant_terms": [],
            "allowed_languages": ["English"]
        }
