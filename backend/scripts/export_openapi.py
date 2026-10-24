"""Writes the API's OpenAPI spec; the web app generates its typed client from it.

uv run python scripts/export_openapi.py ../web/openapi.json
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.main import app  # noqa: E402

out = Path(sys.argv[1] if len(sys.argv) > 1 else "openapi.json")
out.write_text(json.dumps(app.openapi(), indent=1) + "\n")
print(f"wrote {out}")
