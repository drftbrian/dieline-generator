"""Check that each AI provider key in backend/.env authenticates.

Uses model-listing endpoints only (no generation, no cost). Never prints key values.

Usage: uv run python scripts/check_providers.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings  # noqa: E402


def check_anthropic(key: str) -> str:
    import anthropic

    models = anthropic.Anthropic(api_key=key).models.list(limit=100)
    return f"{len(models.data)} models"


def check_gemini(key: str) -> str:
    from google import genai

    client = genai.Client(api_key=key)  # keep a reference; the pager needs an open client
    names = [m.name for m in client.models.list()]
    images = [n for n in names if "image" in n]
    return f"{len(names)} models, image-capable: {', '.join(images) or 'none'}"


def main() -> int:
    settings = get_settings()
    checks = [
        ("Anthropic (Claude)", settings.anthropic_api_key, check_anthropic),
        ("Google Gemini (Nano Banana)", settings.gemini_api_key, check_gemini),
    ]
    failed = 0
    for name, secret, check in checks:
        if secret is None or not secret.get_secret_value():
            print(f"✗ {name}: key not set")
            failed += 1
            continue
        try:
            print(f"✓ {name}: {check(secret.get_secret_value())}")
        except Exception as e:  # noqa: BLE001
            print(f"✗ {name}: {type(e).__name__}: {str(e)[:200]}")
            failed += 1
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
