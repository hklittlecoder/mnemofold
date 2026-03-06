"""Single source of truth for the package version.

Hatchling reads ``__version__`` from this file at build time; the test
suite cross-checks it against the changelog so releases cannot drift.
"""

__version__ = "0.1.3"
