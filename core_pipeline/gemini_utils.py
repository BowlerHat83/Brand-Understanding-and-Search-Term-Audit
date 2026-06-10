import json
import time
import random
from google.genai import errors


# -----------------------------
# CORE GEMINI WRAPPER
# -----------------------------
def gemini_json(
    client,
    model,
    system_prompt,
    payload,
    temperature=0.1,
    retries=3
):
    """
    Robust Gemini JSON wrapper with:
    - exponential backoff
    - reduced retry waste
    - stricter failure handling
    """

    for attempt in range(retries):
        try:
            response = client.models.generate_content(
                model=model,
                contents=payload,
                config={
                    "system_instruction": system_prompt,
                    "response_mime_type": "application/json",
                    "temperature": temperature,
                },
            )

            text = response.text.strip()

            # Fast-path: avoid unnecessary json.loads retries
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                # Only retry if response is clearly malformed
                if attempt < retries - 1:
                    time.sleep(0.5 + random.uniform(0, 0.3))
                    continue
                return {"term_data": []}

        except errors.APIError as e:
            code = getattr(e, "code", None)

            # Rate limit / overload → exponential backoff
            if code in (429, 503) and attempt < retries - 1:
                sleep_time = (1.5 ** attempt) + random.uniform(0, 0.4)
                time.sleep(sleep_time)
                continue

            raise RuntimeError(f"Gemini API error ({code}): {e}")

        except Exception as e:
            # Fail fast for unknown errors (don’t waste retries)
            raise RuntimeError(f"Gemini unexpected error: {e}")

    # Safe fallback (prevents pipeline breakage)
    return {"term_data": []}
