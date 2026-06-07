import os
import json

CACHE_FILE = "brand_blueprints_cache.json"

def load_entire_cache() -> dict:
    """
    Reads the raw JSON storage file from disk. 
    Returns an empty dictionary if the file doesn't exist yet.
    """
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r") as f:
                return json.load(f)
        except json.JSONDecodeError:
            return {}
    return {}

def get_cached_profile_names() -> list:
    """
    Gathers all saved keys to populate your Streamlit dropdown menu.
    Transforms raw technical identifiers into clean, user-friendly names.
    """
    cache = load_entire_cache()
    # Returns a clean list of human-readable options, e.g., ["Acme Corp | Luxury Sofas"]
    return list(cache.keys())

def get_profile_by_name(profile_name: str) -> dict:
    """
    Retrieves the exact blueprint ruleset when you select 
    a client from the dropdown menu.
    """
    cache = load_entire_cache()
    return cache.get(profile_name, {})

def save_profile_to_cache(brand_name: str, core_offering: str, blueprint_data: dict):
    """
    Saves your approved modifications. It creates a human-friendly 
    lookup key combining the Brand and the Offering to keep things organized.
    """
    cache = load_entire_cache()
    
    # This creates a user-friendly English label for your dropdown menus
    dropdown_label = f"{brand_name.strip()} | {core_offering.strip()}"
    
    # Package the metadata and your approved ruleset together
    cache[dropdown_label] = {
        "metadata": {
            "brand_name": brand_name,
            "core_offering": core_offering
        },
        "blueprint": blueprint_data
    }
    
    # Write it back to your hidden local file
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=4)
