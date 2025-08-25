#!/usr/bin/env python3
"""Run every offline example; fail fast on the first non-zero exit.

Examples are discovered as ``examples/*/run.py`` and executed with the
same interpreter in sorted order, so the run is reproducible. Used by
``make examples`` and CI; no network, GPU, or external data required.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    scripts = sorted((ROOT / "examples").glob("*/run.py"))
    if not scripts:
        print("no examples found", file=sys.stderr)
        return 1
    for script in scripts:
        name = script.parent.name
        print(f"--- example: {name} ---", flush=True)
        result = subprocess.run([sys.executable, str(script)], cwd=ROOT)
        if result.returncode != 0:
            print(f"example {name} failed with exit {result.returncode}", file=sys.stderr)
            return result.returncode
    print(f"all {len(scripts)} examples passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
