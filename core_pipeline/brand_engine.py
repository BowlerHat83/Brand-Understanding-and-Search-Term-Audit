import json
from google import genai
from google.genai import errors
from . import cache_manager as cm

# Precision Strategic Prompt
BRAND_BLUEPRINT_SYSTEM_PROMPT = (
    "You are an expert PPC Core Strategist. Your job is to analyze a brand's core offering "
    "and landing page domain to establish strict, conservative semantic boundaries for search terms.\n\n"
    "CRITICAL GENERATION RULES:\n"
    "1. BRAND VARIANTS: Extract the core brand name and common misspellings/variations.\n"
    "2. EXPLICIT NEGATIVE TRIGGERS: Identify high-risk intent vectors that mean waste for this specific business model (e.g., if B2B, look for jobs, resume, DIY, cheap, free, undergraduate, courses).\n"
    "3. PREDICTED COMPETITORS: List real, highly probable market competitors offering this exact service.\n"
    "4. STRICT RELEVANCE RULE: Write a one-sentence 'Golden Rule' that a human auditor can use to judge if a search phrase has valid commercial intent.\n\n"
    "Output MUST be a strict JSON object matching the requested structure perfectly."
)

def generate_brand_profile(brand_name: str, core_offering: str, landing_page: str) -> dict:
    """
    Analyzes brand parameters and generates a strategic blueprint using native Gemini client rules.
    """
    # Initialize official Gemini client (automatically inherits GEMINI_API_KEY from Streamlit secrets)
    client = genai.Client()
    
    user_prompt = f"""
    Analyze the following business entity details to build a strict negative and positive relevance framework:
    - Brand Name: {brand_name}
    - Ad Group Core Offering Target: {core_offering}
    - Target Landing Page context reference: {landing_page}
    
    Provide the output in a strict JSON format with these exact keys:
    "brand_variants" (array of strings),
    "explicit_negative_triggers" (array of strings),
    "predicted_competitors" (array of strings),
    "strict_relevance_rule" (string)
    """
    
    try:
        # Native Gemini JSON call matching audit_engine
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=user_prompt,
            config=genai.types.GenerateContentConfig(
                system_instruction=BRAND_BLUEPRINT_SYSTEM_PROMPT,
                response_mime_type="application/json",
                temperature=0.2
            ),
        )
        
        # Parse output safely
        blueprint_data = json.loads(response.text)
        return blueprint_data
        
    except errors.APIError as api_err:
        # Pass structured error codes up to the UI layout safely
        if api_err.code == 429:
            raise RuntimeError("ERR_GEMINI_QUOTA_EXCEEDED: Generation rate limits hit.")
        else:
            raise RuntimeError(f"ERR_GEMINI_SERVER_BREAK ({api_err.code}): Engine failed.")
            
    except Exception as e:
        # Fallback empty profile layout template to keep pipeline from breaking if parsing hits a snag
        return {
            "brand_variants": [brand_name.strip()],
            "explicit_negative_triggers": ["jobs", "salary", "free", "diy", "download", "cheap"],
            "predicted_competitors": [],
            "strict_relevance_rule": f"Must explicitly indicate direct commercial intent to purchase or inquire about {core_offering}."
        }
