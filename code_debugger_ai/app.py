import json
import os
import time

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
from google import genai
from google.genai import types

from chatbot_config import MODEL_NAME, SYSTEM_PROMPT

load_dotenv()

app = Flask(__name__)

API_KEY = os.getenv("GEMINI_API_KEY")
if not API_KEY:
    raise RuntimeError("GEMINI_API_KEY is not configured.")

client = genai.Client(api_key=API_KEY)


def generate_debug_response(language, code, error_message="", expected_behavior=""):
    prompt = f"""
Analyze the following programming code as a Code Debugger AI.

Programming language: {language}

Code:
```{language}
{code}
```

Reported error, if any:
{error_message or "No error message provided."}

Expected behavior:
{expected_behavior or "Not provided."}

Return ONLY valid JSON using exactly these keys:
{{
  "summary": "short diagnosis",
  "errors": [
    {{
      "title": "error title",
      "explanation": "clear explanation",
      "line_or_area": "line number or code area if identifiable"
    }}
  ],
  "fixed_code": "complete corrected code",
  "explanation": ["step 1", "step 2"],
  "best_practices": ["tip 1", "tip 2"]
}}

Rules:
- Do not invent errors that are not supported by the code.
- If the code is already correct, say so and keep fixed_code unchanged.
- Preserve the user's intended behavior whenever possible.
- Make fixed_code complete and runnable.
- Escape JSON characters correctly.
"""

    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        response_mime_type="application/json",
        temperature=0.2,
    )

    retryable_statuses = {429, 500, 502, 503, 504}
    last_error = None

    for attempt in range(4):
        try:
            response = client.models.generate_content(
                model=MODEL_NAME,
                contents=prompt,
                config=config,
            )
            text = (response.text or "").strip()
            if not text:
                raise ValueError("Gemini returned an empty response.")

            return json.loads(text)

        except json.JSONDecodeError as exc:
            last_error = exc
            break
        except Exception as exc:
            last_error = exc
            status_code = getattr(exc, "status_code", None)
            if status_code in retryable_statuses and attempt < 3:
                time.sleep(1.5 * (2 ** attempt))
                continue
            if attempt < 3 and ("503" in str(exc) or "UNAVAILABLE" in str(exc)):
                time.sleep(1.5 * (2 ** attempt))
                continue
            break

    raise RuntimeError(f"Gemini request failed: {last_error}")


@app.route("/")
def home():
    return render_template("index.html")


@app.post("/debug")
def debug_code():
    try:
        data = request.get_json(silent=True) or {}

        language = (data.get("language") or "").strip()
        code = (data.get("code") or "").strip()
        error_message = (data.get("error_message") or "").strip()
        expected_behavior = (data.get("expected_behavior") or "").strip()

        if not language:
            return jsonify({"error": "Please select a programming language."}), 400

        if not code:
            return jsonify({"error": "Please paste your code before debugging."}), 400

        if len(code) > 30000:
            return jsonify({"error": "Code is too large. Please keep it under 30,000 characters."}), 400

        result = generate_debug_response(
            language=language,
            code=code,
            error_message=error_message,
            expected_behavior=expected_behavior,
        )

        return jsonify(result)

    except RuntimeError as exc:
        return jsonify({
            "error": str(exc),
            "hint": "Gemini may be temporarily busy. Please try again."
        }), 503
    except Exception:
        return jsonify({
            "error": "Something went wrong while debugging the code."
        }), 500


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
