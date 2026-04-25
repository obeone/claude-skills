"""``python -m gemini_tts_mcp`` entrypoint."""

from __future__ import annotations

import sys

from gemini_tts_mcp.cli import main


if __name__ == "__main__":
    sys.exit(main())
