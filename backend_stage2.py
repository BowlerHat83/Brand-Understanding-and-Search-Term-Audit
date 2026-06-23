import re
from collections import Counter
import google.generativeai as genai
import streamlit as st
import json

def classify_terms_batch(terms: list, brand_profile: dict) -> list:
    """
    Sends a batch of search terms to Gemini to classify based on established brand truth rulesets.
    Optimized for raw execution speed using native structured JSON outputs and constrained token limits.
    """
    if "GEMINI_API_KEY" in st.secrets:
        genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    
    model = genai.GenerativeModel('gemini-2.5-flash')
    
    # Format the ruleset for the model context
    rules_context = json.dumps(brand_profile, indent=2)
    
    prompt = f"""
    You are an automated PPC audit script. Classify the following search terms based strictly on these rules:
    {rules_context}
    
    Terms to classify:
    {json.dumps(terms)}
    
    Respond STRICTLY with a valid JSON array of objects. Each object must have these exact keys:
    - "search_term": (string matching the input exactly)
    - "classification": (strictly choose one: "relevant", "irrelevant", or "review")
    - "confidence": (float between 0.00 and 1.00)
    - "reason": (string explaining why - MUST BE 5 WORDS OR LESS)
    
    CRITICAL SPEED RULE: Keep the 'reason' ultra-concise. Do not exceed 5 words under any circumstance.
    """
    
    try:
        # High-Velocity Tier Configuration: Forces native infrastructure JSON compilation
        response = model.generate_content(
            prompt,
            generation_config={"response_mime_type": "application/json"}
        )
        
        # Strip away any stray whitespace characters or wrapper anomalies safely
        clean_text = response.text.strip()
        if clean_text.startswith("```"):
            clean_text = re.sub(r'^
http://googleusercontent.com/immersive_entry_chip/0
