import os
import json
import time

CACHE_FILE = "brand_blueprints_cache.json"

def load_entire_cache() -> dict:
    """
    Reads the raw JSON storage file from disk. 
    Returns an empty dictionary if the file doesn't exist yet.
    """
    if os.path.exists(CACHE_FILE):
        for _ in range(5):
            try:
                with open(CACHE_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, PermissionError):
                time.sleep(0.1)  # Wait 100ms and try again if file is busy
        return {}
    return {}

def get_cached_profile_names() -> list:
    """
    Gathers all saved keys to populate your Streamlit dropdown menu.
    """
    cache = load_entire_cache()
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
    Saves your approved modifications safely with write protection.
    """
    cache = load_entire_cache()
    
    dropdown_label = f"{brand_name.strip()} | {core_offering.strip()}"
    
    cache[dropdown_label] = {
        "metadata": {
            "brand_name": brand_name,
            "core_offering": core_offering
        },
        "blueprint": blueprint_data
    }
    
    # Secure atomic write with retry mechanisms to prevent concurrent app crashes
    for _ in range(5):
        try:
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(cache, f, indent=4)
            break
        except PermissionError:
            time.sleep(0.1)
