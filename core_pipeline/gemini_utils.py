import json
import time
import random
from google.genai import errors


def gemini_json(client, model, system_prompt, payload, temperature=0.1, retries=3):
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
            return json.loads(response.text)

        except errors.APIError as e:
            code = getattr(e, "code", None) or 0

            if code in [429, 503] and attempt < retries - 1:
                time.sleep(1.2 + random.uniform(0, 0.6))
                continue

            raise RuntimeError(f"Gemini error ({code}): {e}")

        except json.JSONDecodeError:
            if attempt < retries - 1:
                continue
            return {"term_data": []}
