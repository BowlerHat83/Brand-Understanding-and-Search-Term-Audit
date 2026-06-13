import json
import google.generativeai as genai
import google.api_core.exceptions as google_exceptions
from backend_config import initialize_gemini

def analyze_brand_profile(brand_name, core_offering, landing_page):
    """
    Stage 1 Backend: High-speed text generation with local Python parsing.
    Bypasses the slow API JSON schema validation engine.
    """
    initialize_gemini()
    try:
        model = genai.GenerativeModel(model_name='gemini-1.5-flash')
        
        prompt = f"""
        You are an expert Google Ads PPC Architect. Synthesize a core PPC keyword taxonomy based on this brand data:
        - Brand Name: {brand_name}
        - Core Offering: {core_offering}
        - Landing Page: {landing_page}
        
        Analyze the relationship between the brand name and the core offering. 
        Identify immediate variations of the brand name, potential broad market competitor terms to look out for, exact target terms that must never be blocked, and generic irrelevant industries/niches that clearly mismatch this offering.
        
        CRITICAL: Your response must be raw text formatted exactly like a clean JSON object. Do not wrap it in markdown code blocks like ```json. 
        
        Expected Output Format:
        {{
          "brand_variants": ["{brand_name.lower()}"],
          "competitor_brands": [],
          "protected_terms": ["{core_offering.lower()}"],
          "irrelevant_niches": []
        }}
        """
        
        # High-speed raw content generation
        response = model.generate_content(prompt)
        clean_text = response.text.strip()
        
        # Strip out any markdown blocks if the model accidentally includes them
        if clean_text.startswith("```"):
            clean_text = clean_text.split("\n", 1)[1].rsplit("\n", 1)[0].strip()
            if clean_text.startswith("json"):
                clean_text = clean_text.split("\n", 1)[1].strip()
                
        return json.loads(clean_text)
        
    except google_exceptions.ResourceExhausted:
        return {"error": "🚨 ERR_GEMINI_QUOTA_EXCEEDED: Rate limit reached. Wait 60 seconds."}
    except Exception as e:
        # Fallback dictionary to ensure the app never freezes or crashes
        return {
            "brand_variants": [brand_name.lower(), brand_name.replace(" ", "").lower()],
            "competitor_brands": ["competitor check required"],
            "protected_terms": [core_offering.lower()],
            "irrelevant_niches": ["free", "cheap", "diy", "jobs"]
        }
