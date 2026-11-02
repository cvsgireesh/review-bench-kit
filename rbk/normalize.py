"""Turn a bot's raw output into the one format the rest of the kit reads.

Normalized review file:
    {"comments": [{"path": str, "line": int, "body": str, "severity"?: str, "category"?: str}],
     "usage": {"input_tokens"?: int, "output_tokens"?: int, "cache_read_tokens"?: int, "cost_usd"?: float}}
"""

from __future__ import annotations

import json
from pathlib import Path


def generic(raw: dict) -> dict:
    comments = []
    for c in raw.get("comments", []):
        if not c.get("body") or not c.get("path"):
            raise ValueError(f"comment needs path and body: {c!r}")
        comments.append({k: c[k] for k in ("path", "line", "body", "severity", "category") if k in c})
        comments[-1].setdefault("line", 0)
    return {"comments": comments, "usage": dict(raw.get("usage", {}))}


def ocr(raw: dict) -> dict:
    """OpenCodeReview `ocr review --format json` output."""
    comments = []
    for c in raw.get("comments", []):
        sev, cat = c.get("severity", ""), c.get("category", "")
        tag = "/".join(x for x in (sev, cat) if x)
        body = (f"[{tag}] " if tag else "") + c.get("content", "")
        if c.get("suggestion_code"):
            body += "\n\nSuggested change:\n" + c["suggestion_code"]
        comments.append({"path": c["path"], "line": c.get("start_line") or 0, "body": body,
                         "severity": sev, "category": cat})
    s = raw.get("summary") or {}
    usage = {k: s[k] for k in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens") if k in s}
    return {"comments": comments, "usage": usage}


NORMALIZERS = {"generic": generic, "ocr": ocr}


def load_output(path: Path, kind: str) -> dict:
    return NORMALIZERS[kind](json.loads(path.read_text()))
