"""Smoke test: install the built wheel and import the package."""

import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: check_package.py <wheel-path>")
        return 2
    wheel = Path(sys.argv[1])
    if not wheel.exists():
        print(f"Wheel not found: {wheel}")
        return 2
    with tempfile.TemporaryDirectory() as td:
        venv = Path(td) / ".venv"
        subprocess.run(
            [sys.executable, "-m", "venv", str(venv)],
            check=True,
            capture_output=True,
        )
        pip = str(venv / "bin" / "pip")
        subprocess.run([pip, "install", str(wheel)], check=True, capture_output=True)
        python = str(venv / "bin" / "python")
        result = subprocess.run(
            [python, "-c", "import mnemofold; print(mnemofold.__version__)"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print("Import failed:", result.stderr)
            return 1
        version = result.stdout.strip()
        print(f"Installed mnemofold {version}")
        cli = str(venv / "bin" / "mnemofold")
        cli_result = subprocess.run([cli, "--version"], capture_output=True, text=True)
        if cli_result.returncode != 0:
            print("CLI entry point failed:", cli_result.stderr)
            return 1
        print(f"CLI entry point OK: {cli_result.stdout.strip()}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
