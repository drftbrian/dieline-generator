"""Write the OpenAPI schema to a file without starting the server.

Usage: uv run python scripts/export_openapi.py <output.json>
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.main import app  # noqa: E402

out = Path(sys.argv[1])
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(app.openapi(), ensure_ascii=False, indent=2))
