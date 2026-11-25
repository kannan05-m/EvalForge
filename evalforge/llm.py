from __future__ import annotations

import json
import os
import urllib.error
import urllib.request


def chat_completion(prompt: str) -> str:
    """Call an OpenAI-compatible chat-completions endpoint configured by environment."""
    api_key = os.environ.get("OPENAI_API_KEY")
    base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    model = os.environ.get("EVALFORGE_MODEL", "gpt-4o-mini")
    if not api_key:
        raise RuntimeError("Set OPENAI_API_KEY before using synthetic generation or the LLM judge.")
    body = json.dumps(
        {"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.3}
    ).encode()
    request = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            result = json.loads(response.read())
    except (urllib.error.URLError, json.JSONDecodeError) as error:
        raise RuntimeError(f"LLM request failed: {error}") from error
    try:
        return result["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as error:
        raise RuntimeError("LLM response did not contain a chat completion.") from error
