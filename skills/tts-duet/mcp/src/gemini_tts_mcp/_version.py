"""Package version — single source of truth.

Kept in sync with ``pyproject.toml`` ``[project].version``. Imported by
``server.py`` for ``meta_health.package_version`` and by
``cli.py`` for ``--version``.
"""

__version__ = "0.3.0"
