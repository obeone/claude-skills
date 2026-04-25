"""Package version — single source of truth.

Kept in sync with ``pyproject.toml`` ``[project].version``. Imported by
``server.py`` for ``meta.health.package_version`` and by
``cli.py`` for ``--version``.
"""

__version__ = "0.1.0"
