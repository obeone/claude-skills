"""Guard rail: INSTALL.md must stay in sync with SKILL.md ``metadata.version``.

Every time the skill's ``metadata.version`` is bumped, INSTALL.md
must reflect the same version in:

- the ``releases/download/v<X.Y.Z>/tts-duet.skill`` URL (§3 Claude Code
  path);
- every ``git+…@v<X.Y.Z>#subdirectory=…`` registration pin (§5).

This test parses both files and fails loudly if the versions diverge.
"""

from __future__ import annotations

import re
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[2]
SKILL_MD = SKILL_ROOT / "SKILL.md"
INSTALL_MD = SKILL_ROOT / "INSTALL.md"


def _read_skill_version() -> str:
    text = SKILL_MD.read_text(encoding="utf-8")
    match = re.search(r'^\s*version:\s*"([0-9]+\.[0-9]+\.[0-9]+)"', text, re.MULTILINE)
    assert match, "SKILL.md does not declare metadata.version"
    return match.group(1)


def test_install_md_release_download_matches_skill_version() -> None:
    skill_version = _read_skill_version()
    install_text = INSTALL_MD.read_text(encoding="utf-8")
    pattern = re.compile(r"releases/download/v([0-9]+\.[0-9]+\.[0-9]+)/tts-duet\.skill")
    found = set(pattern.findall(install_text))
    assert found, "INSTALL.md is missing the releases/download URL"
    assert found == {skill_version}, (
        f"INSTALL.md references release v{found} "
        f"but SKILL.md is at v{skill_version}. "
        "Bump every reference in INSTALL.md when you bump SKILL.md."
    )


def test_install_md_git_pins_match_skill_version() -> None:
    skill_version = _read_skill_version()
    install_text = INSTALL_MD.read_text(encoding="utf-8")
    # Match real registration pins, but ignore the example arrow line
    # that intentionally shows a *next* tag (e.g. "→ @v2.3.0").
    pattern = re.compile(
        r"git\+https://github\.com/obeone/claude-skills@v([0-9]+\.[0-9]+\.[0-9]+)"
    )
    found = set(pattern.findall(install_text))
    assert found, "INSTALL.md is missing git+ registration pins"
    assert found == {skill_version}, (
        f"INSTALL.md pins git+ refs at v{found} "
        f"but SKILL.md is at v{skill_version}. "
        "Bump every @v<X.Y.Z> in INSTALL.md when you bump SKILL.md."
    )
