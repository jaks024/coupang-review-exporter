"""Run the Vercel-style API locally on port 8000."""

from __future__ import annotations

import sys
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from api.reviews import handler  # noqa: E402


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", 8000), handler)
    print("Review API listening on http://127.0.0.1:8000/api/reviews")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

