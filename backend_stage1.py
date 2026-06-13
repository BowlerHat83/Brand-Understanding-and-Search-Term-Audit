import json
import google.generativeai as genai
import google.api_core.exceptions as google_exceptions
from backend_config import initialize_gemini

def analyze_brand_profile(brand_name, core_offering, landing_page=None):
    """
    Stage 1 Backend: Pure context-driven mapping. Explicitly ignores live URL 
    crawling variables to maximize script delivery speed.
    """
    initialize_gemini()
    try:
        model = genai.GenerativeModel(
            model_name='gemini-1.5-flash',
            generation_config={"response_mime_type": "application/json"}
        )
        
        prompt = f"""
        You are an expert Google Ads PPC Architect. Base your analysis on these precise brand variables:
        - Brand Name: {brand_name}
        - Core Offering Context: {core_offering}
        
        Identify common variations, top market competitors, exact target words that must never be blocked, and irrelevant industries/niches. 
        Return raw stringified JSON (no markdown wrappers).
        
        JSON Layout Pattern:
        {{
          "brand_variants": ["{brand_name.lower()}", "{brand_name.replace(' ', '')}"],
          "competitor_brands": ["competitor a", "competitor b"],
          "protected_terms": ["{core_offering.lower()}"],
          "irrelevant_niches": ["cheap", "free", "diy", "jobs"]
        }}
        """
        
        response = model.generate_content(prompt)
        return json.loads(response.text)
        
    except google_exceptions.ResourceExhausted:
        return {"error": "🚨 ERR_GEMINI_QUOTA_EXCEEDED: Rate limit reached. Wait 60 seconds."}
    except Exception as e:
        return {"error": f"🚨 ERR_STAGE1_FAULT: System processing error. Details: {str(e)}"}
