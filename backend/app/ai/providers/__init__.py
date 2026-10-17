from app.ai.providers.base import ImageProvider
from app.ai.providers.gemini import GeminiProvider

# The one image provider. Read it at call time (``providers.PROVIDER``) so tests can swap it.
PROVIDER: ImageProvider = GeminiProvider()
