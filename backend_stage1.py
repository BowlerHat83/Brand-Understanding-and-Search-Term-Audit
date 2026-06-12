import json
import google.generativeai as genai
import google.api_core.exceptions as google_exceptions
from backend_config import initialize_gemini

def analyze_brand_profile(brand_name, core_offering, landing_page):
    """
    Stage 1 Backend: Formulates the baseline Brand Profile using gemini-1.5-flash.
    """
    initialize_gemini()
    try:
        model = genai.GenerativeModel(
            model_name='gemini-1.5-flash',
            generation_config={"response_mime_type": "application/json"}
        )
        
        prompt = f"""
        You are an expert Google Ads PPC Architect. Analyze this brand profile and return a clean JSON object.
        
        Brand Name: {brand_name}
        Core Offering: {core_offering}
        Landing Page Context URL: {landing_page}
        
        CRITICAL PROCESSING RULES:
        1. Base your primary parameters on the Brand Name and Core Offering provided.
        2. Attempt to use your URL context processing to enrich data. If the URL is broken or blocked, ignore it completely and use the text inputs. Do not fail.
        3. Do not wrap output in markdown code blocks. Return raw JSON.
        
        JSON Structure Format:
        {{
          "brand_variants": ["variant1", "variant2"],
          "competitor_brands": ["competitor1", "competitor2"],
          "protected_terms": ["must never block term1"],
          "irrelevant_niches": ["niche1"]
        }}
        """
        
        response = model.generate_content(prompt)
        return json.loads(response.text)
        
    except google_exceptions.ResourceExhausted:
        return {"error": "🚨 ERR_GEMINI_QUOTA_EXCEEDED: Rate limit or daily token quota reached. Please wait a minute."}
    except google_exceptions.GoogleAPIError as e:
        return {"error": f"🚨 ERR_GEMINI_SYSTEM_ERROR: Gemini API encountered an error. Details: {str(e)}"}
    except Exception as e:
        return {"error": f"🚨 ERR_STAGE1_FAULT: Processing fault. Details: {str(e)}"}
