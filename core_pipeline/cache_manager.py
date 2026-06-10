import os
import json
import time

CACHE_FILE = "brand_blueprints_cache.json"


# -----------------------------
# INTERNAL LOADER (single source of truth)
# -----------------------------
def _load_cache():
    """
    Loads cache safely with retry protection for Streamlit file locking.
    """
    if not os.path.exists(CACHE_FILE):
        return {}

    for _ in range(5):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)

        except (json.JSONDecodeError, PermissionError):
            time.sleep(0.1)

    return {}


# -----------------------------
# CACHE READ
# -----------------------------
def get_cached_profile_names() -> list:
    """
    Returns all stored profile keys.
    """
    return list(_load_cache().keys())


def get_profile_by_name(profile_name: str) -> dict:
    """
    Returns blueprint for a given profile.
    """
    cache = _load_cache()
    return cache.get(profile_name, {})


# -----------------------------
# CACHE WRITE (SAFE)
# -----------------------------
def save_profile_to_cache(brand_name: str, core_offering: str, blueprint_data: dict):
    """
    Writes blueprint safely with retry + atomic overwrite protection.
    """

    cache = _load_cache()

    key = f"{brand_name.strip()} | {core_offering.strip()}"

    cache[key] = {
        "metadata": {
            "brand_name": brand_name,
            "core_offering": core_offering
        },
        "blueprint": blueprint_data
    }

    # safer write loop
    for _ in range(5):
        try:
            tmp_file = CACHE_FILE + ".tmp"

            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(cache, f, indent=2)

            # atomic replace (prevents corruption on crash/reload)
            os.replace(tmp_file, CACHE_FILE)
            break

        except PermissionError:
            time.sleep(0.1)

        except Exception as e:
            raise RuntimeError(f"Cache write failed: {e}")
