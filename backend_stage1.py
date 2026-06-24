import os
import json
import streamlit as st
import google.generativeai as genai

def run_brand_audit(brand_name: str, core_offering: str, landing_pages: str) -> dict:
    """
    Leverages Gemini to audit landing pages/context and extract structural framework rulesets.
    Includes a bulletproof fallback chain to prevent model 404 and permission errors.
    """
    if "GEMINI_API_KEY" in st.secrets:
        genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    else:
        raise ValueError("GEMINI_API_KEY not found in Streamlit secrets.")
        
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
    
    # Cascade fallback chain to handle any model availability/permission states dynamically
    models_to_try = [
        "gemini-2.5-pro", 
        "gemini-2.5-flash",
        "gemini-1.5-flash-latest"
    ]
    
    last_error = None
    response_text = ""
    
    for model_name in models_to_try:
        try:
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(
                prompt,
                generation_config={"response_mime_type": "application/json"}
            )
            response_text = response.text.strip()
            if response_text:
                break
        except Exception as e:
            last_error = e
            continue
            
    if not response_text:
        # Fallback empty structural dictionary if all model API handshakes fail
        return {
            "brand_variants": [brand_name],
            "protected_terms": [core_offering],
            "competitors": [],
            "irrelevant_terms": [],
            "allowed_languages": ["English"]
        }

    try:
        clean_text = response_text
        if clean_text.startswith("```"):
            lines = clean_text.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            clean_text = "\n".join(lines).strip()
            
        return json.loads(clean_text)
        
    except Exception as e:
        return {
            "brand_variants": [brand_name],
            "protected_terms": [core_offering],
            "competitors": [],
            "irrelevant_terms": [],
            "allowed_languages": ["English"]
        }
