import os
import google.generativeai as genai

def initialize_gemini():
    """Initializes and returns the Gemini API framework using Streamlit Secrets or Environment Variables."""
    # Check for Streamlit's secrets management first, then fallback to standard environment vars
    api_key = os.getenv("GEMINI_API_KEY")
    
    if api_key:
        genai.configure(api_key=api_key)
    else:
        # If neither are found, let the system know so it doesn't fail silently later
        print("⚠️ WARNING: GEMINI_API_KEY not found in environment variables.")
