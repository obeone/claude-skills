#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""
Regression tests for extract_dockerfile_blocks.py's D9 classifier.

Stdlib-only (`unittest`), no markdown files, no Docker, no network: these
tests exercise `classify_block()` directly against synthetic `FencedBlock`
instances, so they run in milliseconds and can't be skipped by a missing
daemon or a moved fixture file.

Usage
-----

    uv run skills/dockerfile-best-practices/scripts/tests/test_extract_dockerfile_blocks.py
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from types import ModuleType


def _load_extractor() -> ModuleType:
    """Dynamically import the sibling extract_dockerfile_blocks.py.

    Returns
    -------
    ModuleType
        The imported module under test.

    Notes
    -----
    Loaded by explicit file path, the same technique the module under test
    uses to import analyze_dockerfile.py, so these tests work regardless of
    the working directory `uv run` is invoked from.
    """
    module_path = Path(__file__).resolve().parent.parent / "extract_dockerfile_blocks.py"
    spec = importlib.util.spec_from_file_location("extract_dockerfile_blocks", module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load module under test from {module_path}")
    module = importlib.util.module_from_spec(spec)
    # Register in sys.modules *before* exec: the module under test combines
    # `from __future__ import annotations` with @dataclass, and dataclass's
    # own forward-reference resolution looks the module up by name in
    # sys.modules while decorating FencedBlock/BlockReport. Skipping this
    # step raises AttributeError deep inside dataclasses.py.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


edb = _load_extractor()


class ClassifyBlockTests(unittest.TestCase):
    """Regression coverage for the D9 selection rule in classify_block()."""

    def _block(self, text: str) -> "edb.FencedBlock":
        """Build a FencedBlock from a triple-quoted Dockerfile snippet.

        Parameters
        ----------
        text : str
            Dockerfile content; a leading newline (from a triple-quoted
            string) is stripped before splitting into lines.

        Returns
        -------
        FencedBlock
            A block as if extracted from line 1 of some markdown file.
        """
        lines = text.strip("\n").split("\n")
        return edb.FencedBlock(source_file=Path("test.md"), first_content_line=1, lines=lines)

    def test_heredoc_body_does_not_smuggle_a_marker(self):
        """A '# Fragment:'-looking line inside a RUN heredoc must be ignored.

        Regression for the false negative found in code review: the marker
        scan used to check every line in the block, so a heredoc body
        writing a line that happens to start with '# Fragment:' (to a file
        like /etc/motd, nothing to do with the Dockerfile itself) caused a
        complete, buildable image with a genuine defect to be silently
        skipped as a non-buildable fragment. This block has both FROM and
        CMD, so it must validate.
        """
        block = self._block("""
            FROM python:3.12-slim
            RUN cat <<'EOF2' > /etc/motd
            # Fragment: this is app data
            EOF2
            COPY --from=composer:latest /usr/bin/composer /usr/bin/composer
            CMD ["python", "app.py"]
        """)
        status, skip_reason = edb.classify_block(block)
        self.assertEqual(status, "validated")
        self.assertIsNone(skip_reason)

    def test_heredoc_body_anti_pattern_lookalike_also_ignored(self):
        """Same regression, '# Anti-pattern:' form, inside a heredoc body."""
        block = self._block("""
            FROM alpine:3
            RUN cat <<'EOF2' > /etc/issue
            # Anti-pattern: also just file content, not a doc comment
            EOF2
            ENTRYPOINT ["/bin/true"]
        """)
        status, skip_reason = edb.classify_block(block)
        self.assertEqual(status, "validated")
        self.assertIsNone(skip_reason)

    def test_leading_fragment_marker_still_skips(self):
        """A genuine leading '# Fragment:' comment must still be honoured."""
        block = self._block("""
            # Fragment: illustrates the digest form only, not buildable
            FROM python:3.12-slim@sha256:<digest>
        """)
        status, skip_reason = edb.classify_block(block)
        self.assertEqual(status, "skipped")
        self.assertEqual(skip_reason, "fragment")

    def test_leading_anti_pattern_marker_still_skips_a_complete_image(self):
        """A leading marker skips a block even when it has FROM + CMD."""
        block = self._block("""
            # Anti-pattern: complete image, but still deliberately wrong
            FROM python:3.12-slim
            COPY --chown=app:app . /app
            RUN groupadd -r app && useradd -r -g app app
            CMD ["python", "app.py"]
        """)
        status, skip_reason = edb.classify_block(block)
        self.assertEqual(status, "skipped")
        self.assertEqual(skip_reason, "anti-pattern")

    def test_marker_after_a_blank_leading_line_is_still_a_header_marker(self):
        """A blank line before the marker doesn't move it out of the header."""
        block = self._block("""

            # Fragment: blank line above is still part of the header
            FROM python:3.12-slim@sha256:<digest>
        """)
        status, skip_reason = edb.classify_block(block)
        self.assertEqual(status, "skipped")
        self.assertEqual(skip_reason, "fragment")

    def test_no_from_skips_as_snippet(self):
        """A block with no FROM at all is a snippet, not a fragment."""
        block = self._block("""
            RUN --mount=type=cache,target=/root/.cache/pip pip install -r requirements.txt
        """)
        status, skip_reason = edb.classify_block(block)
        self.assertEqual(status, "skipped")
        self.assertEqual(skip_reason, "no-from")

    def test_from_without_cmd_or_entrypoint_skips_as_snippet(self):
        """A block with FROM but no CMD/ENTRYPOINT is a snippet, no marker needed."""
        block = self._block("""
            FROM node:20-alpine
            COPY --link . /app
        """)
        status, skip_reason = edb.classify_block(block)
        self.assertEqual(status, "skipped")
        self.assertEqual(skip_reason, "no-cmd-entrypoint")


if __name__ == "__main__":
    unittest.main()
