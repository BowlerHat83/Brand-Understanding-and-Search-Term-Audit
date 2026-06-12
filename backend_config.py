import os
import google.generativeai as genai

def initialize_gemini():
    """Initializes and returns the Gemini API framework using Streamlit Secrets or Environment Variables."""
    if "GEMINI_API_KEY" in os.environ:
        genai.configure(api_key=os.environ["GEMINI_API_KEY"])
    elif "GEMINI_API_KEY" in os.get_env(): # Fallback check
        genai.configure(api_key=os.get_env()["GEMINI_API_KEY"])
