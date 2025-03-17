"""Version consistency checks.

No hardcoded literals: the package version lives in ``_version.py`` and
every other surface (package attribute, pyproject declaration, changelog
top entry) must agree with it, so a bump that misses one place fails here.
"""

import re
from pathlib import Path

import mnemofold
from mnemofold._version import __version__

ROOT = Path(__file__).resolve().parents[1]


def test_package_attribute_matches_version_module():
    assert mnemofold.__version__ == __version__


def test_pyproject_declares_dynamic_version_from_module():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'dynamic = ["version"]' in text
    assert "[tool.hatch.version]" in text
    assert 'path = "src/mnemofold/_version.py"' in text
    # no static version literal may sneak back in
    assert not re.search(r'^version = "', text, re.MULTILINE)


def test_changelog_top_entry_matches_version():
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    match = re.search(r"^## \[(\d+\.\d+\.\d+)\]", text, re.MULTILINE)
    assert match is not None, "changelog must start with a versioned entry"
    assert match.group(1) == __version__


def test_version_is_plain_semver():
    assert re.fullmatch(r"\d+\.\d+\.\d+", __version__)
