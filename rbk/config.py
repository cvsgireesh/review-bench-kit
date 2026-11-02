"""Config loading. Secrets stay in the environment: any `${VAR}` in a value is expanded at use time."""

from __future__ import annotations

import os
import re
from pathlib import Path

import yaml

_VAR = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def expand(value: str) -> str:
    """Replace ${VAR} with the environment value; a missing variable is an error, never an empty string."""
    missing = [m for m in _VAR.findall(value) if m not in os.environ]
    if missing:
        raise SystemExit(f"environment variable(s) not set: {', '.join(sorted(set(missing)))}")
    return _VAR.sub(lambda m: os.environ[m.group(1)], value)


def load(path: str | Path) -> dict:
    cfg = yaml.safe_load(Path(path).read_text())
    arms = cfg.get("arms") or {}
    if not arms:
        raise SystemExit(f"{path}: no arms defined")
    for name, arm in arms.items():
        if "cmd" not in arm:
            raise SystemExit(f"{path}: arm '{name}' has no cmd")
        if arm.get("normalize", "generic") not in ("generic", "ocr"):
            raise SystemExit(f"{path}: arm '{name}' has unknown normalize '{arm['normalize']}'")
    base = cfg.get("baseline")
    if base is not None and base not in arms:
        raise SystemExit(f"{path}: baseline '{base}' is not an arm")
    return cfg
