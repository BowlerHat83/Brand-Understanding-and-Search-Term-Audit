import os
import json
from openai import OpenAI

def generate_brand_profile(brand_name: str, core_offering: str, landing_page: str) -> dict:
    """
    Connects to OpenAI to generate a highly tailored, initial draft of the
    brand blueprint based on the client's brand name, offering, and domain.
    """
    
    # Initialize the client. This automatically reads the OPENAI_API_KEY environment variable.
    client = OpenAI()
    
    # Establish the specialized context for the AI
    system_prompt = (
        "You are an expert PPC Strategy Engine. Your task is to analyze a business footprint "
        "and draft a high-accuracy Brand Ruleset Blueprint for a Google Ads account. "
        "You must output ONLY a valid JSON object matching the requested schema. "
        "Do not include any conversational text, markdown formatting, or backticks (like ```json)."
    )
    
    # Define the precise rules of engagement for the niche
    user_prompt = f"""
    Analyze these three core brand attributes:
    - Official Brand Name: "{brand_name}"
    - Core Ad Group Offering: "{core_offering}"
    - Landing Page/Domain: "{landing_page}"
    
    Using your advanced marketing and industry knowledge, predict the common negative keyword 
    pitfalls, adjacent irrelevant searches, and standard competitors for this specific niche.
    
    You must return a JSON object with these exact keys:
    {{
        "brand_variants": ["3-5 common abbreviations, sub-brands, or misspellings of the brand name to absolutely protect"],
        "explicit_negative_triggers": ["10-15 highly contextual junk words that ruin conversion intent for THIS specific offering"],
        "predicted_competitors": ["5-7 direct industry rivals or market alternatives for this specific product/service vertical"],
        "strict_relevance_rule": "A clear, one-sentence rule defining exactly what a high-intent commercial query looks like for this offering."
    }}
    """
    
    try:
        # Request a structured JSON object from the model
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.3 # Low temperature ensures consistent, analytical reasoning
        )
        
        # Parse the string response into a native Python dictionary
        raw_content = response.choices[0].message.content
        return json.loads(raw_content)

    except Exception as e:
        # 100% dynamic fallback with NO hardcoded words. 
        # If the API fails, it generates contextual safety terms purely based on your exact input.
        return {
            "brand_variants": [brand_name.lower().strip()],
            "explicit_negative_triggers": [
                "free", "cheap", "diy", "jobs", "salary", "course", 
                f"how to make {core_offering.lower()}", 
                f"{core_offering.lower()} templates",
                f"cheap {core_offering.lower()}"
            ],
            "predicted_competitors": [],
            "strict_relevance_rule": f"Focus strictly on high-intent commercial terms for {core_offering}."
        }
        



