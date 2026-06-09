import json
import time
import random
from google import genai
from google.genai import errors

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
    Equipped with exponential backoff to handle temporary 429 and 503 limits safely.
    """
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
    
    max_retries = 5
    base_delay = 2.0
    
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=user_prompt,
                config=genai.types.GenerateContentConfig(
                    system_instruction=BRAND_BLUEPRINT_SYSTEM_PROMPT,
                    response_mime_type="application/json",
                    temperature=0.2
                ),
            )
            return json.loads(response.text)
            
        except errors.APIError as api_err:
            err_code = getattr(api_err, 'code', None) or "UNKNOWN"
            err_message = getattr(api_err, 'message', str(api_err))
            
            if err_code in [429, 503] or "429" in err_message or "503" in err_message:
                if attempt < max_retries - 1:
                    sleep_time = (base_delay * (2 ** attempt)) + random.uniform(0, 1)
                    time.sleep(sleep_time)
                    continue
                else:
                    raise RuntimeError(f"ERR_GEMINI_QUOTA_EXCEEDED: Generation limits hit permanently after {max_retries} attempts.")
            raise RuntimeError(f"ERR_GEMINI_SERVER_BREAK ({err_code}): {err_message}")
                
        except json.JSONDecodeError:
            break
            
        except Exception as e:
            raise e

    return {
        "brand_variants": [brand_name.strip()],
        "explicit_negative_triggers": ["jobs", "salary", "free", "diy", "download", "cheap"],
        "predicted_competitors": [],
        "strict_relevance_rule": f"Must explicitly indicate direct commercial intent to purchase or inquire about {core_offering}."
    }
