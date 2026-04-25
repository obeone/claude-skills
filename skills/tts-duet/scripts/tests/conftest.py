"""
Pytest configuration for the tts-duet skill-side test suite.

Adds the skill's ``scripts/`` directory to ``sys.path`` so tests can
import from ``lib.*`` and ``tools.*`` without any packaging glue.
"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
